# SPDX-License-Identifier: MIT

import importlib.util
from pathlib import Path
import unittest


PROTOCOL_PATH = (
    Path(__file__).resolve().parents[1]
    / "bricks"
    / "ros_gateway"
    / "protocol.py"
)
SPEC = importlib.util.spec_from_file_location("ros_gateway_protocol", PROTOCOL_PATH)
protocol = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(protocol)


class MotorProtocolTests(unittest.TestCase):
    """单电机ROS WebSocket报文校验测试。"""

    def make_speed(self, **overrides):
        """
        @description         : 创建可覆盖字段的标准单电机速度消息
        @param overrides     : 需要覆盖的协议字段
        @return              : motor_set_speed消息字典
        """
        message = {
            "version": 1,
            "type": "motor_set_speed",
            "seq": 1,
            "timestamp_ms": 1_750_000_000_000,
            "rpm": 20,
            "acceleration_level": 10,
        }
        message.update(overrides)
        return message

    def test_valid_speed_is_normalized(self):
        """
        @description         : 验证合法整数RPM和加减速档位可以通过
        @param               : 无参数
        @return              : 无返回值
        """
        command = protocol.validate_motor_set_speed(
            self.make_speed(),
            "ROS_TELEOP",
            60,
            300,
            current_timestamp_ms=1_750_000_000_100,
        )
        self.assertEqual(command["rpm"], 20)
        self.assertEqual(command["acceleration_level"], 10)

    def test_speed_rejects_float_rpm(self):
        """
        @description         : 验证浮点RPM不会被静默截断
        @param               : 无参数
        @return              : 无返回值
        """
        with self.assertRaises(protocol.ProtocolError) as context:
            protocol.validate_motor_set_speed(
                self.make_speed(rpm=20.5),
                "ROS_TELEOP",
                60,
                300,
                current_timestamp_ms=1_750_000_000_100,
            )
        self.assertEqual(context.exception.code, "invalid_field")

    def test_speed_rejects_overspeed(self):
        """
        @description         : 验证超过配置上限的RPM被拒绝
        @param               : 无参数
        @return              : 无返回值
        """
        with self.assertRaises(protocol.ProtocolError) as context:
            protocol.validate_motor_set_speed(
                self.make_speed(rpm=61),
                "ROS_TELEOP",
                60,
                300,
                current_timestamp_ms=1_750_000_000_100,
            )
        self.assertEqual(context.exception.code, "out_of_range")

    def test_nonzero_speed_requires_teleop(self):
        """
        @description         : 验证非遥控模式只允许零速命令
        @param               : 无参数
        @return              : 无返回值
        """
        with self.assertRaises(protocol.ProtocolError) as context:
            protocol.validate_motor_set_speed(
                self.make_speed(),
                "IDLE",
                60,
                300,
                current_timestamp_ms=1_750_000_000_100,
            )
        self.assertEqual(context.exception.code, "mode_denied")

    def test_enable_requires_boolean(self):
        """
        @description         : 验证使能字段不能使用数字冒充布尔值
        @param               : 无参数
        @return              : 无返回值
        """
        message = {
            "version": 1,
            "type": "motor_enable",
            "seq": 1,
            "timestamp_ms": 1_750_000_000_000,
            "enabled": 1,
        }
        with self.assertRaises(protocol.ProtocolError) as context:
            protocol.validate_motor_enable(message, "ROS_TELEOP")
        self.assertEqual(context.exception.code, "invalid_field")

    def test_stop_is_allowed_without_teleop(self):
        """
        @description         : 验证安全停车不依赖当前运行模式
        @param               : 无参数
        @return              : 无返回值
        """
        message = {
            "version": 1,
            "type": "motor_stop",
            "seq": 9,
            "timestamp_ms": 1_750_000_000_000,
        }
        command = protocol.validate_motor_stop(message)
        self.assertEqual(command["seq"], 9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
