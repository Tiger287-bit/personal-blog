# SPDX-License-Identifier: MIT
"""Backend contract for protocol-neutral CAN frame I/O."""

from abc import ABC, abstractmethod


class CanBackend(ABC):
    """Convert CanFrame objects to and from one concrete CAN interface."""

    @abstractmethod
    def open(self):
        """
        @description         : 打开具体CAN后端需要的资源
        @param self          : 当前后端对象
        @return              : 无
        """

    @abstractmethod
    def send(self, frame):
        """
        @description         : 通过具体CAN后端发送一帧数据
        @param self          : 当前后端对象
        @param frame         : 需要发送的CanFrame
        @return              : 无
        """

    @abstractmethod
    def receive(self, timeout_s):
        """
        @description         : 从具体CAN后端等待接收一帧数据
        @param self          : 当前后端对象
        @param timeout_s     : 最长等待秒数
        @return              : 收到时返回CanFrame，超时返回None
        """

    @abstractmethod
    def close(self):
        """
        @description         : 关闭具体CAN后端占用的资源
        @param self          : 当前后端对象
        @return              : 无
        """
