# SPDX-License-Identifier: MIT

import importlib.util
import json
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


class ProtocolTests(unittest.TestCase):
    """ROS Gateway JSON 协议单元测试。"""

    def make_cmd(self, **overrides):
        """
        @description         : 创建可按字段覆盖的标准 cmd_vel 测试消息
        @param overrides     : 需要覆盖的消息字段
        @return              : cmd_vel 消息字典
        """
        message = {
            "version": 1,
            "type": "cmd_vel",
            "seq": 1,
            "timestamp_ms": 1_750_000_000_000,
            "vx": 0.2,
            "vy": 0.0,
            "wz": 0.3,
        }
        message.update(overrides)
        return message

    def test_decode_valid_json(self):
        """
        @description         : 验证合法 JSON 能被解析
        @param               : 无参数
        @return              : 无返回值
        """
        message = protocol.decode_message(json.dumps(self.make_cmd()))
        self.assertEqual(message["type"], "cmd_vel")

    def test_decode_rejects_non_object(self):
        """
        @description         : 验证数组根节点会被拒绝
        @param               : 无参数
        @return              : 无返回值
        """
        with self.assertRaisesRegex(protocol.ProtocolError, "root must be an object"):
            protocol.decode_message("[]")

    def test_sequence_must_increase(self):
        """
        @description         : 验证重复或倒退序号会被拒绝
        @param               : 无参数
        @return              : 无返回值
        """
        with self.assertRaises(protocol.ProtocolError) as context:
            protocol.validate_sequence(self.make_cmd(seq=4), 4)
        self.assertEqual(context.exception.code, "non_monotonic_seq")

    def test_cmd_vel_accepts_valid_values(self):
        """
        @description         : 验证合法速度指令通过并转换为浮点数
        @param               : 无参数
        @return              : 无返回值
        """
        command = protocol.validate_cmd_vel(
            self.make_cmd(),
            "ROS_TELEOP",
            {"vx": 0.8, "vy": 0.8, "wz": 1.5},
            300,
            current_timestamp_ms=1_750_000_000_100,
        )
        self.assertEqual(command["vx"], 0.2)

    def test_cmd_vel_rejects_overspeed(self):
        """
        @description         : 验证超限速度被拒绝
        @param               : 无参数
        @return              : 无返回值
        """
        with self.assertRaises(protocol.ProtocolError) as context:
            protocol.validate_cmd_vel(
                self.make_cmd(vx=0.81),
                "ROS_TELEOP",
                {"vx": 0.8, "vy": 0.8, "wz": 1.5},
                300,
                current_timestamp_ms=1_750_000_000_100,
            )
        self.assertEqual(context.exception.code, "out_of_range")

    def test_cmd_vel_rejects_stale_timestamp(self):
        """
        @description         : 验证过期速度指令被拒绝
        @param               : 无参数
        @return              : 无返回值
        """
        with self.assertRaises(protocol.ProtocolError) as context:
            protocol.validate_cmd_vel(
                self.make_cmd(),
                "ROS_TELEOP",
                {"vx": 0.8, "vy": 0.8, "wz": 1.5},
                300,
                current_timestamp_ms=1_750_000_000_301,
            )
        self.assertEqual(context.exception.code, "stale_command")

    def test_cmd_vel_rejects_boolean_number(self):
        """
        @description         : 验证 JSON 布尔值不能冒充数值字段
        @param               : 无参数
        @return              : 无返回值
        """
        with self.assertRaises(protocol.ProtocolError) as context:
            protocol.validate_cmd_vel(
                self.make_cmd(vx=True),
                "ROS_TELEOP",
                {"vx": 0.8, "vy": 0.8, "wz": 1.5},
                300,
                current_timestamp_ms=1_750_000_000_100,
            )
        self.assertEqual(context.exception.code, "invalid_field")

    def test_nonzero_velocity_requires_teleop(self):
        """
        @description         : 验证非遥控模式拒绝非零速度
        @param               : 无参数
        @return              : 无返回值
        """
        with self.assertRaises(protocol.ProtocolError) as context:
            protocol.validate_cmd_vel(
                self.make_cmd(),
                "IDLE",
                {"vx": 0.8, "vy": 0.8, "wz": 1.5},
                300,
                current_timestamp_ms=1_750_000_000_100,
            )
        self.assertEqual(context.exception.code, "mode_denied")


if __name__ == "__main__":
    unittest.main(verbosity=2)
