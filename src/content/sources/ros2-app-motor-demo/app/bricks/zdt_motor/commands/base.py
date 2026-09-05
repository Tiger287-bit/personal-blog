"""ZDT 命令层共用的数值编码工具。"""

from ..config import (
    Direction,
    MotionMode,
    parse_direction,
    validate_int,
    validate_number,
)
from ..errors import ZDTConfigurationError


def pack_u16(value):
    """
    @description         : 按手册高字节在前编码uint16
    @param value         : 0至65535整数
    @return              : 两字节数据
    """
    normalized = validate_int("uint16", value, 0, 0xFFFF)
    return normalized.to_bytes(2, "big")


def pack_u32(value):
    """
    @description         : 按手册高字节在前编码uint32
    @param value         : 0至4294967295整数
    @return              : 四字节数据
    """
    normalized = validate_int("uint32", value, 0, 0xFFFFFFFF)
    return normalized.to_bytes(4, "big")


def direction_and_magnitude(name, value, direction, maximum):
    """
    @description         : 从有符号工程值或显式方向得到方向与绝对值
    @param name          : 工程参数名称
    @param value         : 有符号工程单位数值
    @param direction     : cw、ccw或None
    @param maximum       : 绝对值上限
    @return              : Direction和浮点绝对值
    """
    normalized = validate_number(name, value, -maximum, maximum)
    if direction is None:
        resolved = Direction.CCW if normalized < 0 else Direction.CW
    else:
        if normalized < 0:
            raise ZDTConfigurationError(
                f"{name} must be non-negative when direction is explicit"
            )
        resolved = parse_direction(direction)
    return resolved, abs(normalized)


def parse_motion_mode(value):
    """
    @description         : 把位置模式名称或数字转换为MotionMode
    @param value         : 模式名称、数字或MotionMode
    @return              : MotionMode枚举
    """
    if isinstance(value, MotionMode):
        return value
    aliases = {
        "relative_last": MotionMode.RELATIVE_TO_LAST_TARGET,
        "absolute": MotionMode.ABSOLUTE,
        "relative": MotionMode.RELATIVE_TO_CURRENT,
        "relative_current": MotionMode.RELATIVE_TO_CURRENT,
    }
    if isinstance(value, str) and value.lower() in aliases:
        return aliases[value.lower()]
    try:
        return MotionMode(value)
    except (TypeError, ValueError) as error:
        raise ZDTConfigurationError("invalid position motion mode") from error


def require_whole_number(name, value):
    """
    @description         : 要求工程数值能由协议整数精确表示
    @param name          : 参数名称
    @param value         : 待检查数值
    @return              : 整数值
    """
    normalized = float(value)
    if not normalized.is_integer():
        raise ZDTConfigurationError(
            f"{name} must be a whole number for this firmware setting"
        )
    return int(normalized)
