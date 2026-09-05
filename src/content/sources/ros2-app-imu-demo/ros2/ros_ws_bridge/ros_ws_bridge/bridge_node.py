import queue
from functools import partial
from pathlib import Path

import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

from .config_loader import load_bridge_config
from .message_converter import (
    MessageConversionError,
    data_to_ros_message,
    load_message_class,
    ros_message_to_data,
)
from .protocol import (
    ProtocolError,
    build_message,
    decode_message,
    encode_message,
)
from .ws_client import ReconnectingWebSocketClient


class RosWsBridgeNode(Node):
    """Reusable bidirectional ROS 2 and WebSocket bridge."""

    def __init__(self):
        super().__init__("ros_ws_bridge")

        package_share = Path(
            get_package_share_directory("ros_ws_bridge")
        )
        default_config = package_share / "config" / "bridge.yaml"

        self.declare_parameter(
            "config_file",
            str(default_config),
        )
        config_file = self.get_parameter("config_file").value

        self.config = load_bridge_config(config_file)

        self._rules_by_topic = {
            rule.topic: rule
            for rule in self.config.topics
        }
        self._subscriptions_by_topic = {}
        self._publishers_by_topic = {}

        self._ros_to_ws_seq = 0
        self._inbound_queue = queue.Queue(maxsize=64)
        self._inbound_dropped = 0
        self._ws_client = None

        self._create_ros_interfaces()

        self._inbound_timer = self.create_timer(
            0.02,
            self._drain_inbound_queue,
        )

        self._ws_client = ReconnectingWebSocketClient(
            self.config.websocket.uri,
            on_message=self._enqueue_ws_message,
            reconnect_delay_s=(
                self.config.websocket.reconnect_delay_s
            ),
            max_message_bytes=(
                self.config.websocket.max_message_bytes
            ),
        )
        self._ws_client.start()

        self.get_logger().info(
            f"loaded {len(self.config.topics)} topic rules "
            f"from {config_file}"
        )
        self.get_logger().info(
            f"bidirectional WebSocket client started: "
            f"{self.config.websocket.uri}"
        )

    def _create_ros_interfaces(self):
        """Create publishers and subscriptions from YAML."""
        for rule in self.config.topics:
            message_class = load_message_class(rule.ros_type)

            if rule.direction == "ros_to_ws":
                subscription = self.create_subscription(
                    message_class,
                    rule.topic,
                    partial(self._on_ros_message, rule),
                    10,
                )
                self._subscriptions_by_topic[
                    rule.topic
                ] = subscription

                self.get_logger().info(
                    f"subscription ROS -> WS: "
                    f"{rule.topic} [{rule.ros_type}]"
                )
                continue

            publisher = self.create_publisher(
                message_class,
                rule.topic,
                10,
            )
            self._publishers_by_topic[rule.topic] = publisher

            self.get_logger().info(
                f"publisher WS -> ROS: "
                f"{rule.topic} [{rule.ros_type}]"
            )

    def _on_ros_message(self, rule, message):
        """Convert and send one ROS message to WebSocket."""
        sequence = self._ros_to_ws_seq
        self._ros_to_ws_seq += 1

        try:
            data = ros_message_to_data(message)
            envelope = build_message(
                topic=rule.topic,
                ros_type=rule.ros_type,
                direction="ros_to_ws",
                seq=sequence,
                data=data,
            )
            payload = encode_message(envelope)
        except (MessageConversionError, ProtocolError) as exc:
            self.get_logger().error(
                f"cannot encode {rule.topic}: {exc}"
            )
            return

        if not self._ws_client.send(payload):
            self.get_logger().warning(
                f"WebSocket disconnected; dropped "
                f"seq={sequence} topic={rule.topic}"
            )
            return

        self.get_logger().debug(
            f"sent seq={sequence} topic={rule.topic}"
        )

    def _enqueue_ws_message(self, payload):
        """Move WebSocket-thread data into a bounded queue."""
        try:
            self._inbound_queue.put_nowait(payload)
            return
        except queue.Full:
            pass

        try:
            self._inbound_queue.get_nowait()
        except queue.Empty:
            pass

        try:
            self._inbound_queue.put_nowait(payload)
        except queue.Full:
            pass

        self._inbound_dropped += 1

    def _drain_inbound_queue(self):
        """Process queued WebSocket messages in the ROS thread."""
        if self._inbound_dropped:
            dropped = self._inbound_dropped
            self._inbound_dropped = 0
            self.get_logger().warning(
                f"dropped {dropped} old inbound WebSocket messages"
            )

        for _ in range(32):
            try:
                payload = self._inbound_queue.get_nowait()
            except queue.Empty:
                return

            self._process_ws_message(payload)

    def _process_ws_message(self, payload):
        """Validate one envelope and publish it into ROS."""
        try:
            envelope = decode_message(payload)
        except ProtocolError as exc:
            self.get_logger().warning(
                f"rejected WebSocket message: {exc}"
            )
            return

        if envelope["direction"] != "ws_to_ros":
            self.get_logger().warning(
                "rejected WebSocket message with wrong direction: "
                f"{envelope['direction']}"
            )
            return

        topic = envelope["topic"]
        rule = self._rules_by_topic.get(topic)

        if rule is None or rule.direction != "ws_to_ros":
            self.get_logger().warning(
                f"rejected unconfigured WS -> ROS topic: {topic}"
            )
            return

        if envelope["ros_type"] != rule.ros_type:
            self.get_logger().warning(
                f"rejected type mismatch for {topic}: "
                f"expected {rule.ros_type}, "
                f"received {envelope['ros_type']}"
            )
            return

        try:
            message = data_to_ros_message(
                rule.ros_type,
                envelope["data"],
            )
            publisher = self._publishers_by_topic[topic]
            publisher.publish(message)
        except (MessageConversionError, KeyError) as exc:
            self.get_logger().warning(
                f"cannot publish {topic}: {exc}"
            )
            return

        self.get_logger().debug(
            f"published seq={envelope['seq']} topic={topic}"
        )

    def destroy_node(self):
        """Stop WebSocket before destroying ROS resources."""
        if self._ws_client is not None:
            self._ws_client.stop()
            self._ws_client = None

        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None

    try:
        node = RosWsBridgeNode()
        rclpy.spin(node)
    except (ExternalShutdownException, KeyboardInterrupt):
        pass
    finally:
        if node is not None:
            node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()