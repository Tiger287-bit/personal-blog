"""一个 Backend 共享给多个 ZDTMotor 的请求、响应和事件分发器。"""

from dataclasses import dataclass, replace
import queue
import threading
import time

from .backends import CanBackend, SocketCANBackend
from .bus_base import BusKind, ZDTMotorBus
from .commands import common
from .config import (
    ChecksumType,
    parse_checksum_type,
    validate_motor_id,
    validate_nonnegative_number,
    validate_positive_number,
)
from .endpoints import SocketCanEndpoint
from .errors import (
    ZDTBackendError,
    ZDTBusBusyError,
    ZDTConfigurationError,
    ZDTProtocolError,
    ZDTTimeoutError,
    ZDTUnsupportedFeatureError,
)
from .messages import LogicalCommand
from .protocols import (
    ZDTCanProtocol,
    parse_arbitration_id,
    reassemble_can_frames,
)


ASYNC_COMPLETION_STATUS = 0x9F
ASYNC_COMPLETION_FUNCTIONS = frozenset({0xF5, 0x9A, 0xFD})
DEFAULT_EVENT_QUEUE_SIZE = 256


@dataclass
class _PendingRequest:
    """内部等待项。"""

    expected_length: int
    result_queue: queue.Queue


@dataclass
class _Assembly:
    """内部多包重组状态。"""

    frames: list
    expected_length: int | None
    next_packet: int
    started_at: float


@dataclass(frozen=True)
class BusTrace:
    """供监视脚本显示的原始帧记录。"""

    direction: str
    frame: object


