# SPDX-License-Identifier: MIT
"""Thread-safe public CanBus with one receiver and bounded dispatch queues."""

from collections.abc import Mapping
import queue
import threading
import time

from .backends import CanBackend, SocketCANBackend
from .compat import brick
from .config import (
    validate_device,
    validate_queue_size,
    validate_timeout,
)
from .definition import MessageDefinition
from .errors import (
    CANBackendError,
    CANConfigurationError,
    CANError,
    CANMessageError,
    CANTimeoutError,
)
from .frame import CanFrame


_NO_FRAME = object()


@brick
class CanBus:
    """Own one backend, one receiver thread, and independent receive queues."""

    def __init__(
        self,
        interface="can0",
        messages=None,
        backend=None,
        raw_queue_size=256,
        message_queue_size=64,
        receiver_poll_s=0.05,
    ):
        """
        @description         : 创建总线对象、命名报文路由和有界接收队列
        @param self          : 当前CanBus对象
        @param interface     : Linux SocketCAN接口名称，默认can0
        @param messages      : 名称到MessageDefinition的映射
        @param backend       : 可选的自定义CanBackend，测试时可传FakeBackend
        @param raw_queue_size: 原始报文队列最大帧数
        @param message_queue_size: 每个命名报文队列最大帧数
        @param receiver_poll_s: 接收线程单次等待秒数
        @return              : 无
        """
        self.interface = validate_device(interface)
        self.raw_queue_size = validate_queue_size(
            raw_queue_size,
            "raw_queue_size",
        )
        self.message_queue_size = validate_queue_size(
            message_queue_size,
            "message_queue_size",
        )
        self.receiver_poll_s = validate_timeout(receiver_poll_s)
        if self.receiver_poll_s <= 0.0:
            raise CANConfigurationError(
                "receiver_poll_s must be greater than zero"
            )

        if backend is None:
            backend = SocketCANBackend(device=self.interface)
        if not isinstance(backend, CanBackend):
            raise CANConfigurationError(
                "backend must implement the CanBackend contract"
            )
        if (
            isinstance(backend, SocketCANBackend)
            and backend.device != self.interface
        ):
            raise CANConfigurationError(
                "SocketCAN backend device does not match CanBus interface"
            )
        self._backend = backend
        self._messages = self._validate_messages(messages)

        self._raw_frames = queue.Queue(maxsize=self.raw_queue_size)
        self._message_queues = {
            name: queue.Queue(maxsize=self.message_queue_size)
            for name, definition in self._messages.items()
            if definition.allows_rx
        }
        self._routes = {}
        for name, definition in self._messages.items():
            if definition.allows_rx:
                self._routes.setdefault(definition.match_key(), []).append(name)

        self._lifecycle_lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._receiver_thread = None
        self._receiver_error = None
        self._is_open = False

        self.dropped_raw_frames = 0
        self.dropped_message_frames = 0
        self.dropped_message_frames_by_name = {
            name: 0 for name in self._message_queues
        }
        self.received_frames = 0
        self.sent_frames = 0

    @staticmethod
    def _message_name(name):
        """
        @description         : 校验并规范化命名报文名称
        @param name          : 用户提供的报文名称
        @return              : 去除首尾空白后的名称
        """
        if not isinstance(name, str):
            raise CANConfigurationError("message name must be a string")
        normalized = name.strip()
        if not normalized:
            raise CANConfigurationError("message name must not be empty")
        return normalized

    @classmethod
    def _validate_messages(cls, messages):
        """
        @description         : 校验整张命名报文定义表
        @param cls           : CanBus类
        @param messages      : 名称到MessageDefinition的映射或None
        @return              : 规范化后的普通字典
        """
        if messages is None:
            return {}
        if not isinstance(messages, Mapping):
            raise CANConfigurationError(
                "messages must be a mapping of names to MessageDefinition"
            )

        normalized = {}
        for raw_name, definition in messages.items():
            name = cls._message_name(raw_name)
            if name in normalized:
                raise CANConfigurationError(
                    f"duplicate normalized message name '{name}'"
                )
            if not isinstance(definition, MessageDefinition):
                raise CANConfigurationError(
                    f"message '{name}' must be a MessageDefinition"
                )
            normalized[name] = definition
        return normalized

    @property
    def is_open(self):
        """
        @description         : 判断当前CanBus是否已经打开后端
        @param self          : 当前CanBus对象
        @return              : 已打开时返回True，否则返回False
        """
        return self._is_open

    def _clear_queue(self, target_queue):
        """
        @description         : 非阻塞清空一个内部接收队列
        @param self          : 当前CanBus对象
        @param target_queue  : 需要清空的queue.Queue
        @return              : 无
        """
        while True:
            try:
                target_queue.get_nowait()
            except queue.Empty:
                return

    def _clear_receive_queues(self):
        """
        @description         : 打开总线前清空原始队列和所有命名队列
        @param self          : 当前CanBus对象
        @return              : 无
        """
        self._clear_queue(self._raw_frames)
        for target_queue in self._message_queues.values():
            self._clear_queue(target_queue)

    @staticmethod
    def _put_latest(target_queue, frame):
        """
        @description         : 将新帧放入有界队列，满时丢弃最旧帧
        @param target_queue  : 接收新帧的queue.Queue
        @param frame         : 需要入队的CanFrame
        @return              : 本次是否丢弃过一帧旧数据
        """
        try:
            target_queue.put_nowait(frame)
            return False
        except queue.Full:
            pass

        dropped = False
        try:
            target_queue.get_nowait()
            dropped = True
        except queue.Empty:
            pass

        try:
            target_queue.put_nowait(frame)
        except queue.Full:
            # A competing consumer/producer changed the queue between calls.
            # The single receiver is the only producer in V1, so this branch
            # is defensive and never blocks the receiver.
            return dropped
        return dropped

    def _run_receiver(self):
        """
        @description         : 在唯一接收线程内读取后端并分发到各个队列
        @param self          : 当前CanBus对象
        @return              : 无；关闭或发生后端错误时退出
        """
        while not self._stop_event.is_set():
            try:
                frame = self._backend.receive(self.receiver_poll_s)
            except CANError as error:
                self._receiver_error = error
                self._stop_event.set()
                return
            except Exception as error:
                self._receiver_error = CANBackendError(
                    f"receiver thread failed: {error}"
                )
                self._stop_event.set()
                return

            if frame is None:
                continue
            if not isinstance(frame, CanFrame):
                self._receiver_error = CANBackendError(
                    "backend receive returned a non-CanFrame value"
                )
                self._stop_event.set()
                return

            self.received_frames += 1
            if self._put_latest(self._raw_frames, frame):
                self.dropped_raw_frames += 1

            for name in self._routes.get(
                (frame.arbitration_id, frame.is_extended, frame.is_fd),
                (),
            ):
                if self._put_latest(self._message_queues[name], frame):
                    self.dropped_message_frames += 1
                    self.dropped_message_frames_by_name[name] += 1

    def _raise_receiver_error(self):
        """
        @description         : 在调用线程中重新抛出接收线程保存的错误
        @param self          : 当前CanBus对象
        @return              : 无；存在错误时抛出统一CAN异常
        """
        if self._receiver_error is not None:
            error = self._receiver_error
            if isinstance(error, CANError):
                raise error
            raise CANBackendError(str(error)) from error

    def _ensure_open(self):
        """
        @description         : 确认总线已打开
        @param self          : 当前CanBus对象
        @return              : 无；未打开时抛出CANBackendError
        """
        if not self._is_open:
            raise CANBackendError("CAN bus is not open")

    def open(self):
        """
        @description         : 打开后端并启动唯一的接收线程
        @param self          : 当前CanBus对象
        @return              : 当前CanBus，便于with语句和链式使用
        """
        with self._lifecycle_lock:
            if self._is_open:
                return self

            self._clear_receive_queues()
            self._receiver_error = None
            self._stop_event.clear()
            try:
                self._backend.open()
                self._is_open = True
                self._receiver_thread = threading.Thread(
                    target=self._run_receiver,
                    name=f"generic-can-rx-{self.interface}",
                    daemon=True,
                )
                self._receiver_thread.start()
            except CANError:
                self._is_open = False
                self._receiver_thread = None
                try:
                    self._backend.close()
                except Exception:
                    pass
                raise
            except Exception as error:
                self._is_open = False
                self._receiver_thread = None
                try:
                    self._backend.close()
                except Exception:
                    pass
                raise CANBackendError(
                    f"failed to open CAN bus '{self.interface}': {error}"
                ) from error
            return self

    def close(self):
        """
        @description         : 停止接收线程并关闭后端，重复调用安全
        @param self          : 当前CanBus对象
        @return              : 无
        """
        with self._lifecycle_lock:
            if not self._is_open:
                return

            self._is_open = False
            self._stop_event.set()
            receiver_thread = self._receiver_thread
            self._receiver_thread = None

            if receiver_thread is not None:
                receiver_thread.join(
                    timeout=max(1.0, self.receiver_poll_s * 4.0)
                )

            close_error = None
            with self._send_lock:
                try:
                    self._backend.close()
                except CANError as error:
                    close_error = error
                except Exception as error:
                    close_error = CANBackendError(
                        f"failed to close CAN bus '{self.interface}': {error}"
                    )

            if receiver_thread is not None and receiver_thread.is_alive():
                receiver_thread.join(timeout=0.25)
                if receiver_thread.is_alive() and close_error is None:
                    close_error = CANBackendError(
                        "receiver thread did not stop"
                    )

            if close_error is not None:
                raise close_error

    def __enter__(self):
        """
        @description         : 进入with代码块时打开总线
        @param self          : 当前CanBus对象
        @return              : 已打开的当前CanBus
        """
        return self.open()

    def __exit__(self, exc_type, exc_value, traceback):
        """
        @description         : 离开with代码块时关闭总线且不吞掉原异常
        @param self          : 当前CanBus对象
        @param exc_type      : with代码块异常类型或None
        @param exc_value     : with代码块异常对象或None
        @param traceback     : with代码块异常调用栈或None
        @return              : False，表示原异常需要继续传播
        """
        self.close()
        return False

    def send_frame(self, frame):
        """
        @description         : 发送一帧已经构造并校验过的CanFrame
        @param self          : 当前CanBus对象
        @param frame         : 需要发送的CanFrame
        @return              : 成功发送的同一个CanFrame
        """
        if not isinstance(frame, CanFrame):
            raise CANConfigurationError(
                "send_frame requires a CanFrame object"
            )
        self._ensure_open()
        self._raise_receiver_error()

        with self._send_lock:
            self._ensure_open()
            try:
                self._backend.send(frame)
            except CANError:
                raise
            except Exception as error:
                raise CANBackendError(
                    f"backend failed to send frame: {error}"
                ) from error
            self.sent_frames += 1
        return frame

    def _queue_receive(self, target_queue, timeout_s):
        """
        @description         : 从指定内部队列等待一帧并同步检查接收线程错误
        @param self          : 当前CanBus对象
        @param target_queue  : 需要读取的queue.Queue
        @param timeout_s     : 最长等待秒数
        @return              : CanFrame或内部无帧标记
        """
        timeout = validate_timeout(timeout_s)
        self._ensure_open()

        if timeout == 0.0:
            try:
                return target_queue.get_nowait()
            except queue.Empty:
                self._raise_receiver_error()
                return _NO_FRAME

        deadline = time.monotonic() + timeout
        while True:
            self._ensure_open()
            self._raise_receiver_error()
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return _NO_FRAME
            try:
                return target_queue.get(
                    timeout=min(remaining, self.receiver_poll_s)
                )
            except queue.Empty:
                continue

    def receive_frame(self, timeout_s=1.0):
        """
        @description         : 从原始队列读取下一帧CAN数据
        @param self          : 当前CanBus对象
        @param timeout_s     : 最长等待秒数，零表示立即返回
        @return              : 收到时返回CanFrame，超时返回None
        """
        frame = self._queue_receive(self._raw_frames, timeout_s)
        return None if frame is _NO_FRAME else frame

    def _definition(self, name):
        """
        @description         : 按名称查找一条已经校验的报文定义
        @param self          : 当前CanBus对象
        @param name          : 报文名称
        @return              : 规范化名称和MessageDefinition组成的元组
        """
        normalized = self._message_name(name)
        try:
            return normalized, self._messages[normalized]
        except KeyError as error:
            raise CANMessageError(
                f"unknown message '{normalized}'"
            ) from error

    def send(self, name, **values):
        """
        @description         : 使用固定DATA或encode函数构造并发送命名报文
        @param self          : 当前CanBus对象
        @param name          : 需要发送的命名报文名称
        @param values        : 传给该报文encode函数的关键字参数
        @return              : 成功发送的CanFrame
        """
        normalized_name, definition = self._definition(name)
        if not definition.allows_tx:
            raise CANMessageError(
                f"message '{normalized_name}' does not allow tx"
            )

        try:
            if definition.fixed_data is not None:
                if values:
                    raise CANMessageError(
                        f"fixed message '{normalized_name}' takes no values"
                    )
                data = definition.fixed_data
            else:
                data = definition.encode(**values)

            frame = CanFrame(
                arbitration_id=definition.arbitration_id,
                data=data,
                is_extended=definition.is_extended,
                is_fd=definition.is_fd,
                bitrate_switch=definition.bitrate_switch,
            )
        except CANMessageError:
            raise
        except Exception as error:
            raise CANMessageError(
                f"failed to encode message '{normalized_name}': {error}"
            ) from error

        return self.send_frame(frame)

    def receive(self, name, timeout_s=1.0):
        """
        @description         : 等待命名报文并按定义解码
        @param self          : 当前CanBus对象
        @param name          : 需要接收的命名报文名称
        @param timeout_s     : 最长等待秒数
        @return              : 有decode时返回工程值，否则返回CanFrame
        """
        normalized_name, definition = self._definition(name)
        if not definition.allows_rx:
            raise CANMessageError(
                f"message '{normalized_name}' does not allow rx"
            )

        frame = self._queue_receive(
            self._message_queues[normalized_name],
            timeout_s,
        )
        if frame is _NO_FRAME:
            raise CANTimeoutError(
                f"timed out waiting for message '{normalized_name}'"
            )
        if definition.decode is None:
            return frame

        try:
            return definition.decode(frame.data)
        except Exception as error:
            raise CANMessageError(
                f"failed to decode message '{normalized_name}': {error}"
            ) from error

    def describe(self):
        """
        @description         : 导出可JSON序列化的配置、状态和队列统计
        @param self          : 当前CanBus对象
        @return              : 诊断信息字典
        """
        messages = {}
        for name, definition in self._messages.items():
            messages[name] = {
                "arbitration_id": definition.arbitration_id,
                "arbitration_id_hex": f"0x{definition.arbitration_id:X}",
                "direction": definition.direction,
                "is_extended": definition.is_extended,
                "is_fd": definition.is_fd,
                "bitrate_switch": definition.bitrate_switch,
                "payload_source": (
                    "fixed_data"
                    if definition.fixed_data is not None
                    else (
                        "encode" if definition.encode is not None else None
                    )
                ),
                "has_decode": definition.decode is not None,
            }

        receiver_thread = self._receiver_thread
        return {
            "interface": self.interface,
            "is_open": self._is_open,
            "receiver_alive": bool(
                receiver_thread is not None
                and receiver_thread.is_alive()
            ),
            "receiver_error": (
                None
                if self._receiver_error is None
                else str(self._receiver_error)
            ),
            "raw_queue_size": self.raw_queue_size,
            "message_queue_size": self.message_queue_size,
            "raw_queue_depth": self._raw_frames.qsize(),
            "message_queue_depths": {
                name: target_queue.qsize()
                for name, target_queue in self._message_queues.items()
            },
            "sent_frames": self.sent_frames,
            "received_frames": self.received_frames,
            "dropped_raw_frames": self.dropped_raw_frames,
            "dropped_message_frames": self.dropped_message_frames,
            "dropped_message_frames_by_name": dict(
                self.dropped_message_frames_by_name
            ),
            "ignored_error_frames": int(
                getattr(self._backend, "ignored_error_frames", 0)
            ),
            "ignored_remote_frames": int(
                getattr(self._backend, "ignored_remote_frames", 0)
            ),
            "messages": messages,
        }
