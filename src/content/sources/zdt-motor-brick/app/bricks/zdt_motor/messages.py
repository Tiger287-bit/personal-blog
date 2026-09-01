"""独立于具体通信方式的 ZDT 逻辑命令和应答对象。"""

from dataclasses import dataclass

from .config import validate_int


@dataclass(frozen=True)
class LogicalCommand:
    """描述一个尚未编码到具体通信报文的 ZDT 命令。"""

    function_code: int
    payload: bytes = b""
    expected_response_length: int = 3
    description: str = ""

    def __post_init__(self):
        """
        @description         : 校验并规范化ZDT逻辑命令
        @param               : 无参数
        @return              : 无返回值
        """
        validate_int("function_code", self.function_code, 0, 255)
        object.__setattr__(self, "payload", bytes(self.payload))
        validate_int(
            "expected_response_length",
            self.expected_response_length,
            3,
            255,
        )


@dataclass(frozen=True)
class ZDTResponse:
    """
    已通过具体通信协议校验的 ZDT 逻辑应答。

    raw 表示重组后的 ZDT 逻辑应答体，当前 CAN 实现中的内容为
    Function + Data + Checksum。它不包含 CAN arbitration ID、CAN 分包号、
    SocketCAN 元数据或其他通信方式的外层 framing。
    """

    address: int
    function_code: int
    data: bytes
    raw: bytes
    timestamp: float
