"""SocketCANBackend与python-can边界映射测试。"""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from generic_can import CANBackendError, CanFrame
from generic_can.backends import SocketCANBackend


class FakePythonCanBus:
    """记录SocketCANBackend对python-can Bus的调用。"""

    def __init__(self):
        """
        @description         : 创建空的发送记录和接收脚本
        @param self          : 当前FakePythonCanBus对象
        @return              : 无
        """
        self.sent = []
        self.receive_values = []
        self.receive_timeouts = []
        self.shutdown_count = 0

    def send(self, message):
        """
        @description         : 记录一条模拟python-can Message
        @param self          : 当前FakePythonCanBus对象
        @param message       : 待记录的模拟Message
        @return              : 无
        """
        self.sent.append(message)

    def recv(self, timeout):
        """
        @description         : 按测试脚本返回下一条模拟接收结果
        @param self          : 当前FakePythonCanBus对象
        @param timeout       : 后端传入的等待秒数
        @return              : 模拟Message或None
        """
        self.receive_timeouts.append(timeout)
        if not self.receive_values:
            return None
        return self.receive_values.pop(0)

    def shutdown(self):
        """
        @description         : 记录一次python-can Bus关闭动作
        @param self          : 当前FakePythonCanBus对象
        @return              : 无
        """
        self.shutdown_count += 1


class FakePythonCanModule:
    """提供SocketCANBackend实际使用的Bus和Message入口。"""

    def __init__(self):
        """
        @description         : 创建一个可注入后端的python-can兼容模块
        @param self          : 当前FakePythonCanModule对象
        @return              : 无
        """
        self.bus = FakePythonCanBus()
        self.bus_options = None

    def Bus(self, **options):
        """
        @description         : 保存Bus构造参数并返回模拟Bus
        @param self          : 当前FakePythonCanModule对象
        @param options       : SocketCANBackend传入的关键字参数
        @return              : 模拟python-can Bus
        """
        self.bus_options = options
        return self.bus

    def Message(self, **fields):
        """
        @description         : 把Message字段保存为简单属性对象
        @param self          : 当前FakePythonCanModule对象
        @param fields        : SocketCANBackend传入的报文字段
        @return              : 模拟python-can Message
        """
        return SimpleNamespace(**fields)


