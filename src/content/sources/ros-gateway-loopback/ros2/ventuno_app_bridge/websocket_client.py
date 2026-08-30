# SPDX-License-Identifier: MIT

import json
import queue
import threading
import time

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect


PROTOCOL_VERSION = 1


class WebSocketBridgeClient:
    """在后台线程中维护 App Lab WebSocket 连接。"""

    def __init__(
        self,
        websocket_url,
        reconnect_interval,
        heartbeat_interval,
        command_timeout,
        message_callback,
        connection_callback,
        log_callback,
        initial_mode="ROS_TELEOP",
    ):
        """
        @description         : 创建带重连、心跳和有界队列的 WebSocket 客户端
        @param websocket_url : App Lab WebSocket 地址
        @param reconnect_interval : 断线后的重连间隔秒数
        @param heartbeat_interval : 应用层心跳间隔秒数
        @param command_timeout : 本地速度命令过期时间秒数
        @param message_callback : 接收服务端消息的回调
        @param connection_callback : 连接状态变化回调
        @param log_callback : 线程安全日志回调
        @param initial_mode : 每次握手后请求的底盘模式
        @return              : 无返回值
        """
        self._url = websocket_url
        self._reconnect_interval = max(0.1, float(reconnect_interval))
        self._heartbeat_interval = max(0.1, float(heartbeat_interval))
        self._command_timeout = max(0.05, float(command_timeout))
        self._message_callback = message_callback
        self._connection_callback = connection_callback
        self._log_callback = log_callback
        self._initial_mode = initial_mode
        self._stop_event = threading.Event()
        self._thread = None
        self._state_lock = threading.Lock()
        self._connected = False
        self._sequence = 0
        self._latest_command = queue.Queue(maxsize=1)
        self._control_queue = queue.Queue(maxsize=8)

    def start(self):
        """
        @description         : 启动自动重连后台线程
        @param               : 无参数
        @return              : 无返回值
        """
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="ventuno-websocket-client",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        """
        @description         : 请求客户端线程停止并等待退出
        @param               : 无参数
        @return              : 无返回值
        """
        self._stop_event.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5.0)
        self._set_connected(False)

    def is_connected(self):
        """
        @description         : 查询当前 WebSocket 握手状态
        @param               : 无参数
        @return              : 已连接返回 True，否则返回 False
        """
        with self._state_lock:
            return self._connected

    def send_cmd_vel(self, vx, vy, wz):
        """
        @description         : 用最新速度覆盖尚未发送的旧速度，避免控制队列增长
        @param vx            : 纵向速度，单位 m/s
        @param vy            : 横向速度，单位 m/s
        @param wz            : 偏航角速度，单位 rad/s
        @return              : 已进入本地队列返回 True
        """
        command = {
            "timestamp_ms": self._now_ms(),
            "vx": float(vx),
            "vy": float(vy),
            "wz": float(wz),
        }
        self._replace_queue_item(self._latest_command, command)
        return True

    def request_mode(self, mode):
        """
        @description         : 将需要应答的模式切换请求加入有界控制队列
        @param mode          : 目标模式字符串
        @return              : 成功入队返回 True，队列满返回 False
        """
        request = {
            "type": "mode_change",
            "timestamp_ms": self._now_ms(),
            "mode": mode,
        }
        try:
            self._control_queue.put_nowait(request)
            return True
        except queue.Full:
            self._log("warning", "mode request queue is full")
            return False

    def _run(self):
        """
        @description         : 反复连接服务端并在断线后按配置等待重连
        @param               : 无参数
        @return              : 无返回值
        """
        while not self._stop_event.is_set():
            try:
                self._run_connection()
            except Exception as exc:
                self._log("warning", f"WebSocket disconnected: {type(exc).__name__}: {exc}")
            finally:
                self._set_connected(False)

            if not self._stop_event.is_set():
                self._stop_event.wait(self._reconnect_interval)

    def _run_connection(self):
        """
        @description         : 完成单次握手并执行同线程收发循环
        @param               : 无参数
        @return              : 无返回值
        """
        self._log("info", f"connecting to {self._url}")
        with connect(
            self._url,
            open_timeout=3.0,
            close_timeout=2.0,
            ping_interval=1.0,
            ping_timeout=1.0,
            max_size=16 * 1024,
            max_queue=16,
        ) as websocket:
            self._send_json(
                websocket,
                {
                    "version": PROTOCOL_VERSION,
                    "type": "hello",
                    "role": "ros2",
                    "node": "ventuno_app_bridge_node",
                },
            )
            hello = self._receive_json(websocket, timeout=3.0)
            if hello.get("version") != PROTOCOL_VERSION:
                raise RuntimeError("server protocol version mismatch")
            if hello.get("type") != "hello" or hello.get("role") != "app":
                raise RuntimeError("invalid server hello")

            self._sequence = 0
            self._set_connected(True)
            self.request_mode(self._initial_mode)
            next_heartbeat = time.monotonic()

            while not self._stop_event.is_set():
                current = time.monotonic()
                if current >= next_heartbeat:
                    self._send_json(websocket, self._next_message("heartbeat"))
                    next_heartbeat = current + self._heartbeat_interval

                self._send_control_messages(websocket)
                self._send_latest_command(websocket)

                try:
                    message = self._receive_json(websocket, timeout=0.05)
                except TimeoutError:
                    continue
                self._message_callback(message)

    def _send_control_messages(self, websocket):
        """
        @description         : 发送当前有界控制队列中的模式请求
        @param websocket     : 当前 WebSocket 连接
        @return              : 无返回值
        """
        while True:
            try:
                request = self._control_queue.get_nowait()
            except queue.Empty:
                return
            message_type = request.pop("type")
            self._send_json(websocket, self._next_message(message_type, **request))

    def _send_latest_command(self, websocket):
        """
        @description         : 发送最新且未过期的速度命令
        @param websocket     : 当前 WebSocket 连接
        @return              : 无返回值
        """
        try:
            command = self._latest_command.get_nowait()
        except queue.Empty:
            return

        age_seconds = (self._now_ms() - command["timestamp_ms"]) / 1000.0
        if age_seconds > self._command_timeout:
            self._log("warning", f"dropping stale local cmd_vel: age={age_seconds:.3f}s")
            return
        self._send_json(websocket, self._next_message("cmd_vel", **command))

    def _next_message(self, message_type, **fields):
        """
        @description         : 构造具有统一版本和严格递增序号的客户端消息
        @param message_type  : 消息类型
        @param fields        : 附加字段
        @return              : 待发送消息字典
        """
        self._sequence += 1
        message = {
            "version": PROTOCOL_VERSION,
            "type": message_type,
            "seq": self._sequence,
            "timestamp_ms": fields.pop("timestamp_ms", self._now_ms()),
        }
        message.update(fields)
        return message

    def _set_connected(self, connected):
        """
        @description         : 原子更新连接状态并仅在变化时通知 ROS 2 节点
        @param connected     : 新连接状态
        @return              : 无返回值
        """
        changed = False
        with self._state_lock:
            if self._connected != connected:
                self._connected = connected
                changed = True
        if changed:
            self._connection_callback(connected)

    def _log(self, level, message):
        """
        @description         : 将后台线程日志转交给 ROS 2 节点
        @param level         : info、warning 或 error
        @param message       : 日志文本
        @return              : 无返回值
        """
        self._log_callback(level, message)

    @staticmethod
    def _replace_queue_item(target_queue, item):
        """
        @description         : 用新元素替换单元素队列中的旧元素
        @param target_queue  : 目标有界队列
        @param item          : 新元素
        @return              : 无返回值
        """
        try:
            target_queue.get_nowait()
        except queue.Empty:
            pass
        target_queue.put_nowait(item)

    @staticmethod
    def _send_json(websocket, message):
        """
        @description         : 将消息编码为紧凑 JSON 文本并发送
        @param websocket     : 当前 WebSocket 连接
        @param message       : 待发送消息字典
        @return              : 无返回值
        """
        websocket.send(json.dumps(message, separators=(",", ":")))

    @staticmethod
    def _receive_json(websocket, timeout):
        """
        @description         : 接收、解析并基础校验服务端 JSON 消息
        @param websocket     : 当前 WebSocket 连接
        @param timeout       : 接收超时秒数
        @return              : 已解析消息字典
        """
        raw_message = websocket.recv(timeout=timeout)
        message = json.loads(raw_message)
        if not isinstance(message, dict):
            raise RuntimeError("server JSON root must be an object")
        return message

    @staticmethod
    def _now_ms():
        """
        @description         : 获取 Unix 毫秒时间戳
        @param               : 无参数
        @return              : 当前 Unix 毫秒时间戳
        """
        return time.time_ns() // 1_000_000
