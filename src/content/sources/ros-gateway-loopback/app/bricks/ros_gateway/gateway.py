# SPDX-License-Identifier: MIT

import json
import os
import queue
import threading
import time

from arduino.app_utils import brick
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

from .protocol import (
    ProtocolError,
    build_message,
    decode_message,
    validate_cmd_vel,
    validate_heartbeat,
    validate_hello,
    validate_mode_change,
    validate_sequence,
)


@brick
class RosGateway:
    """App Lab 与原生 ROS 2 之间的 WebSocket 网关。"""

    def __init__(
        self,
        host=None,
        port=None,
        path=None,
        max_vx=None,
        max_vy=None,
        max_wz=None,
        command_timeout_ms=None,
        heartbeat_timeout_ms=None,
        outbound_queue_size=32,
    ):
        """
        @description         : 创建 ROS Gateway 并读取 App Lab 注入的配置变量
        @param host          : 容器内监听地址，None 时读取环境变量
        @param port          : WebSocket 监听端口，None 时读取环境变量
        @param path          : WebSocket 请求路径，None 时读取环境变量
        @param max_vx        : vx 绝对值上限
        @param max_vy        : vy 绝对值上限
        @param max_wz        : wz 绝对值上限
        @param command_timeout_ms : 速度指令超时毫秒数
        @param heartbeat_timeout_ms : 连接心跳超时毫秒数
        @param outbound_queue_size : 有界出站队列长度
        @return              : 无返回值
        """
        self._host = host or os.getenv("ROS_GATEWAY_HOST", "0.0.0.0")
        self._port = self._read_int(port, "ROS_GATEWAY_PORT", 8765, 1, 65535)
        self._path = path or os.getenv("ROS_GATEWAY_PATH", "/ros")
        self._limits = {
            "vx": self._read_float(max_vx, "ROS_GATEWAY_MAX_VX", 0.8, 0.0),
            "vy": self._read_float(max_vy, "ROS_GATEWAY_MAX_VY", 0.8, 0.0),
            "wz": self._read_float(max_wz, "ROS_GATEWAY_MAX_WZ", 1.5, 0.0),
        }
        self._command_timeout_ms = self._read_int(
            command_timeout_ms,
            "ROS_GATEWAY_COMMAND_TIMEOUT_MS",
            300,
            1,
            60_000,
        )
        self._heartbeat_timeout_ms = self._read_int(
            heartbeat_timeout_ms,
            "ROS_GATEWAY_HEARTBEAT_TIMEOUT_MS",
            3000,
            self._command_timeout_ms,
            120_000,
        )
        self._outbound = queue.Queue(maxsize=max(1, int(outbound_queue_size)))
        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._server = None
        self._server_thread = None
        self._active_connection = None
        self._connected = False
        self._client_node = None
        self._mode = "IDLE"
        self._last_sequence = -1
        self._outbound_sequence = 0
        self._last_rx_monotonic = 0.0
        self._last_cmd_monotonic = 0.0
        self._last_server_heartbeat = 0.0
        self._watchdog_triggered = True
        self._server_error = None
        self._dropped_messages = 0
        self._cmd_vel_callback = None
        self._mode_change_callback = None
        self._stop_callback = None

    def start(self):
        """
        @description         : 启动非阻塞 WebSocket 服务线程
        @param               : 无参数
        @return              : 无返回值
        """
        if self._server_thread and self._server_thread.is_alive():
            return

        self._stop_event.clear()
        self._ready_event.clear()
        self._server_thread = threading.Thread(
            target=self._run_server,
            name="ros-gateway-server",
            daemon=True,
        )
        self._server_thread.start()

        if not self._ready_event.wait(timeout=5.0):
            print("[ros_gateway] server did not become ready within 5 seconds", flush=True)

    def stop(self):
        """
        @description         : 关闭连接、释放端口并等待服务线程退出
        @param               : 无参数
        @return              : 无返回值
        """
        self._stop_event.set()
        with self._state_lock:
            server = self._server
        if server is not None:
            server.shutdown(reason="App Lab application is stopping")
        if self._server_thread and self._server_thread is not threading.current_thread():
            self._server_thread.join(timeout=5.0)
        self._invoke_stop("app_shutdown")

    def on_cmd_vel(self, callback):
        """
        @description         : 注册已通过安全校验的 cmd_vel 回调
        @param callback      : 接收规范化速度字典的函数
        @return              : 当前 RosGateway 实例
        """
        self._cmd_vel_callback = callback
        return self

    def on_mode_change(self, callback):
        """
        @description         : 注册模式切换回调
        @param callback      : 接收目标模式并返回是否允许的函数
        @return              : 当前 RosGateway 实例
        """
        self._mode_change_callback = callback
        return self

    def on_stop(self, callback):
        """
        @description         : 注册通信异常或命令超时的统一安全停车回调
        @param callback      : 接收停车原因字符串的函数
        @return              : 当前 RosGateway 实例
        """
        self._stop_callback = callback
        return self

    def is_ros_connected(self):
        """
        @description         : 查询是否存在已完成握手的 ROS 2 客户端
        @param               : 无参数
        @return              : 已连接返回 True，否则返回 False
        """
        with self._state_lock:
            return self._connected

    def get_status(self):
        """
        @description         : 获取连接、模式、队列和服务错误状态快照
        @param               : 无参数
        @return              : 状态字典
        """
        with self._state_lock:
            return {
                "connected": self._connected,
                "client_node": self._client_node,
                "mode": self._mode,
                "server_ready": self._ready_event.is_set(),
                "server_error": self._server_error,
                "queued_messages": self._outbound.qsize(),
                "dropped_messages": self._dropped_messages,
            }

    def publish_base_state(self, state):
        """
        @description         : 校验并将模拟或真实底盘状态加入有界发送队列
        @param state         : 底盘状态字段字典
        @return              : 成功入队返回 True，无客户端或失败返回 False
        """
        required_fields = {
            "mode",
            "enabled",
            "wheel_position",
            "wheel_velocity",
            "battery_voltage",
            "estop",
            "fault_code",
        }
        missing_fields = required_fields - state.keys()
        if missing_fields:
            raise ValueError(f"base_state missing fields: {sorted(missing_fields)}")
        self._validate_four_values("wheel_position", state["wheel_position"])
        self._validate_four_values("wheel_velocity", state["wheel_velocity"])
        return self._enqueue("base_state", **state)

    def publish_imu(self, imu):
        """
        @description         : 将 IMU 状态加入有界发送队列
        @param imu           : orientation、angular_velocity、linear_acceleration 字典
        @return              : 成功入队返回 True，无客户端或失败返回 False
        """
        self._validate_vector("orientation", imu.get("orientation"), 4)
        self._validate_vector("angular_velocity", imu.get("angular_velocity"), 3)
        self._validate_vector("linear_acceleration", imu.get("linear_acceleration"), 3)
        return self._enqueue("imu", **imu)

    def publish_diagnostics(self, diagnostics):
        """
        @description         : 将诊断字典加入有界发送队列
        @param diagnostics   : 可 JSON 序列化的诊断字段
        @return              : 成功入队返回 True，无客户端或失败返回 False
        """
        if not isinstance(diagnostics, dict):
            raise ValueError("diagnostics must be a dictionary")
        return self._enqueue("diagnostics", **diagnostics)

    @staticmethod
    def _read_int(explicit_value, environment_name, default_value, minimum, maximum):
        """
        @description         : 从显式参数或环境变量读取受范围约束的整数
        @param explicit_value : 调用方显式提供的值
        @param environment_name : 环境变量名称
        @param default_value : 默认值
        @param minimum       : 最小允许值
        @param maximum       : 最大允许值
        @return              : 校验后的整数
        """
        value = explicit_value
        if value is None:
            value = os.getenv(environment_name, str(default_value))
        parsed = int(value)
        if parsed < minimum or parsed > maximum:
            raise ValueError(f"{environment_name} must be between {minimum} and {maximum}")
        return parsed

    @staticmethod
    def _read_float(explicit_value, environment_name, default_value, minimum):
        """
        @description         : 从显式参数或环境变量读取有下限约束的浮点数
        @param explicit_value : 调用方显式提供的值
        @param environment_name : 环境变量名称
        @param default_value : 默认值
        @param minimum       : 最小允许值
        @return              : 校验后的浮点数
        """
        value = explicit_value
        if value is None:
            value = os.getenv(environment_name, str(default_value))
        parsed = float(value)
        if parsed <= minimum:
            raise ValueError(f"{environment_name} must be greater than {minimum}")
        return parsed

    @staticmethod
    def _validate_vector(field_name, value, expected_length):
        """
        @description         : 校验固定长度数值数组
        @param field_name    : 用于错误信息的字段名
        @param value         : 待校验数组
        @param expected_length : 期望数组长度
        @return              : 无返回值
        """
        if not isinstance(value, (list, tuple)) or len(value) != expected_length:
            raise ValueError(f"{field_name} must contain {expected_length} values")
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise ValueError(f"{field_name} must contain only numbers")

    @classmethod
    def _validate_four_values(cls, field_name, value):
        """
        @description         : 校验四轮位置或速度数组
        @param field_name    : 用于错误信息的字段名
        @param value         : 待校验四元素数组
        @return              : 无返回值
        """
        cls._validate_vector(field_name, value, 4)

    def _run_server(self):
        """
        @description         : 在专用线程中绑定端口并运行同步 WebSocket 服务
        @param               : 无参数
        @return              : 无返回值
        """
        try:
            with serve(
                self._handle_connection,
                self._host,
                self._port,
                compression=None,
                ping_interval=1.0,
                ping_timeout=1.0,
                close_timeout=2.0,
                max_size=16 * 1024,
                max_queue=16,
            ) as server:
                with self._state_lock:
                    self._server = server
                    self._server_error = None
                self._ready_event.set()
                print(
                    f"[ros_gateway] listening on ws://{self._host}:{self._port}{self._path}",
                    flush=True,
                )
                server.serve_forever()
        except Exception as exc:
            with self._state_lock:
                self._server_error = f"{type(exc).__name__}: {exc}"
            self._ready_event.set()
            print(f"[ros_gateway] server failed: {type(exc).__name__}: {exc}", flush=True)
        finally:
            with self._state_lock:
                self._server = None
            self._ready_event.clear()

    def _handle_connection(self, websocket):
        """
        @description         : 处理单个 WebSocket 客户端的握手、收发和安全清理
        @param websocket     : websockets 同步服务端连接对象
        @return              : 无返回值
        """
        request_path = websocket.request.path.split("?", 1)[0]
        if request_path != self._path:
            websocket.close(1008, f"expected path {self._path}")
            return

        with self._state_lock:
            if self._active_connection is not None:
                websocket.close(1013, "another ROS 2 client already owns the gateway")
                return
            self._active_connection = websocket

        was_connected = False
        disconnect_reason = "connection_closed"
        try:
            raw_hello = websocket.recv(timeout=2.0)
            hello = decode_message(raw_hello)
            client_node = validate_hello(hello)
            current = time.monotonic()
            with self._state_lock:
                self._connected = True
                self._client_node = client_node
                self._last_sequence = -1
                self._last_rx_monotonic = current
                self._last_cmd_monotonic = 0.0
                self._last_server_heartbeat = current
                self._watchdog_triggered = True
            was_connected = True
            self._send_json(
                websocket,
                build_message(
                    "hello",
                    role="app",
                    node="ros-gateway-loopback",
                ),
            )
            print(f"[ros_gateway] ROS 2 connected: node={client_node}", flush=True)

            while not self._stop_event.is_set():
                self._service_timers(websocket)
                self._drain_outbound(websocket)
                try:
                    raw_message = websocket.recv(timeout=0.05)
                except TimeoutError:
                    continue
                self._process_message(websocket, raw_message)
        except ProtocolError as exc:
            disconnect_reason = exc.code
            self._send_error(websocket, exc)
            websocket.close(1008, str(exc))
        except ConnectionClosed as exc:
            disconnect_reason = f"connection_closed:{exc.code}"
        except Exception as exc:
            disconnect_reason = f"handler_error:{type(exc).__name__}"
            print(f"[ros_gateway] connection handler error: {type(exc).__name__}: {exc}", flush=True)
        finally:
            with self._state_lock:
                if self._active_connection is websocket:
                    self._active_connection = None
                    self._connected = False
                    self._client_node = None
                    self._mode = "IDLE"
            self._clear_outbound_queue()
            if was_connected:
                print(f"[ros_gateway] ROS 2 disconnected: {disconnect_reason}", flush=True)
                self._invoke_stop(disconnect_reason)

    def _process_message(self, websocket, raw_message):
        """
        @description         : 分派一个客户端消息并执行对应协议校验
        @param websocket     : 当前活动 WebSocket 连接
        @param raw_message   : 原始文本消息
        @return              : 无返回值
        """
        try:
            message = decode_message(raw_message)
            message_type = message["type"]
            if message_type == "hello":
                raise ProtocolError("duplicate_hello", "hello is only valid as the first message")

            with self._state_lock:
                sequence = validate_sequence(message, self._last_sequence)

            if message_type == "heartbeat":
                validate_heartbeat(message)
                with self._state_lock:
                    self._last_sequence = sequence
                    self._last_rx_monotonic = time.monotonic()
                return

            if message_type == "mode_change":
                target_mode = validate_mode_change(message)
                accepted = True
                if self._mode_change_callback is not None:
                    accepted = self._mode_change_callback(target_mode) is not False
                if accepted:
                    with self._state_lock:
                        self._mode = target_mode
                with self._state_lock:
                    self._last_sequence = sequence
                    self._last_rx_monotonic = time.monotonic()
                self._send_json(
                    websocket,
                    build_message(
                        "ack",
                        sequence=sequence,
                        command="mode_change",
                        accepted=accepted,
                        mode=self._mode,
                    ),
                )
                return

            if message_type == "cmd_vel":
                with self._state_lock:
                    mode = self._mode
                command = validate_cmd_vel(
                    message,
                    mode,
                    self._limits,
                    self._command_timeout_ms,
                )
                with self._state_lock:
                    current = time.monotonic()
                    self._last_sequence = sequence
                    self._last_rx_monotonic = current
                    self._last_cmd_monotonic = current
                    self._watchdog_triggered = False
                if self._cmd_vel_callback is not None:
                    self._cmd_vel_callback(command)
                return

            raise ProtocolError(
                "unknown_type",
                f"unsupported message type: {message_type}",
                sequence,
            )
        except ProtocolError as exc:
            self._send_error(websocket, exc)

    def _service_timers(self, websocket):
        """
        @description         : 发送服务端心跳并执行连接与速度命令看门狗
        @param websocket     : 当前活动 WebSocket 连接
        @return              : 无返回值
        """
        current = time.monotonic()
        with self._state_lock:
            last_rx = self._last_rx_monotonic
            last_cmd = self._last_cmd_monotonic
            watchdog_triggered = self._watchdog_triggered
            last_heartbeat = self._last_server_heartbeat

        if current - last_rx > self._heartbeat_timeout_ms / 1000.0:
            raise ProtocolError("heartbeat_timeout", "client heartbeat timed out")

        if last_cmd > 0.0 and not watchdog_triggered:
            if current - last_cmd > self._command_timeout_ms / 1000.0:
                with self._state_lock:
                    self._watchdog_triggered = True
                self._invoke_stop("cmd_vel_timeout")

        if current - last_heartbeat >= 1.0:
            self._send_json(websocket, self._next_message("heartbeat"))
            with self._state_lock:
                self._last_server_heartbeat = current

    def _enqueue(self, message_type, **fields):
        """
        @description         : 将出站消息加入有界队列，满时丢弃最旧消息
        @param message_type  : 出站消息类型
        @param fields        : 出站消息字段
        @return              : 有活动客户端时返回 True，否则返回 False
        """
        if not self.is_ros_connected():
            return False
        message = self._next_message(message_type, **fields)
        try:
            self._outbound.put_nowait(message)
        except queue.Full:
            try:
                self._outbound.get_nowait()
            except queue.Empty:
                pass
            self._outbound.put_nowait(message)
            with self._state_lock:
                self._dropped_messages += 1
        return True

    def _next_message(self, message_type, **fields):
        """
        @description         : 分配严格递增的服务端序号并构造消息
        @param message_type  : 出站消息类型
        @param fields        : 出站消息字段
        @return              : 已构造的消息字典
        """
        with self._state_lock:
            self._outbound_sequence += 1
            sequence = self._outbound_sequence
        return build_message(message_type, sequence=sequence, **fields)

    def _drain_outbound(self, websocket):
        """
        @description         : 在连接处理线程中发送当前队列内的全部消息
        @param websocket     : 当前活动 WebSocket 连接
        @return              : 无返回值
        """
        while True:
            try:
                message = self._outbound.get_nowait()
            except queue.Empty:
                return
            self._send_json(websocket, message)

    def _send_error(self, websocket, error):
        """
        @description         : 向客户端发送结构化协议错误
        @param websocket     : 当前活动 WebSocket 连接
        @param error         : ProtocolError 实例
        @return              : 无返回值
        """
        payload = build_message(
            "error",
            code=error.code,
            message=str(error),
        )
        if error.seq is not None:
            payload["seq"] = error.seq
        self._send_json(websocket, payload)
        print(f"[ros_gateway] rejected message: {error.code}: {error}", flush=True)

    @staticmethod
    def _send_json(websocket, message):
        """
        @description         : 将字典编码为紧凑 UTF-8 JSON 文本并发送
        @param websocket     : 当前活动 WebSocket 连接
        @param message       : 待发送消息字典
        @return              : 无返回值
        """
        websocket.send(json.dumps(message, ensure_ascii=False, separators=(",", ":")))

    def _invoke_stop(self, reason):
        """
        @description         : 安全调用统一停车回调并隔离回调异常
        @param reason        : 停车原因
        @return              : 无返回值
        """
        if self._stop_callback is None:
            return
        try:
            self._stop_callback(reason)
        except Exception as exc:
            print(f"[ros_gateway] stop callback failed: {type(exc).__name__}: {exc}", flush=True)

    def _clear_outbound_queue(self):
        """
        @description         : 清空断线客户端尚未发送的出站消息
        @param               : 无参数
        @return              : 无返回值
        """
        while True:
            try:
                self._outbound.get_nowait()
            except queue.Empty:
                return
