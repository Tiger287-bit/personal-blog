"""经典 CAN 帧及 CAN Backend 的稳定抽象。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import time


@dataclass(frozen=True)
class CanFrame:
    """一帧经典 CAN 报文。"""

    arbitration_id: int
    data: bytes
    is_extended: bool = True
    timestamp: float = 0.0

    def __post_init__(self):
        """
        @description         : 规范化 CAN 数据并补充本地时间戳
        @param               : 无参数
        @return              : 无返回值
        """
        object.__setattr__(self, "data", bytes(self.data))
        if self.timestamp == 0.0:
            object.__setattr__(self, "timestamp", time.time())
        if len(self.data) > 8:
            raise ValueError("classical CAN data must not exceed 8 bytes")


class CanBackend(ABC):
    """只负责经典 CAN 帧搬运的 Backend 接口。"""

    @abstractmethod
    def open(self):
        """
        @description         : 打开 CAN Backend
        @param               : 无参数
        @return              : 当前 Backend
        """

    @abstractmethod
    def send(self, frame):
        """
        @description         : 发送一个经典 CAN 帧
        @param frame         : CanFrame实例
        @return              : 无返回值
        """

    @abstractmethod
    def receive(self, timeout_s):
        """
        @description         : 等待并接收一个经典 CAN 帧
        @param timeout_s     : 最大等待秒数
        @return              : 收到的帧或None
        """

    @abstractmethod
    def close(self):
        """
        @description         : 关闭 CAN Backend
        @param               : 无参数
        @return              : 无返回值
        """

    def __enter__(self):
        """
        @description         : 进入上下文并打开 Backend
        @param               : 无参数
        @return              : 当前 Backend
        """
        return self.open()

    def __exit__(self, exception_type, exception, traceback):
        """
        @description         : 退出上下文并关闭 Backend
        @param exception_type: 上下文异常类型或None
        @param exception     : 上下文异常对象或None
        @param traceback     : 上下文异常堆栈或None
        @return              : False，不屏蔽异常
        """
        self.close()
        return False