class ZDTCanBus(ZDTMotorBus):
    """支持一个 SocketCAN 总线共享多个电机对象。"""

    def __init__(
        self,
        *,
        name="zdt_can",
        endpoint=None,
        interface="can",
        device=None,
        checksum=ChecksumType.FIXED_6B,
        backend=None,
        default_timeout_s=0.5,
        event_queue_size=DEFAULT_EVENT_QUEUE_SIZE,
        trace_callback=None,
    ):
        """
        @description         : 配置共享CAN总线但不自动修改或拉起系统接口
        @param name          : 便于日志和诊断识别的总线名称
        @param endpoint      : SocketCanEndpoint接口配置对象
        @param interface     : 兼容旧代码，仅支持can或socketcan
        @param device        : 兼容旧代码的SocketCAN接口名，推荐改用endpoint
        @param checksum      : ZDT校验方式
        @param backend       : 可选CanBackend，单元测试可传FakeBackend
        @param default_timeout_s: 默认应答超时秒数
        @param event_queue_size: 异步事件队列最大容量
        @param trace_callback: 可选原始帧回调
        @return              : 无返回值
        """
        normalized_default_timeout = validate_positive_number(
            "default_timeout_s",
            default_timeout_s,
        )
        if (
            isinstance(event_queue_size, bool)
            or not isinstance(event_queue_size, int)
            or event_queue_size <= 0
        ):
            raise ZDTConfigurationError(
                "event_queue_size must be a positive integer"
            )
        if not isinstance(name, str) or not name.strip():
            raise ZDTConfigurationError("CAN bus name must not be empty")
        normalized_interface = str(interface).lower()
        if normalized_interface not in ("can", "socketcan"):
            raise ZDTUnsupportedFeatureError(
                f"backend '{interface}' is reserved for a future bus class"
            )
        if endpoint is not None and device is not None:
            raise ZDTConfigurationError(
                "use endpoint or legacy device, not both"
            )
        if endpoint is not None and not isinstance(endpoint, SocketCanEndpoint):
            raise TypeError("endpoint must be a SocketCanEndpoint")
        if endpoint is None:
            resolved_device = device
            if resolved_device is None and isinstance(backend, SocketCANBackend):
                resolved_device = backend.device
            endpoint = SocketCanEndpoint(interface=resolved_device or "can0")
        if backend is None:
            backend = SocketCANBackend(device=endpoint.interface)
        if not isinstance(backend, CanBackend):
            raise TypeError("backend must implement CanBackend")
        if (
            isinstance(backend, SocketCANBackend)
            and backend.device != endpoint.interface
        ):
            raise ZDTConfigurationError(
                "SocketCAN backend device does not match endpoint interface"
            )
        self.name = name.strip()
        self._endpoint = endpoint
        self.backend = backend
        self.device = endpoint.interface
        self._checksum = parse_checksum_type(checksum)
        self.protocol = ZDTCanProtocol(self.checksum)
        self._default_timeout_s = normalized_default_timeout
        self.trace_callback = trace_callback
        self._pending = {}
        self._assemblies = {}
        self._events = queue.Queue(maxsize=event_queue_size)
        self._dropped_event_count = 0
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._receiver_thread = None
        self._receiver_error = None
        self._last_protocol_error = None

    @property
    def checksum(self):
        """
        @description         : 获取当前总线使用的ZDT校验方式
        @param               : 无参数
        @return              : ChecksumType枚举值
        """
        return self._checksum

    @property
    def default_timeout_s(self):
        """
        @description         : 获取当前总线默认请求超时时间
        @param               : 无参数
        @return              : 超时秒数
        """
        return self._default_timeout_s

    @property
    def dropped_event_count(self):
        """
        @description         : 获取当前总线对象累计丢弃的异步事件数量
        @param               : 无参数
        @return              : 累计丢弃事件数量
        """
        return self._dropped_event_count

    @property
    def kind(self):
        """
        @description         : 标明当前对象是一条CAN总线
        @param               : 无参数
        @return              : BusKind.CAN
        """
        return BusKind.CAN

    @property
    def endpoint(self):
        """
        @description         : 获取当前CAN总线使用的SocketCAN端点
        @param               : 无参数
        @return              : SocketCanEndpoint对象
        """
        return self._endpoint

    def describe(self):
        """
        @description         : 返回当前CAN总线的可读配置和运行状态
        @param               : 无参数
        @return              : 只包含基础数据类型的字典
        """
        return {
            "name": self.name,
            "kind": self.kind.value,
            "endpoint": self.endpoint.describe(),
            "checksum": self.checksum.value,
            "backend": type(self.backend).__name__,
            "state": "open" if self.is_open else "closed",
        }

    @property
    def is_open(self):
        """
        @description         : 判断接收线程是否正在运行
        @param               : 无参数
        @return              : 已打开返回True
        """
        return self._receiver_thread is not None and self._receiver_thread.is_alive()

    @property
    def last_protocol_error(self):
        """
        @description         : 获取最近一条非致命协议异常用于诊断
        @param               : 无参数
        @return              : 最近异常对象或None
        """
        return self._last_protocol_error

    def open(self):
        """
        @description         : 打开Backend并启动响应分发线程
        @param               : 无参数
        @return              : 当前ZDTCanBus
        """
        if self.is_open:
            return self
        self.backend.open()
        self._stop_event.clear()
        self._receiver_error = None
        self._last_protocol_error = None
        self._receiver_thread = threading.Thread(
            target=self._receive_loop,
            name="zdt-can-receiver",
            daemon=True,
        )
        self._receiver_thread.start()
        return self

    def close(self):
        """
        @description         : 停止分发线程并关闭共享Backend
        @param               : 无参数
        @return              : 无返回值
        """
        self._stop_event.set()
        receiver = self._receiver_thread
        if receiver is not None and receiver is not threading.current_thread():
            receiver.join(timeout=1.0)
        self._receiver_thread = None
        self.backend.close()
        self._fail_all(ZDTBackendError("ZDT bus closed"))

    def encode_frames(self, address, command):
        """
        @description         : 把ZDT逻辑命令编码成经典CAN扩展帧但不发送
        @param address       : 电机地址
        @param command       : LogicalCommand
        @return              : CanFrame元组
        """
        return self.protocol.encode_command(address, command)

    def start_synchronized(self):
        """
        @description         : 广播触发所有已缓存的同步电机命令且不等待单电机应答
        @param               : 无参数
        @return              : 无返回值
        """
        self._send_command(0, common.build_sync_start())

    def request(
        self,
        address,
        command,
        *,
        timeout_s=None,
        response_address=None,
    ):
        """
        @description         : 发送逻辑命令并等待匹配地址和功能码的完整应答
        @param address       : 发送目标地址，可为广播地址0
        @param command       : LogicalCommand
        @param timeout_s     : 可选本次超时秒数
        @param response_address: None使用发送地址；整数或地址集合限制允许应答的地址
        @return              : ZDTResponse
        """
        if not isinstance(command, LogicalCommand):
            raise TypeError("command must be a LogicalCommand")
        send_address = validate_motor_id(address, allow_broadcast=True)
        if response_address is None:
            reply_addresses = (validate_motor_id(send_address),)
        elif isinstance(response_address, (tuple, list, set, frozenset)):
            reply_addresses = tuple(
                validate_motor_id(item) for item in response_address
            )
            if not reply_addresses:
                raise ValueError("response_address collection must not be empty")
        else:
            reply_addresses = (validate_motor_id(response_address),)
        effective_timeout = validate_positive_number(
            "timeout_s",
            self.default_timeout_s if timeout_s is None else timeout_s,
        )
        self.open()
        if self._receiver_error is not None:
            raise ZDTBackendError(f"receiver stopped: {self._receiver_error}")

        keys = tuple(
            (reply_address, command.function_code)
            for reply_address in dict.fromkeys(reply_addresses)
        )
        pending = _PendingRequest(
            expected_length=command.expected_response_length,
            result_queue=queue.Queue(maxsize=1),
        )
        with self._lock:
            busy_keys = [key for key in keys if key in self._pending]
            if busy_keys:
                raise ZDTBusBusyError(
                    f"request already pending for {busy_keys}"
                )
            for key in keys:
                self._pending[key] = pending

        try:
            self._send_command(send_address, command)
            try:
                result = pending.result_queue.get(timeout=effective_timeout)
            except queue.Empty as error:
                raise ZDTTimeoutError(
                    f"motor address candidates {reply_addresses} function "
                    f"0x{command.function_code:02X} timed out after "
                    f"{effective_timeout:.3f}s"
                ) from error
            if isinstance(result, BaseException):
                raise result
            return result
        finally:
            with self._lock:
                for key in keys:
                    self._pending.pop(key, None)
                    self._assemblies.pop(key, None)

    def next_event(self, timeout_s=0.0):
        """
        @description         : 获取未匹配请求的主动返回或周期返回事件
        @param timeout_s     : 最大等待秒数，0表示立即返回
        @return              : ZDTResponse或None
        """
        normalized_timeout = validate_nonnegative_number("timeout_s", timeout_s)
        try:
            return self._events.get(timeout=normalized_timeout)
        except queue.Empty:
            return None

    def _send_command(self, address, command):
        """
        @description         : 编码并发送命令帧但不创建或等待请求响应
        @param address       : 目标地址，允许广播地址0
        @param command       : LogicalCommand
        @return              : 已发送CanFrame元组
        """
        if not isinstance(command, LogicalCommand):
            raise TypeError("command must be a LogicalCommand")
        send_address = validate_motor_id(address, allow_broadcast=True)
        self.open()
        if self._receiver_error is not None:
            raise ZDTBackendError(f"receiver stopped: {self._receiver_error}")
        frames = self.protocol.encode_command(send_address, command)
        with self._send_lock:
            for frame in frames:
                self._trace("tx", frame)
                self.backend.send(frame)
        return frames

    def _receive_loop(self):
        """
        @description         : 后台接收CAN帧并分发给请求或事件队列
        @param               : 无参数
        @return              : 无返回值
        """
        while not self._stop_event.is_set():
            try:
                frame = self.backend.receive(0.05)
            except Exception as error:
                self._receiver_error = error
                self._fail_all(ZDTBackendError(f"receiver failed: {error}"))
                return
            if frame is None:
                try:
                    self._expire_assemblies()
                except Exception as error:
                    self._last_protocol_error = error
                continue
            try:
                self._trace("rx", frame)
                self._consume_frame(frame)
            except Exception as error:
                # 单条坏帧、重复返回或观察回调异常不能终止整个CAN接收线程。
                self._last_protocol_error = error
                continue

    def _consume_frame(self, frame):
        """
        @description         : 校验帧类型并推进对应电机功能码的分包重组
        @param frame         : 收到的CanFrame
        @return              : 无返回值
        """
        if not frame.is_extended or not frame.data:
            return
        try:
            address, packet = parse_arbitration_id(frame.arbitration_id)
            validate_motor_id(address)
        except Exception:
            return
        function_code = frame.data[0]
        key = (address, function_code)
        with self._lock:
            pending = self._pending.get(key)
            expected_length = pending.expected_length if pending else None
            if packet == 0:
                assembly = _Assembly(
                    frames=[frame],
                    expected_length=expected_length,
                    next_packet=1,
                    started_at=time.monotonic(),
                )
                self._assemblies[key] = assembly
            else:
                assembly = self._assemblies.get(key)
                if assembly is None:
                    candidates = [
                        candidate_key
                        for candidate_key, candidate in self._assemblies.items()
                        if candidate_key[0] == address
                        and candidate.next_packet == packet
                    ]
                    if len(candidates) == 1:
                        self._complete_with_error(
                            candidates[0],
                            ZDTProtocolError(
                                "ZDT continuation function code mismatch"
                            ),
                        )
                    return
                if packet != assembly.next_packet:
                    self._complete_with_error(
                        key,
                        ZDTProtocolError("ZDT packet sequence mismatch"),
                    )
                    return
                assembly.frames.append(frame)
                assembly.next_packet += 1

            logical_length = len(assembly.frames[0].data) + sum(
                len(item.data) - 1 for item in assembly.frames[1:]
            )
            if (
                assembly.expected_length is not None
                and logical_length < assembly.expected_length
                and len(frame.data) < 8
            ):
                self._complete_with_error(
                    key,
                    ZDTProtocolError(
                        f"ZDT response length {logical_length} != "
                        f"{assembly.expected_length}"
                    ),
                )
                return
            complete = (
                assembly.expected_length is not None
                and logical_length >= assembly.expected_length
            ) or (
                assembly.expected_length is None and len(frame.data) < 8
            )
            if complete:
                self._finish_assembly(key, logical_length)

    def _finish_assembly(self, key, logical_length):
        """
        @description         : 重组、校验并投递一条完整ZDT响应
        @param key           : 地址和功能码元组
        @param logical_length: 当前累计逻辑长度
        @return              : 无返回值
        """
        assembly = self._assemblies.pop(key, None)
        if assembly is None:
            return
        expected_length = assembly.expected_length or logical_length
        pending = self._pending.get(key)
        try:
            logical_data = reassemble_can_frames(
                assembly.frames,
                expected_length,
            )
            response = self.protocol.validate_response(
                key[0],
                logical_data,
                expected_function=key[1],
            )
            response = replace(
                response,
                timestamp=assembly.frames[-1].timestamp,
            )
        except Exception as error:
            self._last_protocol_error = error
            if pending is not None:
                self._put_pending_result(pending, error)
            return
        if (
            response.function_code in ASYNC_COMPLETION_FUNCTIONS
            and response.data == bytes((ASYNC_COMPLETION_STATUS,))
        ):
            self._put_event(response)
            return
        if pending is None:
            self._put_event(response)
            return
        self._put_pending_result(pending, response)

    def _complete_with_error(self, key, error):
        """
        @description         : 结束一个损坏的分包并通知等待请求
        @param key           : 地址和功能码元组
        @param error         : 协议异常
        @return              : 无返回值
        """
        self._assemblies.pop(key, None)
        self._last_protocol_error = error
        pending = self._pending.get(key)
        if pending is not None:
            self._put_pending_result(pending, error)

    @staticmethod
    def _put_pending_result(pending, result):
        """
        @description         : 非阻塞投递请求结果并安全忽略重复返回造成的队列已满
        @param pending       : 当前等待请求
        @param result        : ZDTResponse或异常
        @return              : 成功投递返回True，队列已满返回False
        """
        try:
            pending.result_queue.put_nowait(result)
            return True
        except queue.Full:
            return False

    def _put_event(self, response):
        """
        @description         : 非阻塞投递异步事件，队列满时丢弃最旧事件
        @param response      : 已校验的ZDTResponse
        @return              : 成功投递返回True，队列已满返回False
        """
        try:
            self._events.put_nowait(response)
            return True
        except queue.Full:
            try:
                self._events.get_nowait()
            except queue.Empty:
                pass
            else:
                self._dropped_event_count += 1
            try:
                self._events.put_nowait(response)
                return True
            except queue.Full:
                return False

    def _expire_assemblies(self):
        """
        @description         : 清理超过默认超时的未完成主动分包
        @param               : 无参数
        @return              : 无返回值
        """
        deadline = time.monotonic() - self.default_timeout_s
        with self._lock:
            stale = [
                key
                for key, assembly in self._assemblies.items()
                if assembly.started_at < deadline and key not in self._pending
            ]
            for key in stale:
                self._assemblies.pop(key, None)

    def _fail_all(self, error):
        """
        @description         : 将Backend致命错误投递给全部等待请求
        @param error         : 要投递的异常
        @return              : 无返回值
        """
        with self._lock:
            delivered = set()
            for pending in self._pending.values():
                pending_id = id(pending)
                if pending_id in delivered:
                    continue
                delivered.add(pending_id)
                self._put_pending_result(pending, error)

    def _trace(self, direction, frame):
        """
        @description         : 调用可选的原始帧观察回调
        @param direction     : tx或rx
        @param frame         : CanFrame
        @return              : 无返回值
        """
        if self.trace_callback is not None:
            try:
                self.trace_callback(BusTrace(direction=direction, frame=frame))
            except Exception:
                pass

    def __enter__(self):
        """
        @description         : 进入上下文并打开共享Bus
        @param               : 无参数
        @return              : 当前ZDTBus
        """
        return self.open()

    def __exit__(self, exception_type, exception, traceback):
        """
        @description         : 退出上下文并关闭共享Bus
        @param exception_type: 上下文异常类型或None
        @param exception     : 上下文异常对象或None
        @param traceback     : 上下文异常堆栈或None
        @return              : False，不屏蔽异常
        """
        self.close()
        return False


# 兼容旧版导入；新代码应使用含义更明确的 ZDTCanBus。
ZDTBus = ZDTCanBus