def incoming_message(**overrides):
    """
    @description         : 创建一条包含python-can常用字段的模拟接收消息
    @param overrides     : 需要覆盖的消息字段
    @return              : 模拟python-can Message
    """
    fields = {
        "arbitration_id": 0x123,
        "data": bytearray([1, 2]),
        "is_extended_id": False,
        "is_fd": False,
        "bitrate_switch": False,
        "timestamp": 12.5,
        "is_error_frame": False,
        "is_remote_frame": False,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


class SocketCANBackendTests(unittest.TestCase):
    """验证唯一允许接触python-can的后端模块。"""

    def setUp(self):
        """
        @description         : 为每个测试创建新的模拟python-can模块和后端
        @param self          : 当前测试用例
        @return              : 无
        """
        self.can_module = FakePythonCanModule()
        self.backend = SocketCANBackend(
            device="can7",
            can_module=self.can_module,
        )

    def test_open_passes_selected_interface_and_fd_capability(self):
        """
        @description         : 验证用户可选择接口且后端启用FD帧处理能力
        @param self          : 当前测试用例
        @return              : 无
        """
        self.backend.open()
        self.assertEqual(
            self.can_module.bus_options,
            {"interface": "socketcan", "channel": "can7", "fd": True},
        )

    def test_send_maps_every_public_frame_field(self):
        """
        @description         : 验证CanFrame字段完整映射为python-can Message
        @param self          : 当前测试用例
        @return              : 无
        """
        self.backend.open()
        frame = CanFrame(
            0x123456,
            b"\x01\x02",
            is_extended=True,
            is_fd=True,
            bitrate_switch=True,
        )
        self.backend.send(frame)
        message = self.can_module.bus.sent[0]
        self.assertEqual(message.arbitration_id, 0x123456)
        self.assertEqual(message.data, b"\x01\x02")
        self.assertTrue(message.is_extended_id)
        self.assertTrue(message.is_fd)
        self.assertTrue(message.bitrate_switch)
        self.assertTrue(message.check)

    def test_receive_maps_data_frame_and_timestamp(self):
        """
        @description         : 验证python-can接收消息完整转换为CanFrame
        @param self          : 当前测试用例
        @return              : 无
        """
        self.backend.open()
        self.can_module.bus.receive_values.append(
            incoming_message(
                arbitration_id=0x456,
                is_fd=True,
                bitrate_switch=True,
            )
        )
        self.assertEqual(
            self.backend.receive(0.1),
            CanFrame(
                0x456,
                b"\x01\x02",
                is_fd=True,
                bitrate_switch=True,
                timestamp=12.5,
            ),
        )

    def test_error_and_remote_frames_are_ignored_and_counted(self):
        """
        @description         : 验证错误帧和远程帧不进入业务队列且可诊断
        @param self          : 当前测试用例
        @return              : 无
        """
        self.backend.open()
        self.can_module.bus.receive_values.extend(
            [
                incoming_message(is_error_frame=True),
                incoming_message(is_remote_frame=True),
                incoming_message(arbitration_id=0x555),
            ]
        )
        self.assertEqual(self.backend.receive(1.0).arbitration_id, 0x555)
        self.assertEqual(self.backend.ignored_error_frames, 1)
        self.assertEqual(self.backend.ignored_remote_frames, 1)

    def test_nonblocking_receive_skips_filtered_frames(self):
        """
        @description         : 验证零超时时也会跳过过滤帧并读取其后的数据帧
        @param self          : 当前测试用例
        @return              : 无
        """
        self.backend.open()
        self.can_module.bus.receive_values.extend(
            [
                incoming_message(is_error_frame=True),
                incoming_message(arbitration_id=0x600),
            ]
        )
        self.assertEqual(self.backend.receive(0).arbitration_id, 0x600)

    def test_receive_timeout_still_expires_while_filtered_frames_arrive(self):
        """
        @description         : 验证错误帧和远程帧不会无限延长正数接收超时
        @param self          : 当前测试用例
        @return              : 无
        """
        self.backend.open()
        self.can_module.bus.receive_values.extend(
            [
                incoming_message(is_error_frame=True),
                incoming_message(is_remote_frame=True),
                incoming_message(is_error_frame=True),
            ]
        )
        with patch(
            "generic_can.backends.socketcan.time.monotonic",
            side_effect=(10.0, 10.001, 10.002, 10.006),
        ):
            self.assertIsNone(self.backend.receive(0.005))

        self.assertEqual(len(self.can_module.bus.receive_timeouts), 2)
        self.assertGreater(self.can_module.bus.receive_timeouts[0], 0.0)
        self.assertGreater(self.can_module.bus.receive_timeouts[1], 0.0)
        self.assertEqual(self.backend.ignored_error_frames, 1)
        self.assertEqual(self.backend.ignored_remote_frames, 1)

    def test_close_is_idempotent(self):
        """
        @description         : 验证关闭两次只释放一次python-can Bus
        @param self          : 当前测试用例
        @return              : 无
        """
        self.backend.open()
        self.backend.close()
        self.backend.close()
        self.assertEqual(self.can_module.bus.shutdown_count, 1)

    def test_operations_before_open_raise_unified_error(self):
        """
        @description         : 验证未打开时发送和接收抛出统一后端异常
        @param self          : 当前测试用例
        @return              : 无
        """
        with self.assertRaises(CANBackendError):
            self.backend.send(CanFrame(1))
        with self.assertRaises(CANBackendError):
            self.backend.receive(0)


if __name__ == "__main__":
    unittest.main()
