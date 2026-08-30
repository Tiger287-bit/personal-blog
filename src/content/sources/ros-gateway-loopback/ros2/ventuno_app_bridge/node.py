# SPDX-License-Identifier: MIT

import json
import queue

import rclpy
from geometry_msgs.msg import Twist, TwistStamped
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, String

from .websocket_client import WebSocketBridgeClient


class VentunoAppBridgeNode(Node):
    """把标准 ROS 2 速度话题转换为 App Lab WebSocket 协议。"""

    def __init__(self):
        """
        @description         : 声明参数、创建 ROS 接口并启动 WebSocket 客户端
        @param               : 无参数
        @return              : 无返回值
        """
        super().__init__("ventuno_app_bridge_node")
        self.declare_parameter("websocket_url", "ws://127.0.0.1:8765/ros")
        self.declare_parameter("reconnect_interval", 2.0)
        self.declare_parameter("heartbeat_interval", 1.0)
        self.declare_parameter("command_timeout", 0.3)
        self.declare_parameter("use_twist_stamped", False)

        self._incoming_messages = queue.Queue(maxsize=64)
        self._connection_events = queue.Queue(maxsize=4)
        self._last_connection_state = None

        connection_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._connection_publisher = self.create_publisher(
            Bool,
            "/ventuno/connection",
            connection_qos,
        )
        self._base_state_publisher = self.create_publisher(
            String,
            "/ventuno/base_state",
            10,
        )

        use_twist_stamped = self.get_parameter("use_twist_stamped").value
        if use_twist_stamped:
            self._cmd_vel_subscription = self.create_subscription(
                TwistStamped,
                "/cmd_vel",
                self._handle_twist_stamped,
                10,
            )
            command_type = "geometry_msgs/msg/TwistStamped"
        else:
            self._cmd_vel_subscription = self.create_subscription(
                Twist,
                "/cmd_vel",
                self._handle_twist,
                10,
            )
            command_type = "geometry_msgs/msg/Twist"

        self._client = WebSocketBridgeClient(
            websocket_url=self.get_parameter("websocket_url").value,
            reconnect_interval=self.get_parameter("reconnect_interval").value,
            heartbeat_interval=self.get_parameter("heartbeat_interval").value,
            command_timeout=self.get_parameter("command_timeout").value,
            message_callback=self._queue_incoming_message,
            connection_callback=self._queue_connection_event,
            log_callback=self._log_from_thread,
        )
        self._drain_timer = self.create_timer(0.05, self._drain_events)
        self._client.start()
        self.get_logger().info(
            f"subscribing /cmd_vel as {command_type}; "
            f"gateway={self.get_parameter('websocket_url').value}"
        )

    def destroy_node(self):
        """
        @description         : 在销毁 ROS 2 节点前停止 WebSocket 后台线程
        @param               : 无参数
        @return              : 父类销毁结果
        """
        self._client.stop()
        return super().destroy_node()

    def _handle_twist(self, message):
        """
        @description         : 将 Twist 速度消息提交到只保留最新值的发送队列
        @param message       : geometry_msgs/msg/Twist 消息
        @return              : 无返回值
        """
        self._client.send_cmd_vel(
            message.linear.x,
            message.linear.y,
            message.angular.z,
        )

    def _handle_twist_stamped(self, message):
        """
        @description         : 将 TwistStamped 内的速度提交到发送队列
        @param message       : geometry_msgs/msg/TwistStamped 消息
        @return              : 无返回值
        """
        self._handle_twist(message.twist)

    def _queue_incoming_message(self, message):
        """
        @description         : 从 WebSocket 线程向 ROS 主线程投递消息
        @param message       : 已解析的服务端消息字典
        @return              : 无返回值
        """
        self._replace_bounded(self._incoming_messages, message)

    def _queue_connection_event(self, connected):
        """
        @description         : 从 WebSocket 线程向 ROS 主线程投递连接状态
        @param connected     : 新连接状态
        @return              : 无返回值
        """
        self._replace_bounded(self._connection_events, bool(connected))

    def _log_from_thread(self, level, message):
        """
        @description         : 输出 WebSocket 后台线程产生的诊断日志
        @param level         : 日志级别
        @param message       : 日志文本
        @return              : 无返回值
        """
        logger = self.get_logger()
        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)

    def _drain_events(self):
        """
        @description         : 在 ROS 主线程中发布连接状态和 App 模拟状态
        @param               : 无参数
        @return              : 无返回值
        """
        while True:
            try:
                connected = self._connection_events.get_nowait()
            except queue.Empty:
                break
            self._publish_connection(connected)

        while True:
            try:
                message = self._incoming_messages.get_nowait()
            except queue.Empty:
                break
            self._handle_gateway_message(message)

    def _publish_connection(self, connected):
        """
        @description         : 发布连接状态并在状态变化时写日志
        @param connected     : 当前连接状态
        @return              : 无返回值
        """
        status_message = Bool()
        status_message.data = connected
        self._connection_publisher.publish(status_message)
        if self._last_connection_state != connected:
            state_text = "connected" if connected else "disconnected"
            self.get_logger().info(f"App Lab gateway {state_text}")
            self._last_connection_state = connected

    def _handle_gateway_message(self, message):
        """
        @description         : 将服务端消息转换为当前阶段 ROS 2 输出
        @param message       : 已解析服务端消息
        @return              : 无返回值
        """
        message_type = message.get("type")
        if message_type == "base_state":
            raw_state = String()
            raw_state.data = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
            self._base_state_publisher.publish(raw_state)
        elif message_type == "ack":
            self.get_logger().info(
                f"gateway ack: command={message.get('command')} "
                f"accepted={message.get('accepted')} mode={message.get('mode')}"
            )
        elif message_type == "error":
            self.get_logger().warning(
                f"gateway rejected message: code={message.get('code')} "
                f"detail={message.get('message')}"
            )

    @staticmethod
    def _replace_bounded(target_queue, value):
        """
        @description         : 有界队列满时丢弃最旧事件并插入最新事件
        @param target_queue  : 目标队列
        @param value         : 新事件
        @return              : 无返回值
        """
        try:
            target_queue.put_nowait(value)
            return
        except queue.Full:
            pass
        try:
            target_queue.get_nowait()
        except queue.Empty:
            pass
        target_queue.put_nowait(value)


def main(args=None):
    """
    @description         : 初始化 rclpy 并运行 Ventuno App Bridge 节点
    @param args          : 可选 ROS 2 命令行参数
    @return              : 无返回值
    """
    rclpy.init(args=args)
    node = VentunoAppBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
