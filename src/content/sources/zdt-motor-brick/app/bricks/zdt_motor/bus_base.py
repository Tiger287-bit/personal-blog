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

    @property
    @abstractmethod
    def checksum(self):
        """
        @description         : 返回当前总线使用的ZDT校验方式
        @param               : 无参数
        @return              : ChecksumType枚举值
        """

    @property
    @abstractmethod
    def default_timeout_s(self):
        """
        @description         : 返回当前总线默认请求超时时间
        @param               : 无参数
        @return              : 超时秒数
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
    def request(
        self,
        address,
        command,
        *,
        timeout_s=None,
        response_address=None,
    ):
        """
        @description         : 发送逻辑命令并等待匹配的ZDT应答
        @param address       : 发送目标电机地址
        @param command       : LogicalCommand
        @param timeout_s     : 本次请求超时时间，None表示使用Bus默认值
        @param response_address: None表示应答必须来自address；整数表示只接受该地址；
                                tuple/list/set/frozenset表示允许其中任一地址，首个有效
                                匹配应答完成请求；主要用于修改电机ID后的应答地址兼容
        @return              : ZDTResponse
        """

    @abstractmethod
    def describe(self):
        """
        @description         : 返回适合显示和诊断的总线信息
        @param               : 无参数
        @return              : 只包含基础数据类型的字典
        """
