# SPDX-License-Identifier: MIT
"""Unified public exceptions for the Generic CAN Brick."""


class CANError(Exception):
    """Base class for every error intentionally exposed by this Brick."""


class CANConfigurationError(CANError, ValueError):
    """A public argument or static definition is invalid."""


class CANBackendError(CANError, OSError):
    """The operating-system or hardware backend failed."""


class CANTimeoutError(CANError, TimeoutError):
    """A named receive operation did not get its expected frame in time."""


class CANMessageError(CANError):
    """A named message could not be encoded, decoded, or used as requested."""


class CANUnsupportedFeatureError(CANError, NotImplementedError):
    """The caller requested a feature outside the current V1 scope."""
