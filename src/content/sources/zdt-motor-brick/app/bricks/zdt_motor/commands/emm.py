"""ZDT Emm 固件专属速度和位置命令。"""

from ..config import MotionMode, validate_bool, validate_int, validate_number
from ..errors import ZDTConfigurationError
from ..messages import LogicalCommand
from .base import (
    direction_and_magnitude,
    pack_u16,
    pack_u32,
    parse_motion_mode,
    require_whole_number,
)


def build_speed(rpm, *, direction=None, acceleration=10, synchronized=False):
    """
    @description         : 构造Emm固件F6速度模式命令
    @param rpm           : 目标速度，默认设置下为整数RPM，允许用符号表示方向
    @param direction     : cw、ccw或None
    @param acceleration  : Emm加速度档位0至255
    @param synchronized  : True缓存到同步触发，False立即执行
    @return              : LogicalCommand
    """
    resolved_direction, magnitude = direction_and_magnitude(
        "rpm", rpm, direction, 3000
    )
    synchronized_value = validate_bool("synchronized", synchronized)
    speed = require_whole_number("rpm", magnitude)
    acceleration_level = validate_int("acceleration", acceleration, 0, 255)
    payload = (
        bytes((resolved_direction,))
        + pack_u16(speed)
        + bytes((acceleration_level, int(synchronized_value)))
    )
    return LogicalCommand(0xF6, payload, 3, "Emm speed mode")


def degrees_to_pulses(degrees, *, microstep=16, step_angle_degrees=1.8):
    """
    @description         : 按电机步距角和细分把角度转换为Emm脉冲数
    @param degrees       : 非负角度值
    @param microstep     : 细分1至256
    @param step_angle_degrees: 电机步距角0.9或1.8度
    @return              : 四舍五入后的协议脉冲数
    """
    normalized_degrees = validate_number("degrees", degrees, 0, 1e12)
    normalized_microstep = validate_int("microstep", microstep, 1, 256)
    if step_angle_degrees not in (0.9, 1.8):
        raise ZDTConfigurationError("step_angle_degrees must be 0.9 or 1.8")
    pulses = round(
        normalized_degrees * normalized_microstep / step_angle_degrees
    )
    if pulses > 0xFFFFFFFF:
        raise ZDTConfigurationError("degrees exceed Emm uint32 pulse range")
    return pulses


def build_position(
    degrees,
    *,
    rpm,
    direction=None,
    acceleration=10,
    mode=MotionMode.RELATIVE_TO_CURRENT,
    synchronized=False,
    microstep=16,
    step_angle_degrees=1.8,
):
    """
    @description         : 构造Emm固件FD位置模式命令
    @param degrees       : 工程角度，允许用符号表示方向
    @param rpm           : 最大速度，默认设置下为整数RPM
    @param direction     : cw、ccw或None
    @param acceleration  : Emm加速度档位0至255
    @param mode          : 相对当前、相对上一目标或绝对位置
    @param synchronized  : True缓存到同步触发，False立即执行
    @param microstep     : 当前电机细分
    @param step_angle_degrees: 当前电机步距角
    @return              : LogicalCommand
    """
    resolved_direction, magnitude = direction_and_magnitude(
        "degrees", degrees, direction, 1e12
    )
    synchronized_value = validate_bool("synchronized", synchronized)
    normalized_rpm = require_whole_number(
        "rpm", validate_number("rpm", rpm, 0, 3000)
    )
    acceleration_level = validate_int("acceleration", acceleration, 0, 255)
    motion_mode = parse_motion_mode(mode)
    pulses = degrees_to_pulses(
        magnitude,
        microstep=microstep,
        step_angle_degrees=step_angle_degrees,
    )
    payload = (
        bytes((resolved_direction,))
        + pack_u16(normalized_rpm)
        + bytes((acceleration_level,))
        + pack_u32(pulses)
        + bytes((motion_mode, int(synchronized_value)))
    )
    return LogicalCommand(0xFD, payload, 3, "Emm position mode")
