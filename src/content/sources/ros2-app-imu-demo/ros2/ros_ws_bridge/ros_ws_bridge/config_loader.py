from dataclasses import dataclass
from pathlib import Path

import yaml

from .message_converter import (
    MessageConversionError,
    load_message_class,
)


DIRECTIONS = {"ros_to_ws", "ws_to_ros"}


class ConfigError(ValueError):
    """Bridge configuration is invalid."""


@dataclass(frozen=True)
class WebSocketSettings:
    uri: str
    reconnect_delay_s: float
    max_message_bytes: int


@dataclass(frozen=True)
class TopicRule:
    topic: str
    ros_type: str
    direction: str


@dataclass(frozen=True)
class BridgeConfig:
    websocket: WebSocketSettings
    topics: tuple[TopicRule, ...]


def load_bridge_config(path):
    """Load and validate one bridge YAML file."""
    config_path = Path(path)

    try:
        raw = yaml.safe_load(config_path.read_text())
    except OSError as exc:
        raise ConfigError(
            f"cannot read config file {config_path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"invalid YAML in {config_path}: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be an object")

    websocket = _parse_websocket(raw.get("websocket"))
    topics = _parse_topics(raw.get("topics"))

    return BridgeConfig(
        websocket=websocket,
        topics=tuple(topics),
    )


def _parse_websocket(raw):
    if not isinstance(raw, dict):
        raise ConfigError("websocket must be an object")

    uri = raw.get("uri")
    if not isinstance(uri, str) or not uri.startswith(
        ("ws://", "wss://")
    ):
        raise ConfigError("websocket.uri must start with ws:// or wss://")

    reconnect_delay = raw.get("reconnect_delay_s")
    if (
        type(reconnect_delay) not in (int, float)
        or reconnect_delay <= 0
    ):
        raise ConfigError(
            "websocket.reconnect_delay_s must be positive"
        )

    max_message_bytes = raw.get("max_message_bytes")
    if (
        type(max_message_bytes) is not int
        or max_message_bytes <= 0
    ):
        raise ConfigError(
            "websocket.max_message_bytes must be a positive integer"
        )

    return WebSocketSettings(
        uri=uri,
        reconnect_delay_s=float(reconnect_delay),
        max_message_bytes=max_message_bytes,
    )


def _parse_topics(raw):
    if not isinstance(raw, list) or not raw:
        raise ConfigError("topics must be a non-empty list")

    rules = []
    seen_topics = set()

    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ConfigError(f"topics[{index}] must be an object")

        topic = item.get("topic")
        ros_type = item.get("ros_type")
        direction = item.get("direction")

        if (
            not isinstance(topic, str)
            or not topic.startswith("/")
            or any(character.isspace() for character in topic)
        ):
            raise ConfigError(
                f"topics[{index}].topic must be an absolute topic name"
            )

        if topic in seen_topics:
            raise ConfigError(
                f"duplicate topic is not allowed: {topic}"
            )
        seen_topics.add(topic)

        if direction not in DIRECTIONS:
            raise ConfigError(
                f"topics[{index}].direction must be "
                "ros_to_ws or ws_to_ros"
            )

        try:
            load_message_class(ros_type)
        except MessageConversionError as exc:
            raise ConfigError(
                f"topics[{index}] cannot load {ros_type!r}"
            ) from exc

        rules.append(
            TopicRule(
                topic=topic,
                ros_type=ros_type,
                direction=direction,
            )
        )

    return rules