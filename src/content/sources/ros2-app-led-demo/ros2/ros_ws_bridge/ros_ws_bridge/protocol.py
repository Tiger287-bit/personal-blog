import json
import re
import time


DIRECTIONS = {"ros_to_ws", "ws_to_ros"}
ROS_TYPE_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]*/msg/[A-Za-z][A-Za-z0-9_]*$"
)
REQUIRED_FIELDS = {
    "topic",
    "ros_type",
    "direction",
    "seq",
    "timestamp",
    "data",
}


class ProtocolError(ValueError):
    """A WebSocket JSON envelope is invalid."""


def now_ms():
    """Return the Unix timestamp in milliseconds."""
    return time.time_ns() // 1_000_000


def validate_envelope(message):
    """Validate the common fields without interpreting ROS data."""
    if not isinstance(message, dict):
        raise ProtocolError("JSON root must be an object")

    missing = REQUIRED_FIELDS - message.keys()
    if missing:
        raise ProtocolError(
            f"missing required fields: {', '.join(sorted(missing))}"
        )

    topic = message["topic"]
    if not isinstance(topic, str) or not topic.startswith("/"):
        raise ProtocolError("topic must be an absolute ROS topic name")

    ros_type = message["ros_type"]
    if not isinstance(ros_type, str) or not ROS_TYPE_PATTERN.fullmatch(ros_type):
        raise ProtocolError(
            "ros_type must use package/msg/Message format"
        )

    if message["direction"] not in DIRECTIONS:
        raise ProtocolError(
            "direction must be ros_to_ws or ws_to_ros"
        )

    if type(message["seq"]) is not int or message["seq"] < 0:
        raise ProtocolError("seq must be a non-negative integer")

    if type(message["timestamp"]) is not int or message["timestamp"] <= 0:
        raise ProtocolError(
            "timestamp must be a positive Unix millisecond integer"
        )

    if not isinstance(message["data"], dict):
        raise ProtocolError("data must be a ROS message field object")

    return message


def build_message(
    *,
    topic,
    ros_type,
    direction,
    seq,
    data,
    timestamp=None,
):
    """Build and validate one protocol message."""
    message = {
        "topic": topic,
        "ros_type": ros_type,
        "direction": direction,
        "seq": seq,
        "timestamp": now_ms() if timestamp is None else timestamp,
        "data": data,
    }
    return validate_envelope(message)


def encode_message(message):
    """Encode one envelope as a compact JSON text frame."""
    validate_envelope(message)
    try:
        return json.dumps(
            message,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"data is not JSON serializable: {exc}") from exc


def decode_message(raw_message):
    """Decode and validate a JSON text frame."""
    if isinstance(raw_message, bytes):
        try:
            raw_message = raw_message.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("message must be UTF-8") from exc

    if not isinstance(raw_message, str):
        raise ProtocolError("message must be text or UTF-8 bytes")

    try:
        message = json.loads(raw_message)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {exc.msg}") from exc

    return validate_envelope(message)