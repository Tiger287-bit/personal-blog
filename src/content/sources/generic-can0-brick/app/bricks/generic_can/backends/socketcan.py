# SPDX-License-Identifier: MIT
"""Linux SocketCAN backend; this is the only module that imports python-can."""

import importlib
import threading
import time

from ..config import validate_device, validate_timeout
from ..errors import CANBackendError
from ..frame import CanFrame
from .base import CanBackend


class SocketCANBackend(CanBackend):
    """Use an already-created and already-configured Linux SocketCAN device."""

    def __init__(self, device="can0", can_module=None):
        """
        @description         : 创建一个Linux SocketCAN后端但暂不打开接口
        @param self          : 当前后端对象
        @param device        : 已由系统创建并配置好的SocketCAN接口名称
        @param can_module    : 单元测试可注入的python-can兼容模块
        @return              : 无
        """
        self.device = validate_device(device)
        self._can_module_override = can_module
        self._can_module = None
        self._bus = None
        self._lifecycle_lock = threading.RLock()
        self.ignored_error_frames = 0
        self.ignored_remote_frames = 0

    @property
    def is_open(self):
        """
        @description         : 判断python-can Bus对象是否已经建立
        @param self          : 当前后端对象
        @return              : 已打开时返回True，否则返回False
        """
        return self._bus is not None

    def _module(self):
        """
        @description         : 延迟加载python-can，使FakeBackend测试不依赖该软件包
        @param self          : 当前后端对象
        @return              : python-can模块或测试注入的兼容模块
        """
        if self._can_module is not None:
            return self._can_module
        if self._can_module_override is not None:
            self._can_module = self._can_module_override
            return self._can_module
        try:
            self._can_module = importlib.import_module("can")
        except Exception as error:
            raise CANBackendError(
                "python-can is unavailable; start the App so its "
                "offline dependencies are installed"
            ) from error
        return self._can_module

    def open(self):
        """
        @description         : 打开已有SocketCAN接口且不修改链路状态或位速率
        @param self          : 当前后端对象
        @return              : 无；重复调用不会重复建立Bus
        """
        with self._lifecycle_lock:
            if self._bus is not None:
                return
            can_module = self._module()
            try:
                # fd=True enables CAN FD frame handling on this socket. It
                # does not execute ip link or reconfigure the Linux device.
                self._bus = can_module.Bus(
                    interface="socketcan",
                    channel=self.device,
                    fd=True,
                )
            except Exception as error:
                self._bus = None
                raise CANBackendError(
                    f"could not open SocketCAN device '{self.device}': {error}"
                ) from error

    def _require_bus(self):
        """
        @description         : 取得已打开的python-can Bus对象
        @param self          : 当前后端对象
        @return              : 当前python-can Bus对象
        """
        if self._bus is None:
            raise CANBackendError("SocketCAN backend is not open")
        return self._bus

    def send(self, frame):
        """
        @description         : 把CanFrame转换成python-can Message并发送
        @param self          : 当前后端对象
        @param frame         : 需要发送的CanFrame
        @return              : 无
        """
        if not isinstance(frame, CanFrame):
            raise CANBackendError("backend send requires a CanFrame")
        bus = self._require_bus()
        can_module = self._module()
        try:
            message = can_module.Message(
                arbitration_id=frame.arbitration_id,
                data=frame.data,
                is_extended_id=frame.is_extended,
                is_fd=frame.is_fd,
                bitrate_switch=frame.bitrate_switch,
                check=True,
            )
            bus.send(message)
        except Exception as error:
            raise CANBackendError(
                f"failed to send CAN frame on '{self.device}': {error}"
            ) from error

    def receive(self, timeout_s):
        """
        @description         : 接收下一帧数据并忽略错误帧和远程帧
        @param self          : 当前后端对象
        @param timeout_s     : 最长等待秒数
        @return              : 数据帧转换成的CanFrame，超时返回None
        """
        timeout = validate_timeout(timeout_s)
        bus = self._require_bus()
        deadline = time.monotonic() + timeout

        while True:
            if timeout == 0.0:
                remaining = 0.0
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return None
            try:
                message = bus.recv(timeout=remaining)
            except Exception as error:
                raise CANBackendError(
                    f"failed to receive from '{self.device}': {error}"
                ) from error

            if message is None:
                return None
            if bool(getattr(message, "is_error_frame", False)):
                self.ignored_error_frames += 1
                continue
            if bool(getattr(message, "is_remote_frame", False)):
                self.ignored_remote_frames += 1
                continue

            try:
                return CanFrame(
                    arbitration_id=message.arbitration_id,
                    data=bytes(message.data),
                    is_extended=bool(message.is_extended_id),
                    is_fd=bool(getattr(message, "is_fd", False)),
                    bitrate_switch=bool(
                        getattr(message, "bitrate_switch", False)
                    ),
                    timestamp=float(getattr(message, "timestamp", 0.0) or 0.0),
                )
            except Exception as error:
                raise CANBackendError(
                    f"received an invalid CAN frame on '{self.device}': "
                    f"{error}"
                ) from error

    def close(self):
        """
        @description         : 释放python-can资源且不改变Linux接口配置
        @param self          : 当前后端对象
        @return              : 无；重复调用安全
        """
        with self._lifecycle_lock:
            bus = self._bus
            self._bus = None
            if bus is None:
                return
            try:
                bus.shutdown()
            except Exception as error:
                raise CANBackendError(
                    f"failed to close SocketCAN device '{self.device}': "
                    f"{error}"
                ) from error
