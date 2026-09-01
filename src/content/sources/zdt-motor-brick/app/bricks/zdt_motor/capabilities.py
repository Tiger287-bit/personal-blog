"""阻止当前电机型号使用手册未确认支持的功能。

这样可以在发送 CAN 报文前给出清楚的错误，避免把其他型号的命令误发给
X57S。普通用户不需要直接修改这个文件。
"""

from dataclasses import dataclass

from .config import Firmware, parse_firmware
from .errors import ZDTUnsupportedFeatureError


X57S_COMMON_FEATURES = frozenset(
    {
        "enable",
        "stop",
        "speed",
        "position",
        "read_version",
        "read_phase_parameters",
        "bus_voltage",
        "phase_current",
        "encoder",
        "input_pulses",
        "position_error",
        "motor_status",
        "home",
        "home_status",
        "set_motor_id",
        "set_microstep",
        "set_current_limit",
        "set_direction",
        "raw",
    }
)

X42S_Y42_ONLY_FEATURES = frozenset(
    {
        "reboot",
        "multi_motor_command",
        "periodic_return",
        "bus_current",
        "temperature",
        "combined_status",
        "io_levels",
        "position_window",
        "heartbeat",
        "broadcast_read_id",
    }
)


@dataclass(frozen=True)
class CapabilityProfile:
    """记录某个电机型号和固件可以安全调用哪些功能。"""

    model: str
    firmware: Firmware
    features: frozenset[str]
    explicitly_unsupported: frozenset[str]

    def supports(self, feature):
        """
        @description         : 判断当前组合是否支持指定功能
        @param feature       : 功能名称
        @return              : 支持返回True，否则返回False
        """
        return str(feature) in self.features

    def require(self, feature):
        """
        @description         : 要求当前组合支持指定功能
        @param feature       : 功能名称
        @return              : 支持时无返回值
        """
        if not self.supports(feature):
            raise ZDTUnsupportedFeatureError(
                f"{self.model}/{self.firmware.value} does not support "
                f"feature '{feature}'"
            )


def capabilities_for(model, firmware):
    """
    @description         : 创建经过手册边界约束的能力配置
    @param model         : 电机型号，V1确认支持X57S
    @param firmware      : emm或x固件
    @return              : CapabilityProfile
    """
    normalized_model = str(model).upper()
    normalized_firmware = parse_firmware(firmware)
    if normalized_model != "X57S":
        raise ZDTUnsupportedFeatureError(
            f"V1 capability data is only confirmed for X57S, got {normalized_model}"
        )
    firmware_features = (
        {"emm_speed", "emm_position"}
        if normalized_firmware is Firmware.EMM
        else {"x_speed", "x_position"}
    )
    return CapabilityProfile(
        model=normalized_model,
        firmware=normalized_firmware,
        features=frozenset(X57S_COMMON_FEATURES | firmware_features),
        explicitly_unsupported=X42S_Y42_ONLY_FEATURES,
    )
