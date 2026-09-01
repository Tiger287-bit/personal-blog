"""ZDT Motor Brick 的公共配置和枚举。"""

from dataclasses import dataclass
from enum import Enum, IntEnum
import math

from .errors import ZDTConfigurationError


class Firmware(str, Enum):
    """ZDT 第二代闭环固件类型。"""

    EMM = "emm"
    X = "x"


class ChecksumType(str, Enum):
    """ZDT 自由协议校验方式。"""

    FIXED_6B = "fixed_6b"
    XOR = "xor"
    CRC8 = "crc8"


class Direction(IntEnum):
    """手册中的电机运动方向。"""

    CW = 0
    CCW = 1


class MotionMode(IntEnum):
    """位置运动参考方式。"""

    RELATIVE_TO_LAST_TARGET = 0
    ABSOLUTE = 1
    RELATIVE_TO_CURRENT = 2


class HomeMode(IntEnum):
    """手册定义的回零模式。"""

    NEAREST = 0
    DIRECTIONAL = 1
    COLLISION = 2
    LIMIT_SWITCH = 3
    ABSOLUTE_ZERO = 4
    POWER_LOSS_POSITION = 5


@dataclass(frozen=True)
class MotorConfig:
    """单个 ZDTMotor 对象的协议与机械配置。"""

    model: str = "X57S"
    firmware: Firmware = Firmware.EMM
    motor_id: int = 1
    checksum: ChecksumType = ChecksumType.FIXED_6B
    microstep: int = 16
    step_angle_degrees: float = 1.8
    timeout_s: float = 0.5

    def __post_init__(self):
        """
        @description         : 规范化并校验单电机配置
        @param               : 无参数
        @return              : 无返回值
        """
        object.__setattr__(self, "model", str(self.model).upper())
        object.__setattr__(self, "firmware", parse_firmware(self.firmware))
        object.__setattr__(self, "checksum", parse_checksum_type(self.checksum))
        validate_motor_id(self.motor_id)
        validate_int("microstep", self.microstep, 1, 256)
        if self.step_angle_degrees not in (0.9, 1.8):
            raise ZDTConfigurationError("step_angle_degrees must be 0.9 or 1.8")
        object.__setattr__(
            self,
            "timeout_s",
            validate_positive_number("timeout_s", self.timeout_s),
        )


def parse_firmware(value):
    """
    @description         : 把字符串或枚举转换为 Firmware
    @param value         : emm、x 或 Firmware 枚举
    @return              : Firmware 枚举
    """
    try:
        return value if isinstance(value, Firmware) else Firmware(str(value).lower())
    except ValueError as error:
        raise ZDTConfigurationError("firmware must be 'emm' or 'x'") from error


def parse_checksum_type(value):
    """
    @description         : 把字符串或枚举转换为 ChecksumType
    @param value         : fixed_6b、xor、crc8 或对应枚举
    @return              : ChecksumType 枚举
    """
    try:
        if isinstance(value, ChecksumType):
            return value
        normalized = str(value).lower().replace("-", "_")
        if normalized in ("6b", "fixed", "fixed6b"):
            normalized = "fixed_6b"
        return ChecksumType(normalized)
    except ValueError as error:
        raise ZDTConfigurationError(
            "checksum must be fixed_6b, xor, or crc8"
        ) from error


def parse_direction(value):
    """
    @description         : 把方向字符串、数字或枚举转换为 Direction
    @param value         : cw、ccw、0、1 或 Direction
    @return              : Direction 枚举
    """
    if isinstance(value, Direction):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "cw":
            return Direction.CW
        if normalized == "ccw":
            return Direction.CCW
    try:
        return Direction(value)
    except (TypeError, ValueError) as error:
        raise ZDTConfigurationError("direction must be 'cw' or 'ccw'") from error


def validate_motor_id(motor_id, *, allow_broadcast=False):
    """
    @description         : 校验 ZDT 电机地址
    @param motor_id      : 待校验地址
    @param allow_broadcast: 是否允许广播地址0
    @return              : 合法整数地址
    """
    if isinstance(motor_id, bool) or not isinstance(motor_id, int):
        raise ZDTConfigurationError("motor_id must be an integer")
    minimum = 0 if allow_broadcast else 1
    if motor_id < minimum or motor_id > 255:
        raise ZDTConfigurationError(
            f"motor_id must be in range {minimum}-255"
        )
    return motor_id


def validate_int(name, value, minimum, maximum):
    """
    @description         : 校验不接受布尔值的整数范围
    @param name          : 参数名称
    @param value         : 参数值
    @param minimum       : 最小允许值
    @param maximum       : 最大允许值
    @return              : 合法整数
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ZDTConfigurationError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ZDTConfigurationError(
            f"{name} must be in range {minimum}-{maximum}"
        )
    return value


def validate_number(name, value, minimum, maximum):
    """
    @description         : 校验工程单位数值范围
    @param name          : 参数名称
    @param value         : 参数值
    @param minimum       : 最小允许值
    @param maximum       : 最大允许值
    @return              : 合法浮点数
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ZDTConfigurationError(f"{name} must be a number")
    normalized = float(value)
    if (
        not math.isfinite(normalized)
        or normalized < minimum
        or normalized > maximum
    ):
        raise ZDTConfigurationError(
            f"{name} must be a finite number in range {minimum}-{maximum}"
        )
    return normalized


def validate_positive_number(name, value):
    """
    @description         : 校验有限且大于零的数值并转换为浮点数
    @param name          : 参数名称
    @param value         : 待校验数值
    @return              : 合法浮点数
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ZDTConfigurationError(
            f"{name} must be a finite positive number"
        )
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ZDTConfigurationError(
            f"{name} must be a finite positive number"
        )
    return normalized


def validate_nonnegative_number(name, value):
    """
    @description         : 校验有限且不小于零的数值并转换为浮点数
    @param name          : 参数名称
    @param value         : 待校验数值
    @return              : 合法浮点数
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ZDTConfigurationError(
            f"{name} must be a finite non-negative number"
        )
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ZDTConfigurationError(
            f"{name} must be a finite non-negative number"
        )
    return normalized
