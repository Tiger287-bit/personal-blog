# SPDX-License-Identifier: MIT
"""Small validation helpers shared by the Generic CAN Brick."""

import math

from .errors import CANConfigurationError


def validate_device(device):
    """
    @description         : 校验并规范化 Linux SocketCAN 接口名称
    @param device        : 接口名称，例如 can0、can1 或 vcan0
    @return              : 去除首尾空白后的合法接口名称
    """
    if not isinstance(device, str):
        raise CANConfigurationError("device must be a string")
    normalized = device.strip()
    if not normalized:
        raise CANConfigurationError("device must not be empty")
    if len(normalized.encode("utf-8")) > 15:
        raise CANConfigurationError("device must be at most 15 UTF-8 bytes")
    if any(character.isspace() for character in normalized):
        raise CANConfigurationError("device must not contain whitespace")
    if "/" in normalized or "\x00" in normalized:
        raise CANConfigurationError("device contains an invalid character")
    return normalized


def validate_timeout(timeout_s):
    """
    @description         : 校验超时时间并转换为秒数浮点值
    @param timeout_s     : 有限且不小于零的秒数
    @return              : float 类型的超时时间
    """
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, (int, float))
    ):
        raise CANConfigurationError("timeout_s must be a number")
    normalized = float(timeout_s)
    if not math.isfinite(normalized) or normalized < 0.0:
        raise CANConfigurationError(
            "timeout_s must be finite and non-negative"
        )
    return normalized


def validate_queue_size(value, name):
    """
    @description         : 校验接收队列容量
    @param value         : 必须大于零的整数容量
    @param name          : 出错时显示的参数名称
    @return              : 校验后的队列容量
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CANConfigurationError(f"{name} must be a positive integer")
    return value


def validate_bool(value, name):
    """
    @description         : 严格校验布尔参数，不把整数0或1当作布尔值
    @param value         : 待校验的值
    @param name          : 出错时显示的参数名称
    @return              : 校验后的布尔值
    """
    if type(value) is not bool:
        raise CANConfigurationError(f"{name} must be bool")
    return value
