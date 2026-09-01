"""把 ZDT 逻辑命令转换成真实 CAN 报文，并检查电机应答。

普通用户不需要直接调用本模块。``ZDTMotor`` 和 ``ZDTBus`` 会自动完成
CAN ID 生成、长报文分包、应答重组以及校验码检查。
"""

from dataclasses import dataclass

from ..backends.base import CanFrame
from ..config import ChecksumType, parse_checksum_type, validate_motor_id, validate_int
from ..errors import ZDTProtocolError
from .checksum import calculate_checksum


@dataclass(frozen=True)
class LogicalCommand:
    """尚未转换成 CAN 帧的电机命令，仅供 Brick 内部传递。"""

    function_code: int
    payload: bytes = b""
    expected_response_length: int = 3
    description: str = ""

    def __post_init__(self):
        """
        @description         : 校验并规范化逻辑命令
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
    """地址、长度和校验码都检查通过后的电机应答。"""

    address: int
    function_code: int
    data: bytes
    raw: bytes
    timestamp: float


def arbitration_id(address, packet=0):
    """
    @description         : 根据电机地址和分包号生成ZDT扩展CAN ID
    @param address       : 电机地址，允许广播地址0
    @param packet        : 分包编号0至255
    @return              : CAN扩展标识符
    """
    normalized_address = validate_motor_id(address, allow_broadcast=True)
    normalized_packet = validate_int("packet", packet, 0, 255)
    return (normalized_address << 8) | normalized_packet


def parse_arbitration_id(can_id):
    """
    @description         : 从收到的CAN ID中取出电机地址和分包号
    @param can_id        : 29位CAN标识符
    @return              : address与packet二元组
    """
    validate_int("can_id", can_id, 0, 0x1FFFFFFF)
    address = (can_id >> 8) & 0xFF
    packet = can_id & 0xFF
    if can_id >> 16:
        raise ZDTProtocolError(f"invalid ZDT CAN ID 0x{can_id:X}")
    return address, packet


def split_can_frames(address, logical_data):
    """
    @description         : 把超过8字节的逻辑数据拆成多条经典CAN报文
    @param address       : 电机地址
    @param logical_data  : 功能码、数据和校验码，不含地址
    @return              : CanFrame元组
    """
    payload = bytes(logical_data)
    if len(payload) < 2:
        raise ZDTProtocolError("logical ZDT data is too short")
    function_code = payload[0]
    frames = []
    first = payload[:8]
    frames.append(CanFrame(arbitration_id(address, 0), first, True))
    offset = len(first)
    packet = 1
    while offset < len(payload):
        continuation = bytes((function_code,)) + payload[offset : offset + 7]
        frames.append(CanFrame(arbitration_id(address, packet), continuation, True))
        offset += 7
        packet += 1
        if packet > 255:
            raise ZDTProtocolError("ZDT command needs more than 256 CAN packets")
    return tuple(frames)


def reassemble_can_frames(frames, expected_length):
    """
    @description         : 重组首包和重复功能码的后续包
    @param frames        : 按接收顺序排列的CanFrame
    @param expected_length: 期望逻辑数据总长度
    @return              : 重组后的逻辑数据
    """
    packet_list = tuple(frames)
    if not packet_list:
        raise ZDTProtocolError("no CAN frames to reassemble")
    validate_int("expected_length", expected_length, 2, 255)
    first_address, first_packet = parse_arbitration_id(
        packet_list[0].arbitration_id
    )
    if first_packet != 0 or not packet_list[0].is_extended:
        raise ZDTProtocolError("first ZDT CAN packet must be extended packet 0")
    if not packet_list[0].data:
        raise ZDTProtocolError("empty ZDT CAN packet")
    function_code = packet_list[0].data[0]
    assembled = bytearray(packet_list[0].data)
    for expected_packet, frame in enumerate(packet_list[1:], start=1):
        address, packet = parse_arbitration_id(frame.arbitration_id)
        if not frame.is_extended or address != first_address:
            raise ZDTProtocolError("ZDT continuation address or frame type mismatch")
        if packet != expected_packet:
            raise ZDTProtocolError("ZDT continuation packet sequence mismatch")
        if not frame.data or frame.data[0] != function_code:
            raise ZDTProtocolError("ZDT continuation function code mismatch")
        assembled.extend(frame.data[1:])
    if len(assembled) != expected_length:
        raise ZDTProtocolError(
            f"ZDT response length {len(assembled)} != {expected_length}"
        )
    return bytes(assembled)


class ZDTProtocol:
    """负责 ZDT 逻辑数据与经典 CAN 帧之间的转换。"""

    def __init__(self, checksum=ChecksumType.FIXED_6B):
        """
        @description         : 保存协议校验方式
        @param checksum      : fixed_6b、xor或crc8
        @return              : 无返回值
        """
        self.checksum = parse_checksum_type(checksum)

    def encode_command(self, address, command):
        """
        @description         : 为逻辑命令添加校验并编码为经典CAN扩展帧
        @param address       : 电机地址
        @param command       : LogicalCommand实例
        @return              : CanFrame元组
        """
        if not isinstance(command, LogicalCommand):
            raise TypeError("command must be a LogicalCommand")
        body = bytes((command.function_code,)) + command.payload
        checksum = calculate_checksum(self.checksum, address, body)
        return split_can_frames(address, body + bytes((checksum,)))

    def validate_response(self, address, logical_data, expected_function=None):
        """
        @description         : 校验应答地址、功能码和校验码并创建结构化响应
        @param address       : 从CAN ID解析出的电机地址
        @param logical_data  : 功能码、返回数据和校验码
        @param expected_function: 可选的期望功能码
        @return              : ZDTResponse
        """
        normalized_address = validate_motor_id(address)
        payload = bytes(logical_data)
        if len(payload) < 3:
            raise ZDTProtocolError("ZDT response is too short")
        function_code = payload[0]
        if expected_function is not None and function_code != expected_function:
            raise ZDTProtocolError(
                f"function 0x{function_code:02X} != 0x{expected_function:02X}"
            )
        expected_checksum = calculate_checksum(
            self.checksum,
            normalized_address,
            payload[:-1],
        )
        if payload[-1] != expected_checksum:
            raise ZDTProtocolError(
                f"checksum 0x{payload[-1]:02X} != 0x{expected_checksum:02X}"
            )
        return ZDTResponse(
            address=normalized_address,
            function_code=function_code,
            data=payload[1:-1],
            raw=payload,
            timestamp=0.0,
        )
