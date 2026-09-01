"""使用 python-can 连接 Linux 的 ``can0`` 接口。

这个文件是 Brick 中唯一直接依赖 ``python-can`` 的模块。它只负责收发
经典 CAN 扩展帧，不负责设置波特率，也不会自动启用系统接口。
"""

import socket

from .base import CanFrame, MotorBackend
from ..errors import ZDTBackendError, ZDTConfigurationError


class SocketCANBackend(MotorBackend):
    """打开一个已经由用户配置好的 Linux SocketCAN 接口。"""

    def __init__(self, device="can0", *, receive_own_messages=False):
        """
        @description         : 保存Linux CAN接口名称，但不修改它的状态或波特率
        @param device        : Linux CAN接口名称，通常是can0
        @param receive_own_messages: 是否接收本进程发出的回环帧
        @return              : 无返回值
        """
        if not device or not isinstance(device, str):
            raise ZDTConfigurationError("device must be a non-empty string")
        self.device = device
        self.receive_own_messages = bool(receive_own_messages)
        self._bus = None

    def open(self):
        """
        @description         : 使用python-can打开已经存在的Linux CAN接口
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
        if timeout_s < 0:
            raise ZDTConfigurationError("timeout_s must not be negative")
        try:
            message = self._require_bus().recv(timeout=float(timeout_s))
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
