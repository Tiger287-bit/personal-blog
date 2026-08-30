# SPDX-License-Identifier: MIT

import json
import unittest
from unittest.mock import Mock

from ventuno_app_bridge.websocket_client import WebSocketBridgeClient


class TestWebSocketBridgeClient(unittest.TestCase):
    """验证 ROS 2 WebSocket 客户端的本地队列与协议编码。"""

    def setUp(self):
        """
        @description         : 为每个测试创建相互隔离的客户端和回调记录器
        @param               : 无参数
        @return              : 无返回值
        """
        self.messages = []
        self.connection_changes = []
        self.logs = []
        self.client = WebSocketBridgeClient(
            websocket_url="ws://127.0.0.1:8765/ros",
            reconnect_interval=0.1,
            heartbeat_interval=1.0,
            command_timeout=0.3,
            message_callback=self.messages.append,
            connection_callback=self.connection_changes.append,
            log_callback=lambda level, message: self.logs.append((level, message)),
        )

    def test_latest_velocity_replaces_older_command(self):
        """
        @description         : 验证速度队列仅保留最新命令并编码协议公共字段
        @param               : 无参数
        @return              : 无返回值
        """
        websocket = Mock()
        self.client.send_cmd_vel(0.1, 0.2, 0.3)
        self.client.send_cmd_vel(-0.4, 0.5, -0.6)

        self.client._send_latest_command(websocket)

        websocket.send.assert_called_once()
        message = json.loads(websocket.send.call_args.args[0])
        self.assertEqual(message["version"], 1)
        self.assertEqual(message["type"], "cmd_vel")
        self.assertEqual(message["seq"], 1)
        self.assertEqual(message["vx"], -0.4)
        self.assertEqual(message["vy"], 0.5)
        self.assertEqual(message["wz"], -0.6)

    def test_stale_velocity_is_not_sent(self):
        """
        @description         : 验证超过本地时限的速度命令会被丢弃
        @param               : 无参数
        @return              : 无返回值
        """
        websocket = Mock()
        self.client._latest_command.put_nowait(
            {
                "timestamp_ms": self.client._now_ms() - 1000,
                "vx": 0.1,
                "vy": 0.0,
                "wz": 0.0,
            }
        )

        self.client._send_latest_command(websocket)

        websocket.send.assert_not_called()
        self.assertTrue(any("stale local cmd_vel" in item[1] for item in self.logs))

    def test_connection_callback_only_reports_changes(self):
        """
        @description         : 验证连接状态回调不会重复发布相同状态
        @param               : 无参数
        @return              : 无返回值
        """
        self.client._set_connected(True)
        self.client._set_connected(True)
        self.client._set_connected(False)
        self.client._set_connected(False)

        self.assertEqual(self.connection_changes, [True, False])

    def test_mode_queue_is_bounded(self):
        """
        @description         : 验证控制请求队列达到上限后拒绝继续增长
        @param               : 无参数
        @return              : 无返回值
        """
        results = [self.client.request_mode("ROS_TELEOP") for _ in range(9)]

        self.assertEqual(results, ([True] * 8) + [False])
        self.assertEqual(self.client._control_queue.qsize(), 8)

    def test_receive_requires_json_object(self):
        """
        @description         : 验证服务端消息根节点必须是 JSON 对象
        @param               : 无参数
        @return              : 无返回值
        """
        websocket = Mock()
        websocket.recv.return_value = "[]"

        with self.assertRaisesRegex(RuntimeError, "JSON root"):
            self.client._receive_json(websocket, timeout=0.1)


if __name__ == "__main__":
    unittest.main()
