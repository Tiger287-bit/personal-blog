"""基于 python-can 的 Linux SocketCAN Backend。"""

import socket

from .base import CanBackend, CanFrame
from ..config import validate_positive_number
from ..errors import ZDTBackendError, ZDTConfigurationError


class SocketCANBackend(CanBackend):
    """只使用已经存在且已配置的 Linux SocketCAN 接口。"""

    def __init__(self, device="can0", *, receive_own_messages=False):
        """
        @description         : 保存 SocketCAN 接口名但不修改系统接口状态
        @param device        : SocketCAN接口，例如can0
        @param receive_own_messages: 是否接收本进程发出的回环帧
        @return              : 无返回值
        """
        if not isinstance(device, str):
            raise ZDTConfigurationError("device must be a non-empty string")
        normalized_device = device.strip()
        if not normalized_device:
            raise ZDTConfigurationError("device must be a non-empty string")
        self.device = normalized_device
        self.receive_own_messages = bool(receive_own_messages)
        self._bus = None

    def open(self):
        """
        @description         : 使用 python-can 打开已有 SocketCAN 接口
        @param               : 无参数
        @return              : 当前 SocketCANBackend
        """
        if self._bus is not None:
            return self
        try:
            socket.if_nametoindex(self.device)
        except OSError as error:
            raise ZDTBackendError(
                f"SocketCAN interface '{self.device}' does not exist"
            ) from error
        try:
            import can

            self._bus = can.Bus(
                interface="socketcan",
                channel=self.device,
                receive_own_messages=self.receive_own_messages,
            )
        except ImportError as error:
            raise ZDTBackendError(
                "python-can is required; install Brick requirements first"
            ) from error
        except Exception as error:
            raise ZDTBackendError(
                f"cannot open SocketCAN interface '{self.device}': {error}"
            ) from error
        return self

    def send(self, frame):
        """
        @description         : 发送经典 CAN 扩展帧，明确关闭 CAN FD/BRS
        @param frame         : CanFrame实例
        @return              : 无返回值
        """
        if not isinstance(frame, CanFrame):
            raise ZDTConfigurationError("frame must be a CanFrame")
        if not frame.is_extended:
            raise ZDTConfigurationError("ZDT CAN requires extended frames")
        try:
            import can

            message = can.Message(
                arbitration_id=frame.arbitration_id,
                data=frame.data,
                is_extended_id=True,
                is_fd=False,
                bitrate_switch=False,
            )
            self._require_bus().send(message)
        except Exception as error:
            if isinstance(error, (ZDTBackendError, ZDTConfigurationError)):
                raise
            raise ZDTBackendError(f"SocketCAN send failed: {error}") from error

    def receive(self, timeout_s):
        """
        @description         : 在指定时间内接收一帧经典 CAN 报文
        @param timeout_s     : 最大等待秒数
        @return              : CanFrame或None
        """
        normalized_timeout = validate_positive_number("timeout_s", timeout_s)
        try:
            message = self._require_bus().recv(timeout=normalized_timeout)
        except Exception as error:
            if isinstance(error, ZDTBackendError):
                raise
            raise ZDTBackendError(f"SocketCAN receive failed: {error}") from error
        if message is None:
            return None
        if message.is_error_frame or message.is_remote_frame or message.is_fd:
            return None
        return CanFrame(
            arbitration_id=message.arbitration_id,
            data=bytes(message.data),
            is_extended=bool(message.is_extended_id),
            timestamp=float(message.timestamp or 0.0),
        )

    def close(self):
        """
        @description         : 关闭 python-can Bus 并释放套接字
        @param               : 无参数
        @return              : 无返回值
        """
        if self._bus is not None:
            bus = self._bus
            self._bus = None
            bus.shutdown()

    def _require_bus(self):
        """
        @description         : 获取已打开的 python-can Bus
        @param               : 无参数
        @return              : python-can Bus实例
        """
        if self._bus is None:
            raise ZDTBackendError("SocketCAN backend is not open")
        return self._bus
