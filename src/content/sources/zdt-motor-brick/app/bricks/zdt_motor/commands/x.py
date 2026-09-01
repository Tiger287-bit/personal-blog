"""ZDT X 固件专属速度和梯形位置命令。"""

from ..config import MotionMode, validate_bool, validate_int, validate_number
from ..errors import ZDTConfigurationError
from ..messages import LogicalCommand
from .base import direction_and_magnitude, pack_u16, pack_u32, parse_motion_mode


def to_tenths(name, value, maximum):
    """
    @description         : 把工程单位转换为手册规定的0.1单位整数
    @param name          : 参数名称
    @param value         : 工程单位数值
    @param maximum       : 工程单位上限
    @return              : 放大10倍的整数
    """
    normalized = validate_number(name, value, 0, maximum)
    scaled = round(normalized * 10)
    if abs(scaled / 10.0 - normalized) > 1e-9:
        raise ZDTConfigurationError(f"{name} supports one decimal place")
    return scaled


def build_speed(rpm, *, direction=None, acceleration=1000, synchronized=False):
    """
    @description         : 构造X固件F6速度模式命令
    @param rpm           : 目标速度RPM，支持一位小数和有符号方向
    @param direction     : cw、ccw或None
    @param acceleration  : 加速度0至65535RPM/S
    @param synchronized  : True缓存到同步触发，False立即执行
    @return              : LogicalCommand
    """
    resolved_direction, magnitude = direction_and_magnitude(
        "rpm", rpm, direction, 3000.0
    )
    synchronized_value = validate_bool("synchronized", synchronized)
    speed_tenths = to_tenths("rpm", magnitude, 3000.0)
    acceleration_value = validate_int("acceleration", acceleration, 0, 65535)
    payload = (
        bytes((resolved_direction,))
        + pack_u16(acceleration_value)
        + pack_u16(speed_tenths)
        + bytes((int(synchronized_value),))
    )
    return LogicalCommand(0xF6, payload, 3, "X speed mode")


def build_position(
    degrees,
    *,
    rpm,
    direction=None,
    acceleration=1000,
    deceleration=None,
    mode=MotionMode.RELATIVE_TO_CURRENT,
    synchronized=False,
):
    """
    @description         : 构造X固件FD梯形曲线位置模式命令
    @param degrees       : 目标或相对角度，支持一位小数和有符号方向
    @param rpm           : 最大速度RPM，支持一位小数
    @param direction     : cw、ccw或None
    @param acceleration  : 加速加速度0至65535RPM/S
    @param deceleration  : 减速加速度；None时等于acceleration
    @param mode          : 相对当前、相对上一目标或绝对位置
    @param synchronized  : True缓存到同步触发，False立即执行
    @return              : LogicalCommand
    """
    resolved_direction, magnitude = direction_and_magnitude(
        "degrees", degrees, direction, 429496729.5
    )
    synchronized_value = validate_bool("synchronized", synchronized)
    angle_tenths = to_tenths("degrees", magnitude, 429496729.5)
    speed_tenths = to_tenths("rpm", rpm, 3000.0)
    acceleration_value = validate_int("acceleration", acceleration, 0, 65535)
    deceleration_value = validate_int(
        "deceleration",
        acceleration if deceleration is None else deceleration,
        0,
        65535,
    )
    motion_mode = parse_motion_mode(mode)
    payload = (
        bytes((resolved_direction,))
        + pack_u16(acceleration_value)
        + pack_u16(deceleration_value)
        + pack_u16(speed_tenths)
        + pack_u32(angle_tenths)
        + bytes((motion_mode, int(synchronized_value)))
    )
    return LogicalCommand(0xFD, payload, 3, "X trapezoidal position mode")
