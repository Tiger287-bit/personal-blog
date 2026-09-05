"""用户主要编辑的 CAN 报文定义文件。

下面的 ID 和 DATA 只用于教学，不代表任何真实设备协议。连接真实总线前，
必须按照设备手册替换它们。
"""

import math

from generic_can import MessageDefinition


def encode_motor_speed(rpm):
    """
    @description         : 把RPM工程值放大10倍并编码成2字节大端有符号整数
    @param rpm           : 需要编码的目标转速，单位RPM
    @return              : 两字节CAN DATA
    """
    if isinstance(rpm, bool) or not isinstance(rpm, (int, float)):
        raise ValueError("rpm must be a number")
    if not math.isfinite(float(rpm)):
        raise ValueError("rpm must be finite")

    scaled = int(round(float(rpm) * 10.0))
    if not -32768 <= scaled <= 32767:
        raise ValueError("rpm does not fit the signed 16-bit example field")
    return scaled.to_bytes(2, byteorder="big", signed=True)


def decode_motor_status(data):
    """
    @description         : 把状态位和2字节大端转速解析成便于业务使用的字典
    @param data          : 至少包含3字节的CAN DATA
    @return              : 包含enabled、fault和speed_rpm的字典
    """
    payload = bytes(data)
    if len(payload) < 3:
        raise ValueError("motor status requires at least 3 bytes")

    flags = payload[0]
    scaled_speed = int.from_bytes(
        payload[1:3],
        byteorder="big",
        signed=True,
    )
    return {
        "enabled": bool(flags & 0x01),
        "fault": bool(flags & 0x02),
        "speed_rpm": scaled_speed / 10.0,
    }


def encode_fd_bytes(payload):
    """
    @description         : 把用户提供的字节兼容对象转换成CAN FD示例DATA
    @param payload       : 长度不超过64的字节兼容对象
    @return              : 不可变bytes
    """
    if isinstance(payload, (str, int)):
        raise ValueError(
            "payload must be bytes-compatible, not text or an integer"
        )
    return bytes(payload)


MESSAGES = {
    # 固定DATA：调用bus.send("enable")即可发送。
    "enable": MessageDefinition(
        arbitration_id=0x201,
        direction="tx",
        fixed_data=b"\x01\x01",
    ),
    "disable": MessageDefinition(
        arbitration_id=0x201,
        direction="tx",
        fixed_data=b"\x01\x00",
    ),

    # 动态DATA：rpm通过encode_motor_speed()转换成两个字节。
    "set_speed": MessageDefinition(
        arbitration_id=0x202,
        direction="tx",
        encode=encode_motor_speed,
    ),

    # 接收后通过decode_motor_status()转换成工程值字典。
    "status": MessageDefinition(
        arbitration_id=0x301,
        direction="rx",
        decode=decode_motor_status,
    ),

    # 29位扩展帧示例。
    "extended_ping": MessageDefinition(
        arbitration_id=0x123456,
        direction="tx",
        is_extended=True,
        fixed_data=b"\xA5",
    ),

    # CAN FD+BRS示例。Brick不会自动把Linux接口配置成fd on。
    "fd_payload": MessageDefinition(
        arbitration_id=0x420,
        direction="tx",
        is_fd=True,
        bitrate_switch=True,
        encode=encode_fd_bytes,
    ),
}
