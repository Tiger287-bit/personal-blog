# SPDX-License-Identifier: MIT

import json
import unittest
from unittest.mock import Mock

from ventuno_zdt_motor_bridge.websocket_client import MotorWebSocketClient


class TestMotorWebSocketClient(unittest.TestCase):
    """验证单电机WebSocket客户端的安全队列和协议编码。"""

    def setUp(self):
        """
        @description         : 为每个测试创建隔离客户端和日志记录器
        @param               : 无参数
        @return              : 无返回值
        """
        self.logs = []
        self.client = MotorWebSocketClient(
            websocket_url="ws://127.0.0.1:8765/ros",
            reconnect_interval=0.1,
            heartbeat_interval=1.0,
            command_timeout=0.3,
            message_callback=lambda message: None,
            connection_callback=lambda connected: None,
            log_callback=lambda level, message: self.logs.append((level, message)),
        )

    def test_latest_rpm_replaces_older_command(self):
        """
        @description         : 验证速度队列只保留最新RPM并包含完整协议字段
        @param               : 无参数
        @return              : 无返回值
        """
        websocket = Mock()
        self.client.send_motor_speed(10, 5)
        self.client.send_motor_speed(-20, 10)
        self.client._send_latest_speed(websocket)

        websocket.send.assert_called_once()
        message = json.loads(websocket.send.call_args.args[0])
        self.assertEqual(message["version"], 1)
        self.assertEqual(message["type"], "motor_set_speed")
        self.assertEqual(message["rpm"], -20)
        self.assertEqual(message["acceleration_level"], 10)

    def test_stale_rpm_is_not_sent(self):
        """
        @description         : 验证本地过期RPM不会进入WebSocket
        @param               : 无参数
        @return              : 无返回值
        """
        websocket = Mock()
        self.client._latest_speed.put_nowait(
            {
                "timestamp_ms": self.client._now_ms() - 1000,
                "rpm": 20,
                "acceleration_level": 10,
            }
        )
        self.client._send_latest_speed(websocket)

        websocket.send.assert_not_called()
        self.assertTrue(any("stale motor RPM" in item[1] for item in self.logs))

    def test_enable_queues_mode_before_enable(self):
        """
        @description         : 验证使能前先请求ROS_TELEOP模式
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertTrue(self.client.request_enable(True))
        first = self.client._control_queue.get_nowait()
        second = self.client._control_queue.get_nowait()
        self.assertEqual(first["type"], "mode_change")
        self.assertEqual(first["mode"], "ROS_TELEOP")
        self.assertEqual(second["type"], "motor_enable")
        self.assertTrue(second["enabled"])

    def test_stop_discards_pending_rpm(self):
        """
        @description         : 验证停车请求会先清除尚未发送的RPM
        @param               : 无参数
        @return              : 无返回值
        """
        self.client.send_motor_speed(20, 10)
        self.assertTrue(self.client.request_stop())
        self.assertTrue(self.client._latest_speed.empty())
        self.assertEqual(self.client._control_queue.get_nowait()["type"], "motor_stop")

    def test_disconnect_clears_commands(self):
        """
        @description         : 验证断线后不会重放旧使能或旧速度命令
        @param               : 无参数
        @return              : 无返回值
        """
        self.client.send_motor_speed(20, 10)
        self.client.request_enable(True)
        self.client._clear_command_queues()
        self.assertTrue(self.client._latest_speed.empty())
        self.assertTrue(self.client._control_queue.empty())


if __name__ == "__main__":
    unittest.main(verbosity=2)
