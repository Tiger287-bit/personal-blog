"""生成 Emm 和 X 固件可以共用的电机命令。

本模块只负责排列命令参数，不直接访问 ``can0``。普通用户应调用
``ZDTMotor`` 的同名功能，而不是手动调用这里的 ``build_*`` 函数。
"""

from ..config import HomeMode, parse_direction, validate_int, validate_motor_id
from ..errors import ZDTConfigurationError
from ..protocols.zdt import LogicalCommand
from .base import pack_u16


def build_enable(enabled=True, *, synchronized=False):
    """
    @description         : 构造F3电机使能或失能命令
    @param enabled       : True使能，False失能
    @param synchronized  : True缓存到同步触发，False立即执行
    @return              : LogicalCommand
    """
    payload = bytes((0xAB, int(bool(enabled)), int(bool(synchronized))))
    return LogicalCommand(0xF3, payload, 3, "enable motor")


def build_stop(*, synchronized=False):
    """
    @description         : 构造FE立即停止命令
    @param synchronized  : True缓存到同步触发，False立即执行
    @return              : LogicalCommand
    """
    return LogicalCommand(
        0xFE,
        bytes((0x98, int(bool(synchronized)))),
        3,
        "stop motor",
    )


def build_sync_start():
    """
    @description         : 构造FF广播触发同步运动命令
    @param               : 无参数
    @return              : LogicalCommand
    """
    return LogicalCommand(0xFF, bytes((0x66,)), 3, "start synchronized motion")


def build_home(mode=HomeMode.NEAREST, *, synchronized=False):
    """
    @description         : 构造9A触发回零命令
    @param mode          : 0至5或HomeMode
    @param synchronized  : True缓存到同步触发，False立即执行
    @return              : LogicalCommand
    """
    try:
        normalized_mode = mode if isinstance(mode, HomeMode) else HomeMode(mode)
    except (TypeError, ValueError) as error:
        raise ZDTConfigurationError("invalid home mode") from error
    return LogicalCommand(
        0x9A,
        bytes((normalized_mode, int(bool(synchronized)))),
        3,
        "start homing",
    )


def build_abort_home():
    """
    @description         : 构造9C强制中断回零命令
    @param               : 无参数
    @return              : LogicalCommand
    """
    return LogicalCommand(0x9C, bytes((0x48,)), 3, "abort homing")


def build_set_motor_id(new_motor_id, *, store=True):
    """
    @description         : 构造AE修改电机地址命令
    @param new_motor_id  : 新地址1至255
    @param store         : True永久存储，False临时修改
    @return              : LogicalCommand
    """
    normalized_id = validate_motor_id(new_motor_id)
    return LogicalCommand(
        0xAE,
        bytes((0x4B, int(bool(store)), normalized_id)),
        3,
        "set motor id",
    )


def build_set_microstep(microstep, *, store=True):
    """
    @description         : 构造84修改细分命令
    @param microstep     : 细分1至256
    @param store         : True永久存储，False临时修改
    @return              : LogicalCommand
    """
    normalized = validate_int("microstep", microstep, 1, 256)
    protocol_value = 0 if normalized == 256 else normalized
    return LogicalCommand(
        0x84,
        bytes((0x8A, int(bool(store)), protocol_value)),
        3,
        "set microstep",
    )


def build_set_current_limit(current_ma, *, store=True):
    """
    @description         : 构造45修改闭环最大电流命令
    @param current_ma    : 最大相电流0至5000mA
    @param store         : True永久存储，False临时修改
    @return              : LogicalCommand
    """
    normalized = validate_int("current_ma", current_ma, 0, 5000)
    payload = bytes((0x66, int(bool(store)))) + pack_u16(normalized)
    return LogicalCommand(0x45, payload, 3, "set closed-loop current limit")


def build_set_direction(direction, *, store=True):
    """
    @description         : 构造D4修改电机正方向命令
    @param direction     : cw或ccw
    @param store         : True永久存储，False临时修改
    @return              : LogicalCommand
    """
    normalized = parse_direction(direction)
    payload = bytes((0x60, int(bool(store)), normalized))
    return LogicalCommand(0xD4, payload, 3, "set positive direction")


def build_read_version():
    """
    @description         : 构造1F读取固件和硬件版本命令
    @param               : 无参数
    @return              : LogicalCommand
    """
    return LogicalCommand(0x1F, b"", 6, "read firmware and hardware version")


def build_read_phase_parameters():
    """
    @description         : 构造20读取相电阻和相电感命令
    @param               : 无参数
    @return              : LogicalCommand
    """
    return LogicalCommand(0x20, b"", 6, "read phase resistance and inductance")


def build_read_bus_voltage():
    """
    @description         : 构造24读取总线电压命令
    @param               : 无参数
    @return              : LogicalCommand
    """
    return LogicalCommand(0x24, b"", 4, "read bus voltage")


def build_read_phase_current():
    """
    @description         : 构造27读取相电流命令
    @param               : 无参数
    @return              : LogicalCommand
    """
    return LogicalCommand(0x27, b"", 4, "read phase current")


def build_read_encoder():
    """
    @description         : 构造31读取单圈线性编码器值命令
    @param               : 无参数
    @return              : LogicalCommand
    """
    return LogicalCommand(0x31, b"", 4, "read encoder")


def build_read_input_pulses():
    """
    @description         : 构造32读取输入脉冲数命令
    @param               : 无参数
    @return              : LogicalCommand
    """
    return LogicalCommand(0x32, b"", 7, "read input pulses")


def build_read_target_position():
    """
    @description         : 构造33读取电机目标位置命令
    @param               : 无参数
    @return              : LogicalCommand
    """
    return LogicalCommand(0x33, b"", 7, "read target position")


def build_read_speed():
    """
    @description         : 构造35读取实时速度命令
    @param               : 无参数
    @return              : LogicalCommand
    """
    return LogicalCommand(0x35, b"", 5, "read speed")


def build_read_position():
    """
    @description         : 构造36读取实时位置命令
    @param               : 无参数
    @return              : LogicalCommand
    """
    return LogicalCommand(0x36, b"", 7, "read position")


def build_read_position_error():
    """
    @description         : 构造37读取位置误差命令
    @param               : 无参数
    @return              : LogicalCommand
    """
    return LogicalCommand(0x37, b"", 7, "read position error")


def build_read_motor_status():
    """
    @description         : 构造3A读取电机状态标志命令
    @param               : 无参数
    @return              : LogicalCommand
    """
    return LogicalCommand(0x3A, b"", 3, "read motor status")


def build_read_home_status():
    """
    @description         : 构造3B读取回零状态标志命令
    @param               : 无参数
    @return              : LogicalCommand
    """
    return LogicalCommand(0x3B, b"", 3, "read home status")


def build_raw(function_code, payload=b"", *, expected_response_length=3):
    """
    @description         : 为高级调试构造不含地址和校验码的逻辑命令
    @param function_code : 功能码0至255
    @param payload       : 原始命令数据，不含功能码和校验码
    @param expected_response_length: CAN逻辑应答总长度
    @return              : LogicalCommand
    """
    return LogicalCommand(
        validate_int("function_code", function_code, 0, 255),
        bytes(payload),
        expected_response_length,
        "raw command",
    )
