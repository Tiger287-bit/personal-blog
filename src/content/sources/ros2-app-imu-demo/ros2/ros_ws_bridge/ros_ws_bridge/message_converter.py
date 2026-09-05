from functools import lru_cache

from rosidl_runtime_py import message_to_ordereddict
from rosidl_runtime_py import set_message_fields
from rosidl_runtime_py.utilities import get_message


class MessageConversionError(ValueError):
    """ROS message loading or field conversion failed."""


@lru_cache(maxsize=64)
def load_message_class(ros_type):
    """Dynamically load a ROS message class."""
    if not isinstance(ros_type, str) or not ros_type:
        raise MessageConversionError("ros_type must be a non-empty string")

    try:
        return get_message(ros_type)
    except Exception as exc:
        raise MessageConversionError(
            f"cannot load ROS message type {ros_type}: {exc}"
        ) from exc


def ros_message_to_data(message):
    """Convert a ROS message object into JSON-compatible fields."""
    try:
        return message_to_ordereddict(message)
    except Exception as exc:
        raise MessageConversionError(
            f"cannot convert ROS message to data: {exc}"
        ) from exc


def data_to_ros_message(ros_type, data):
    """Create a ROS message and populate it from a data dictionary."""
    if not isinstance(data, dict):
        raise MessageConversionError("data must be an object")

    message_class = load_message_class(ros_type)
    message = message_class()

    try:
        set_message_fields(message, data)
    except Exception as exc:
        raise MessageConversionError(
            f"invalid data for {ros_type}: {exc}"
        ) from exc

    return message