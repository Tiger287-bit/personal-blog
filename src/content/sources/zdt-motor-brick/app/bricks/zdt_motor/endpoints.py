"""描述 ZDT 电机总线连接到哪个系统接口。"""

from dataclasses import dataclass, field
from enum import Enum

from .errors import ZDTConfigurationError


class EndpointOwner(str, Enum):
    """接口由 Linux 还是 MCU 直接管理。"""

    LINUX = "linux"
    MCU = "mcu"


@dataclass(frozen=True)
class SocketCanEndpoint:
    """Linux SocketCAN 接口的显式配置。"""

    interface: str = "can0"
    expected_bitrate: int = 500_000
    physical_port: str | None = None
    transport: str = field(default="socketcan", init=False)
    owner: EndpointOwner = field(default=EndpointOwner.LINUX, init=False)

    def __post_init__(self):
        """
        @description         : 校验SocketCAN接口配置
        @param               : 无参数
        @return              : 无返回值
        """
        if not isinstance(self.interface, str) or not self.interface.strip():
            raise ZDTConfigurationError("SocketCAN interface must not be empty")
        if (
            isinstance(self.expected_bitrate, bool)
            or not isinstance(self.expected_bitrate, int)
            or self.expected_bitrate <= 0
        ):
            raise ZDTConfigurationError(
                "SocketCAN expected_bitrate must be a positive integer"
            )
        if self.physical_port is not None and (
            not isinstance(self.physical_port, str)
            or not self.physical_port.strip()
        ):
            raise ZDTConfigurationError(
                "SocketCAN physical_port must be None or a non-empty string"
            )

    def describe(self):
        """
        @description         : 返回SocketCAN接口的可读配置
        @param               : 无参数
        @return              : 只包含基础数据类型的字典
        """
        return {
            "transport": self.transport,
            "owner": self.owner.value,
            "interface": self.interface,
            "expected_bitrate": self.expected_bitrate,
            "physical_port": self.physical_port,
        }

