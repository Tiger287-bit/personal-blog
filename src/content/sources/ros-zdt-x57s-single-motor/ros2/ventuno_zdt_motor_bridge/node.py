# SPDX-License-Identifier: MIT

import json
import queue

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, Int32, String
from std_srvs.srv import SetBool, Trigger

from .websocket_client import MotorWebSocketClient


class VentunoZdtMotorBridgeNode(Node):
    """将ROS 2单电机话题与App Lab WebSocket协议互相转换。"""

    def __init__(self):
        """
        @description         : 创建ROS 2接口、参数、队列和WebSocket后台客户端
        @param               : 无参数
        @return              : 无返回值
        """
        super().__init__("ventuno_zdt_motor_bridge")
        self.declare_parameter("websocket_url", "ws://127.0.0.1:8765/ros")
        self.declare_parameter("reconnect_interval", 2.0)
        self.declare_parameter("heartbeat_interval", 1.0)
        self.declare_parameter("command_timeout", 0.3)
        self.declare_parameter("acceleration_level", 10)
        self.declare_parameter("maximum_rpm", 60)

        websocket_url = self.get_parameter("websocket_url").value
        reconnect_interval = self.get_parameter("reconnect_interval").value
        heartbeat_interval = self.get_parameter("heartbeat_interval").value
        command_timeout = self.get_parameter("command_timeout").value
        self._acceleration_level = int(
            self.get_parameter("acceleration_level").value
        )
        self._maximum_rpm = int(self.get_parameter("maximum_rpm").value)
        if not 0 <= self._acceleration_level <= 255:
            raise ValueError("acceleration_level must be in range 0-255")
        if self._maximum_rpm <= 0:
            raise ValueError("maximum_rpm must be greater than zero")

        self._incoming_messages = queue.Queue(maxsize=64)
        self._connection_events = queue.Queue(maxsize=4)
        self._last_connection_state = None
        self._motor_enabled = False

        self._speed_publisher = self.create_publisher(
            Int32,
            "/zdt_x57s/speed_rpm",
            10,
        )
        self._enabled_publisher = self.create_publisher(
            Bool,
            "/zdt_x57s/enabled",
            10,
        )
        self._connection_publisher = self.create_publisher(
            Bool,
            "/zdt_x57s/connected",
            10,
        )
        self._state_publisher = self.create_publisher(
            String,
            "/zdt_x57s/state",
            10,
        )
        self._target_subscription = self.create_subscription(
            Int32,
            "/zdt_x57s/target_rpm",
            self._handle_target_rpm,
            10,
        )
        self._enable_service = self.create_service(
            SetBool,
            "/zdt_x57s/enable",
            self._handle_enable_service,
        )
        self._stop_service = self.create_service(
            Trigger,
            "/zdt_x57s/stop",
            self._handle_stop_service,
        )

        self._client = MotorWebSocketClient(
            websocket_url=websocket_url,
            reconnect_interval=reconnect_interval,
            heartbeat_interval=heartbeat_interval,
            command_timeout=command_timeout,
            message_callback=self._queue_incoming_message,
            connection_callback=self._queue_connection_event,
            log_callback=self._log_from_thread,
            initial_mode="IDLE",
        )
        self._event_timer = self.create_timer(0.02, self._drain_events)
        self._client.start()

    def destroy_node(self):
        """
        @description         : 先停止WebSocket后台线程再销毁ROS 2节点
        @param               : 无参数
        @return              : 父类销毁结果
        """
        self._client.stop()
        return super().destroy_node()

    def _handle_target_rpm(self, message):
        """
        @description         : 校验ROS 2整数RPM并提交到最新值发送队列
        @param message       : std_msgs/msg/Int32目标转速消息
        @return              : 无返回值
        """
        rpm = int(message.data)
        if abs(rpm) > self._maximum_rpm:
            self.get_logger().warning(
                f"dropping target RPM {rpm}: limit is {self._maximum_rpm}"
            )
            return
        if not self._client.is_connected():
            self.get_logger().warning("dropping target RPM: App Lab is disconnected")
            return
        if rpm != 0 and not self._motor_enabled:
            self.get_logger().warning("dropping non-zero target RPM: motor is not enabled")
            return
        self._client.send_motor_speed(rpm, self._acceleration_level)

    def _handle_enable_service(self, request, response):
        """
        @description         : 将ROS 2使能服务转换为有顺序的模式与电机控制消息
        @param request       : std_srvs/srv/SetBool请求
        @param response      : std_srvs/srv/SetBool响应
        @return              : 已填写的服务响应
        """
        if not self._client.is_connected():
            response.success = False
            response.message = "App Lab WebSocket is disconnected"
            return response

        response.success = self._client.request_enable(bool(request.data))
        action = "enable" if request.data else "disable"
        response.message = (
            f"motor {action} request queued"
            if response.success
            else f"motor {action} request queue is full"
        )
        return response

    def _handle_stop_service(self, request, response):
        """
        @description         : 将ROS 2停车服务转换为停车和IDLE模式消息
        @param request       : std_srvs/srv/Trigger请求
        @param response      : std_srvs/srv/Trigger响应
        @return              : 已填写的服务响应
        """
        del request
        if not self._client.is_connected():
            response.success = False
            response.message = "App Lab WebSocket is disconnected"
            return response

        response.success = self._client.request_stop()
        response.message = (
            "motor stop request queued"
            if response.success
            else "motor stop request queue is full"
        )
        return response

    def _queue_incoming_message(self, message):
        """
        @description         : 从WebSocket线程向ROS主线程投递服务端消息
        @param message       : 已解析的服务端消息字典
        @return              : 无返回值
        """
        self._replace_bounded(self._incoming_messages, message)

    def _queue_connection_event(self, connected):
        """
        @description         : 从WebSocket线程向ROS主线程投递连接状态
        @param connected     : 新连接状态
        @return              : 无返回值
        """
        self._replace_bounded(self._connection_events, bool(connected))

    def _log_from_thread(self, level, message):
        """
        @description         : 输出WebSocket后台线程产生的诊断日志
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
        @description         : 在ROS主线程中发布连接事件与电机状态
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
        @description         : 发布WebSocket连接状态并在断线时清除本地使能状态
        @param connected     : 当前连接状态
        @return              : 无返回值
        """
        status_message = Bool()
        status_message.data = connected
        self._connection_publisher.publish(status_message)
        if not connected:
            self._motor_enabled = False
        if self._last_connection_state != connected:
            state_text = "connected" if connected else "disconnected"
            self.get_logger().info(f"App Lab gateway {state_text}")
            self._last_connection_state = connected

    def _handle_gateway_message(self, message):
        """
        @description         : 将motor_state、ack和error转换为ROS 2输出
        @param message       : 已解析的服务端消息
        @return              : 无返回值
        """
        message_type = message.get("type")
        if message_type == "motor_state":
            speed_message = Int32()
            speed_message.data = int(message.get("speed_rpm", 0))
            self._speed_publisher.publish(speed_message)

            self._motor_enabled = bool(message.get("enabled", False))
            enabled_message = Bool()
            enabled_message.data = self._motor_enabled
            self._enabled_publisher.publish(enabled_message)

            state_message = String()
            state_message.data = json.dumps(
                message,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            self._state_publisher.publish(state_message)
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
    @description         : 初始化rclpy并运行单电机桥接节点
    @param args          : 可选ROS 2命令行参数
    @return              : 无返回值
    """
    rclpy.init(args=args)
    node = VentunoZdtMotorBridgeNode()
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
