"""Stable public API for the Generic CAN V1 Brick."""

from .bus import CanBus
from .definition import MessageDefinition
from .errors import (
    CANBackendError,
    CANConfigurationError,
    CANError,
    CANMessageError,
    CANTimeoutError,
    CANUnsupportedFeatureError,
)
from .frame import CanFrame

__all__ = [
    "CanBus",
    "CanFrame",
    "MessageDefinition",
    "CANError",
    "CANConfigurationError",
    "CANBackendError",
    "CANTimeoutError",
    "CANMessageError",
    "CANUnsupportedFeatureError",
]
