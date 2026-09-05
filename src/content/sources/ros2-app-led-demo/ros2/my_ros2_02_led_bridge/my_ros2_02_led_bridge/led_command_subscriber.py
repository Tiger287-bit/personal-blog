"""Subscribe to four-LED commands for the ROS2-02 lesson."""

import rclpy
from rclpy.node import Node
from std_msgs.msg import UInt8MultiArray


class LedCommandSubscriber(Node):
    """Receive and display simulated four-LED commands."""

    def __init__(self):
        super().__init__('my_ros2_02_led_command_subscriber')

        self.subscription = self.create_subscription(
            UInt8MultiArray,
            'my_ros2_02/led_command',
            self.receive_command,
            10,
        )

        self.get_logger().info(
            'LED command subscriber started; ROS 2 simulation only'
        )

    def receive_command(self, message):
        command = list(message.data)

        if len(command) != 4:
            self.get_logger().warning(
                f'ignoring LED command {command}: expected 4 values'
            )
            return

        if any(value not in (0, 1) for value in command):
            self.get_logger().warning(
                f'ignoring LED command {command}: values must be 0 or 1'
            )
            return

        states = [
            'ON' if value == 1 else 'OFF'
            for value in command
        ]

        self.get_logger().info(
            f'received LED command: {command}'
        )
        self.get_logger().info(
            f'simulated LED states: '
            f'LED1={states[0]}, LED2={states[1]}, '
            f'LED3={states[2]}, LED4={states[3]}'
        )


def main(args=None):
    rclpy.init(args=args)
    node = LedCommandSubscriber()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info(
            'Ctrl-C received; stopping LED command subscriber'
        )
    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()