# SPDX-License-Identifier: MIT

import json
import queue
import threading
import time

from websockets.sync.client import connect


PROTOCOL_VERSION = 1


class MotorWebSocketClient:
    """在后台线程中维护单电机ROS 2到App Lab的WebSocket连接。"""

    def __init__(
        self,
        websocket_url,
        reconnect_interval,
        heartbeat_interval,
        command_timeout,
        message_callback,
        connection_callback,
        log_callback,
        initial_mode="IDLE",
    ):
        """
        @description         : 创建带重连、心跳和有界命令队列的单电机客户端
        @param websocket_url : App Lab WebSocket地址
        @param reconnect_interval : 断线重连间隔秒数
        @param heartbeat_interval : 应用层心跳间隔秒数
        @param command_timeout : 本地RPM命令过期秒数
        @param message_callback : 服务端消息回调
        @param connection_callback : 连接状态回调
        @param log_callback : 线程安全日志回调
        @param initial_mode : 每次连接后的初始安全模式
        @return              : 无返回值
        """
        self._url = str(websocket_url)
        self._reconnect_interval = max(0.1, float(reconnect_interval))
        self._heartbeat_interval = max(0.1, float(heartbeat_interval))
        self._command_timeout = max(0.05, float(command_timeout))
        self._message_callback = message_callback
        self._connection_callback = connection_callback
        self._log_callback = log_callback
        self._initial_mode = str(initial_mode)
        self._stop_event = threading.Event()
        self._thread = None
        self._state_lock = threading.Lock()
        self._connected = False
        self._sequence = 0
        self._latest_speed = queue.Queue(maxsize=1)
        self._control_queue = queue.Queue(maxsize=16)

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
            name="zdt-motor-websocket-client",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        """
        @description         : 请求客户端线程停止并清空所有未发送命令
        @param               : 无参数
        @return              : 无返回值
        """
        self._stop_event.set()
        self._clear_command_queues()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5.0)
        self._set_connected(False)

    def is_connected(self):
        """
        @description         : 查询WebSocket握手是否完成
        @param               : 无参数
        @return              : 已连接返回True，否则返回False
        """
        with self._state_lock:
            return self._connected

    def send_motor_speed(self, rpm, acceleration_level):
        """
        @description         : 用最新RPM覆盖尚未发送的旧RPM命令
        @param rpm           : 整数目标转速
        @param acceleration_level : 加减速档位0至255
        @return              : 已进入本地队列返回True
        """
        command = {
            "timestamp_ms": self._now_ms(),
            "rpm": int(rpm),
            "acceleration_level": int(acceleration_level),
        }
        self._replace_queue_item(self._latest_speed, command)
        return True

    def request_enable(self, enabled):
        """
        @description         : 按安全顺序请求遥控模式和单电机使能状态
        @param enabled       : True请求使能，False请求停车失能
        @return              : 所有控制消息成功入队返回True
        """
        timestamp = self._now_ms()
        if enabled:
            messages = (
                {"type": "mode_change", "timestamp_ms": timestamp, "mode": "ROS_TELEOP"},
                {"type": "motor_enable", "timestamp_ms": timestamp, "enabled": True},
            )
        else:
            self._clear_queue(self._latest_speed)
            messages = (
                {"type": "motor_enable", "timestamp_ms": timestamp, "enabled": False},
                {"type": "mode_change", "timestamp_ms": timestamp, "mode": "IDLE"},
            )
        return self._enqueue_control_batch(messages)

    def request_stop(self):
        """
        @description         : 丢弃待发速度并请求停车后进入IDLE模式
        @param               : 无参数
        @return              : 所有停车消息成功入队返回True
        """
        self._clear_queue(self._latest_speed)
        timestamp = self._now_ms()
        return self._enqueue_control_batch(
            (
                {"type": "motor_stop", "timestamp_ms": timestamp},
                {"type": "mode_change", "timestamp_ms": timestamp, "mode": "IDLE"},
            )
        )

    def _enqueue_control_batch(self, messages):
        """
        @description         : 将一组有顺序依赖的控制消息加入有界队列
        @param messages      : 控制消息字典序列
        @return              : 全部成功入队返回True，空间不足返回False
        """
        messages = tuple(messages)
        if self._control_queue.qsize() + len(messages) > self._control_queue.maxsize:
            self._log("warning", "motor control queue is full")
            return False
        for message in messages:
            self._control_queue.put_nowait(dict(message))
        return True

    def _run(self):
        """
        @description         : 反复连接服务端并在断线后安全清队列再重连
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
                self._clear_command_queues()

            if not self._stop_event.is_set():
                self._stop_event.wait(self._reconnect_interval)

    def _run_connection(self):
        """
        @description         : 完成一次握手并执行同线程收发循环
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
                    "node": "ventuno_zdt_motor_bridge",
                },
            )
            hello = self._receive_json(websocket, timeout=3.0)
            if hello.get("version") != PROTOCOL_VERSION:
                raise RuntimeError("server protocol version mismatch")
            if hello.get("type") != "hello" or hello.get("role") != "app":
                raise RuntimeError("invalid server hello")

            self._sequence = 0
            self._set_connected(True)
            self._enqueue_control_batch(
                (
                    {
                        "type": "mode_change",
                        "timestamp_ms": self._now_ms(),
                        "mode": self._initial_mode,
                    },
                )
            )
            next_heartbeat = time.monotonic()

            while not self._stop_event.is_set():
                current = time.monotonic()
                if current >= next_heartbeat:
                    self._send_json(websocket, self._next_message("heartbeat"))
                    next_heartbeat = current + self._heartbeat_interval

                self._send_control_messages(websocket)
                self._send_latest_speed(websocket)

                try:
                    message = self._receive_json(websocket, timeout=0.05)
                except TimeoutError:
                    continue
                self._message_callback(message)

    def _send_control_messages(self, websocket):
        """
        @description         : 按入队顺序发送使能、停车和模式控制消息
        @param websocket     : 当前WebSocket连接
        @return              : 无返回值
        """
        while True:
            try:
                request = self._control_queue.get_nowait()
            except queue.Empty:
                return
            message_type = request.pop("type")
            self._send_json(websocket, self._next_message(message_type, **request))

    def _send_latest_speed(self, websocket):
        """
        @description         : 仅发送最新且未过期的单电机RPM命令
        @param websocket     : 当前WebSocket连接
        @return              : 无返回值
        """
        try:
            command = self._latest_speed.get_nowait()
        except queue.Empty:
            return

        age_seconds = (self._now_ms() - command["timestamp_ms"]) / 1000.0
        if age_seconds > self._command_timeout:
            self._log("warning", f"dropping stale motor RPM: age={age_seconds:.3f}s")
            return
        self._send_json(websocket, self._next_message("motor_set_speed", **command))

    def _next_message(self, message_type, **fields):
        """
        @description         : 为出站报文分配严格递增序号并补齐公共字段
        @param message_type  : 协议消息类型
        @param fields        : 消息专用字段
        @return              : 可直接JSON编码的消息字典
        """
        self._sequence += 1
        message = {
            "version": PROTOCOL_VERSION,
            "type": message_type,
            "seq": self._sequence,
            "timestamp_ms": self._now_ms(),
        }
        message.update(fields)
        return message

    @staticmethod
    def _send_json(websocket, message):
        """
        @description         : 发送紧凑JSON文本帧
        @param websocket     : 当前WebSocket连接
        @param message       : 待发送消息字典
        @return              : 无返回值
        """
        websocket.send(json.dumps(message, ensure_ascii=False, separators=(",", ":")))

    @staticmethod
    def _receive_json(websocket, timeout):
        """
        @description         : 接收并校验JSON对象文本帧
        @param websocket     : 当前WebSocket连接
        @param timeout       : 接收超时秒数
        @return              : 解析后的消息字典
        """
        message = json.loads(websocket.recv(timeout=timeout))
        if not isinstance(message, dict):
            raise RuntimeError("server JSON root must be an object")
        return message

    def _set_connected(self, connected):
        """
        @description         : 更新连接状态并仅在状态变化时调用回调
        @param connected     : 新连接状态
        @return              : 无返回值
        """
        connected = bool(connected)
        with self._state_lock:
            if self._connected == connected:
                return
            self._connected = connected
        self._connection_callback(connected)

    def _clear_command_queues(self):
        """
        @description         : 清除断线期间不允许重放的全部控制和速度命令
        @param               : 无参数
        @return              : 无返回值
        """
        self._clear_queue(self._latest_speed)
        self._clear_queue(self._control_queue)

    @staticmethod
    def _clear_queue(target_queue):
        """
        @description         : 清空指定本地队列
        @param target_queue  : 需要清空的Queue对象
        @return              : 无返回值
        """
        while True:
            try:
                target_queue.get_nowait()
            except queue.Empty:
                return

    @staticmethod
    def _replace_queue_item(target_queue, value):
        """
        @description         : 队列满时丢弃旧值并只保留最新值
        @param target_queue  : 最大长度为1的目标队列
        @param value         : 新队列值
        @return              : 无返回值
        """
        try:
            target_queue.put_nowait(value)
            return
        except queue.Full:
            pass
        try:
            target_queue.get_nowait()
        except queue.Empty:
            pass
        target_queue.put_nowait(value)

    def _log(self, level, message):
        """
        @description         : 将后台线程日志转发给ROS 2节点
        @param level         : 日志级别
        @param message       : 日志文本
        @return              : 无返回值
        """
        self._log_callback(level, message)

    @staticmethod
    def _now_ms():
        """
        @description         : 获取Unix毫秒时间戳
        @param               : 无参数
        @return              : 当前Unix毫秒时间戳
        """
        return time.time_ns() // 1_000_000
