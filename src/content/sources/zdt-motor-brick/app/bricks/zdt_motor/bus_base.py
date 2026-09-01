"""ZDT 电机通信总线的公共接口。"""

from abc import ABC, abstractmethod
from enum import Enum


class BusKind(str, Enum):
    """通信总线种类。枚举值不代表对应实现已经完成。"""

    CAN = "can"
    SERIAL = "serial"


class ZDTMotorBus(ABC):
    """所有 ZDT 电机总线都应实现的最小公共接口。"""

    @property
    @abstractmethod
    def kind(self):
        """
        @description         : 返回当前总线的通信种类
        @param               : 无参数
        @return              : BusKind枚举值
        """

    @property
    @abstractmethod
    def endpoint(self):
        """
        @description         : 返回当前总线使用的接口端点对象
        @param               : 无参数
        @return              : 端点对象
        """

    @abstractmethod
    def open(self):
        """
        @description         : 打开通信总线
        @param               : 无参数
        @return              : 当前总线对象
        """

    @abstractmethod
    def close(self):
        """
        @description         : 关闭通信总线
        @param               : 无参数
        @return              : 无返回值
        """

    @abstractmethod
    def request(self, address, command, **kwargs):
        """
        @description         : 发送电机命令并等待应答
        @param address       : 电机地址
        @param command       : 电机逻辑命令
        @param kwargs        : 各总线实现支持的可选参数
        @return              : 解析后的电机应答
        """

    @abstractmethod
    def describe(self):
        """
        @description         : 返回适合显示和诊断的总线信息
        @param               : 无参数
        @return              : 只包含基础数据类型的字典
        """

