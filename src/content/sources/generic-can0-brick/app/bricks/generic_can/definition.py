# SPDX-License-Identifier: MIT
"""Named message definitions supplied by the user's can_messages.py."""

from dataclasses import dataclass
from typing import Callable, Optional

from .config import validate_bool
from .errors import CANConfigurationError
from .frame import CanFrame


@dataclass(frozen=True)
class MessageDefinition:
    """Describe how one named CAN message is sent and/or received."""

    arbitration_id: int
    direction: str = "both"
    is_extended: bool = False
    is_fd: bool = False
    bitrate_switch: bool = False
    fixed_data: Optional[bytes] = None
    encode: Optional[Callable] = None
    decode: Optional[Callable] = None

    def __post_init__(self):
        """
        @description         : 校验命名报文方向、标志位和编解码配置
        @param self          : 当前不可变 MessageDefinition 对象
        @return              : 无；非法配置会抛出 CANConfigurationError
        """
        if not isinstance(self.direction, str):
            raise CANConfigurationError("direction must be a string")
        normalized_direction = self.direction.strip().lower()
        if normalized_direction not in {"tx", "rx", "both"}:
            raise CANConfigurationError(
                "direction must be 'tx', 'rx', or 'both'"
            )
        object.__setattr__(self, "direction", normalized_direction)

        validate_bool(self.is_extended, "is_extended")
        validate_bool(self.is_fd, "is_fd")
        validate_bool(self.bitrate_switch, "bitrate_switch")

        if self.encode is not None and not callable(self.encode):
            raise CANConfigurationError("encode must be callable or None")
        if self.decode is not None and not callable(self.decode):
            raise CANConfigurationError("decode must be callable or None")
        if self.fixed_data is not None and self.encode is not None:
            raise CANConfigurationError(
                "fixed_data and encode cannot both be configured"
            )

        normalized_fixed_data = self.fixed_data
        if self.fixed_data is not None:
            if isinstance(self.fixed_data, (str, int)):
                raise CANConfigurationError(
                    "fixed_data must be bytes-compatible, not text or "
                    "an integer"
                )
            try:
                normalized_fixed_data = bytes(self.fixed_data)
            except (TypeError, ValueError, OverflowError) as error:
                raise CANConfigurationError(
                    "fixed_data must be bytes-compatible"
                ) from error
            object.__setattr__(self, "fixed_data", normalized_fixed_data)

        if normalized_direction == "rx":
            if normalized_fixed_data is not None or self.encode is not None:
                raise CANConfigurationError(
                    "rx-only messages cannot define fixed_data or encode"
                )
        elif normalized_direction == "tx":
            if self.decode is not None:
                raise CANConfigurationError(
                    "tx-only messages cannot define decode"
                )
            if normalized_fixed_data is None and self.encode is None:
                raise CANConfigurationError(
                    "tx messages require fixed_data or encode"
                )
        elif normalized_fixed_data is None and self.encode is None:
            raise CANConfigurationError(
                "both-direction messages require fixed_data or encode"
            )

        # Reuse CanFrame's protocol-neutral ID, flag, and payload validation.
        CanFrame(
            arbitration_id=self.arbitration_id,
            data=normalized_fixed_data or b"",
            is_extended=self.is_extended,
            is_fd=self.is_fd,
            bitrate_switch=self.bitrate_switch,
        )

    @property
    def allows_tx(self):
        """
        @description         : 判断当前命名报文是否允许发送
        @param self          : 当前报文定义
        @return              : 允许发送时返回True，否则返回False
        """
        return self.direction in {"tx", "both"}

    @property
    def allows_rx(self):
        """
        @description         : 判断当前命名报文是否允许接收
        @param self          : 当前报文定义
        @return              : 允许接收时返回True，否则返回False
        """
        return self.direction in {"rx", "both"}

    def match_key(self):
        """
        @description         : 生成接收线程分发报文时使用的匹配键
        @param self          : 当前报文定义
        @return              : 由CAN ID、扩展帧标志和FD标志组成的元组
        """
        return (self.arbitration_id, self.is_extended, self.is_fd)
