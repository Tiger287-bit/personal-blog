"""Publish alternating four-LED commands for the ROS2-02 lesson."""

import rclpy
from rclpy.node import Node
from std_msgs.msg import UInt8MultiArray


class LedCommandPublisher(Node):
    """Publish simulated four-LED commands."""

    def __init__(self):
        super().__init__('my_ros2_02_led_command_publisher')

        self.publisher = self.create_publisher(
            UInt8MultiArray,
            'my_ros2_02/led_command',
            10,
        )

        self.commands = [
            [0, 0, 0, 0],
            [1, 0, 1, 0],
            [0, 1, 0, 1],
            [1, 1, 1, 1],
        ]

        self.command_index = 0
        self.timer = self.create_timer(2.0, self.publish_command)

        self.get_logger().info(
            'LED command publisher started; ROS 2 simulation only'
        )

    def publish_command(self):
        command = self.commands[self.command_index]

        message = UInt8MultiArray()
        message.data = list(command)

        self.publisher.publish(message)

        self.get_logger().info(
            f'published LED command: {command} (0=off, 1=on)'
        )

        self.command_index = (
            self.command_index + 1
        ) % len(self.commands)


def main(args=None):
    rclpy.init(args=args)
    node = LedCommandPublisher()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info(
            'Ctrl-C received; stopping LED command publisher'
        )
    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()