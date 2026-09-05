# SPDX-License-Identifier: MIT
"""Protocol-neutral representation of one CAN data frame."""

from dataclasses import dataclass
import math

from .config import validate_bool
from .errors import CANConfigurationError


CAN_FD_DATA_LENGTHS = frozenset({
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    12,
    16,
    20,
    24,
    32,
    48,
    64,
})


@dataclass(frozen=True)
class CanFrame:
    """One validated Standard/Extended Classical CAN or CAN FD data frame."""

    arbitration_id: int
    data: bytes = b""
    is_extended: bool = False
    is_fd: bool = False
    bitrate_switch: bool = False
    timestamp: float = 0.0

    def __post_init__(self):
        """
        @description         : 校验并规范化一帧 CAN 数据的全部字段
        @param self          : 当前不可变 CanFrame 对象
        @return              : 无；非法字段会抛出 CANConfigurationError
        """
        if (
            isinstance(self.arbitration_id, bool)
            or not isinstance(self.arbitration_id, int)
        ):
            raise CANConfigurationError("arbitration_id must be an integer")

        validate_bool(self.is_extended, "is_extended")
        validate_bool(self.is_fd, "is_fd")
        validate_bool(self.bitrate_switch, "bitrate_switch")

        maximum_id = 0x1FFFFFFF if self.is_extended else 0x7FF
        if not 0 <= self.arbitration_id <= maximum_id:
            frame_kind = "extended" if self.is_extended else "standard"
            raise CANConfigurationError(
                f"{frame_kind} arbitration_id must be in "
                f"0x0..0x{maximum_id:X}"
            )

        if isinstance(self.data, (str, int)):
            raise CANConfigurationError(
                "data must be bytes-compatible, not text or an integer"
            )
        try:
            normalized_data = bytes(self.data)
        except (TypeError, ValueError, OverflowError) as error:
            raise CANConfigurationError(
                "data must be bytes-compatible"
            ) from error
        object.__setattr__(self, "data", normalized_data)

        if self.is_fd and len(normalized_data) not in CAN_FD_DATA_LENGTHS:
            raise CANConfigurationError(
                "CAN FD data length must be one of "
                "0..8, 12, 16, 20, 24, 32, 48, or 64 bytes"
            )
        if not self.is_fd and len(normalized_data) > 8:
            raise CANConfigurationError(
                "Classical CAN data must contain 0..8 bytes"
            )

        if self.bitrate_switch and not self.is_fd:
            raise CANConfigurationError(
                "bitrate_switch requires is_fd=True"
            )

        if (
            isinstance(self.timestamp, bool)
            or not isinstance(self.timestamp, (int, float))
        ):
            raise CANConfigurationError("timestamp must be a number")
        normalized_timestamp = float(self.timestamp)
        if not math.isfinite(normalized_timestamp) or normalized_timestamp < 0:
            raise CANConfigurationError(
                "timestamp must be finite and non-negative"
            )
        object.__setattr__(self, "timestamp", normalized_timestamp)
