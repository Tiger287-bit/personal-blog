"""Backend extension point for the Generic CAN Brick."""

from .base import CanBackend
from .socketcan import SocketCANBackend

__all__ = ["CanBackend", "SocketCANBackend"]
