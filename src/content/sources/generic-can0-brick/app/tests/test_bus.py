"""CanBus生命周期、分发、超时和队列策略测试。"""

import threading
import time
import unittest

from fake_backend import FakeBackend
from generic_can import (
    CANBackendError,
    CANConfigurationError,
    CANMessageError,
    CANTimeoutError,
    CanBus,
    CanFrame,
    MessageDefinition,
)
from generic_can.backends import SocketCANBackend


def wait_until(predicate, timeout_s=1.0):
    """
    @description         : 在限定时间内轮询等待测试条件成立
    @param predicate     : 返回布尔值的无参数函数
    @param timeout_s     : 最长等待秒数
    @return              : 条件是否在超时前成立
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


class CanBusTests(unittest.TestCase):
    """使用FakeBackend验证公开CanBus行为。"""

    def setUp(self):
        """
        @description         : 为每个测试创建独立FakeBackend
        @param self          : 当前测试用例
        @return              : 无
        """
        self.backend = FakeBackend()

    def tearDown(self):
        """
        @description         : 测试后关闭仍在运行的CanBus
        @param self          : 当前测试用例
        @return              : 无
        """
        test_bus = getattr(self, "bus", None)
        if test_bus is not None and test_bus.is_open:
            test_bus.close()

    def make_bus(self, **options):
        """
        @description         : 用本测试的FakeBackend创建CanBus
        @param self          : 当前测试用例
        @param options       : 覆盖CanBus默认值的关键字参数
        @return              : 新建的CanBus
        """
        self.bus = CanBus(
            backend=self.backend,
            receiver_poll_s=0.01,
            **options,
        )
        return self.bus

    def test_open_is_idempotent_and_uses_one_receiver(self):
        """
        @description         : 验证重复open不会打开后端或启动第二个接收线程
        @param self          : 当前测试用例
        @return              : 无
        """
        test_bus = self.make_bus().open()
        receiver = test_bus._receiver_thread
        test_bus.open()
        self.assertEqual(self.backend.open_count, 1)
        self.assertIs(test_bus._receiver_thread, receiver)
        self.assertTrue(receiver.is_alive())

    def test_concurrent_open_still_opens_backend_once(self):
        """
        @description         : 验证多个线程同时open仍然只有一个后端和接收线程
        @param self          : 当前测试用例
        @return              : 无
        """
        test_bus = self.make_bus()
        threads = [threading.Thread(target=test_bus.open) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(self.backend.open_count, 1)
        self.assertTrue(test_bus._receiver_thread.is_alive())

    def test_raw_send_and_receive(self):
        """
        @description         : 验证原始帧发送与接收的完整路径
        @param self          : 当前测试用例
        @return              : 无
        """
        test_bus = self.make_bus().open()
        outgoing = CanFrame(0x123, b"\x10")
        self.assertIs(test_bus.send_frame(outgoing), outgoing)
        self.assertEqual(self.backend.sent_frames, [outgoing])

        incoming = CanFrame(0x321, b"\x20", timestamp=1.25)
        self.backend.inject(incoming)
        self.assertEqual(test_bus.receive_frame(0.5), incoming)

    def test_named_send_receive_and_raw_copy(self):
        """
        @description         : 验证命名报文编解码且原始队列仍保留同一帧
        @param self          : 当前测试用例
        @return              : 无
        """
        messages = {
            "speed": MessageDefinition(
                0x200,
                direction="tx",
                encode=lambda value: bytes([value]),
            ),
            "status": MessageDefinition(
                0x300,
                direction="rx",
                decode=lambda data: {"value": data[0]},
            ),
        }
        test_bus = self.make_bus(messages=messages).open()
        sent = test_bus.send("speed", value=7)
        self.assertEqual(sent, CanFrame(0x200, b"\x07"))

        received = CanFrame(0x300, b"\x09")
        self.backend.inject(received)
        self.assertEqual(test_bus.receive("status", 0.5), {"value": 9})
        self.assertEqual(test_bus.receive_frame(0.5), received)

    def test_fixed_data_named_send(self):
        """
        @description         : 验证固定DATA命名报文无需参数即可发送
        @param self          : 当前测试用例
        @return              : 无
        """
        messages = {
            "enable": MessageDefinition(
                0x201,
                direction="tx",
                fixed_data=b"\x01\x01",
            )
        }
        test_bus = self.make_bus(messages=messages).open()
        frame = test_bus.send("enable")
        self.assertEqual(frame, CanFrame(0x201, b"\x01\x01"))

    def test_queue_overflow_drops_oldest_and_counts(self):
        """
        @description         : 验证有界队列满时保留最新帧并累计丢帧计数
        @param self          : 当前测试用例
        @return              : 无
        """
        messages = {
            "sample": MessageDefinition(0x100, direction="rx")
        }
        test_bus = self.make_bus(
            messages=messages,
            raw_queue_size=2,
            message_queue_size=2,
        ).open()
        for value in (1, 2, 3):
            self.backend.inject(CanFrame(0x100, bytes([value])))
        self.assertTrue(wait_until(lambda: test_bus.received_frames == 3))

        self.assertEqual(test_bus.receive_frame(0).data, b"\x02")
        self.assertEqual(test_bus.receive_frame(0).data, b"\x03")
        self.assertEqual(test_bus.receive("sample", 0).data, b"\x02")
        self.assertEqual(test_bus.receive("sample", 0).data, b"\x03")
        report = test_bus.describe()
        self.assertEqual(report["dropped_raw_frames"], 1)
        self.assertEqual(report["dropped_message_frames"], 1)
        self.assertEqual(
            report["dropped_message_frames_by_name"]["sample"],
            1,
        )

    def test_named_timeout_and_raw_timeout_have_clear_contracts(self):
        """
        @description         : 验证原始超时返回None而命名超时抛出统一异常
        @param self          : 当前测试用例
        @return              : 无
        """
        messages = {"status": MessageDefinition(0x300, direction="rx")}
        test_bus = self.make_bus(messages=messages).open()
        self.assertIsNone(test_bus.receive_frame(0.01))
        with self.assertRaises(CANTimeoutError):
            test_bus.receive("status", 0.01)

    def test_receiver_error_propagates_to_caller(self):
        """
        @description         : 验证接收线程错误会在公开API中重新抛出
        @param self          : 当前测试用例
        @return              : 无
        """
        test_bus = self.make_bus().open()
        self.backend.inject_error(CANBackendError("injected failure"))
        self.assertTrue(
            wait_until(lambda: test_bus.describe()["receiver_error"] is not None)
        )
        with self.assertRaisesRegex(CANBackendError, "injected failure"):
            test_bus.receive_frame(0)

    def test_unknown_and_wrong_direction_messages_are_rejected(self):
        """
        @description         : 验证未知名称和错误方向不会进入后端
        @param self          : 当前测试用例
        @return              : 无
        """
        messages = {
            "only_rx": MessageDefinition(1, direction="rx"),
            "only_tx": MessageDefinition(2, direction="tx", fixed_data=b""),
        }
        test_bus = self.make_bus(messages=messages).open()
        with self.assertRaises(CANMessageError):
            test_bus.send("missing")
        with self.assertRaises(CANMessageError):
            test_bus.send("only_rx")
        with self.assertRaises(CANMessageError):
            test_bus.receive("only_tx", 0)

    def test_user_codec_errors_are_wrapped_with_message_name(self):
        """
        @description         : 验证用户编解码异常会保留原因并转换成CANMessageError
        @param self          : 当前测试用例
        @return              : 无
        """
        def fail_encode(**values):
            """
            @description         : 为测试主动抛出编码异常
            @param values        : 未使用的编码参数
            @return              : 不返回，始终抛出ValueError
            """
            raise ValueError("bad engineering value")

        def fail_decode(data):
            """
            @description         : 为测试主动抛出解码异常
            @param data          : 未使用的CAN DATA
            @return              : 不返回，始终抛出ValueError
            """
            raise ValueError("bad payload")

        messages = {
            "command": MessageDefinition(
                0x100,
                direction="tx",
                encode=fail_encode,
            ),
            "feedback": MessageDefinition(
                0x101,
                direction="rx",
                decode=fail_decode,
            ),
        }
        test_bus = self.make_bus(messages=messages).open()
        with self.assertRaisesRegex(CANMessageError, "command"):
            test_bus.send("command", value=1)
        self.backend.inject(CanFrame(0x101, b"\x01"))
        with self.assertRaisesRegex(CANMessageError, "feedback"):
            test_bus.receive("feedback", 0.5)

    def test_close_is_idempotent_and_context_manager_does_not_hide_error(self):
        """
        @description         : 验证close幂等且with语句不会吞掉业务异常
        @param self          : 当前测试用例
        @return              : 无
        """
        test_bus = self.make_bus().open()
        test_bus.close()
        test_bus.close()
        self.assertEqual(self.backend.close_count, 1)

        second_backend = FakeBackend()
        with self.assertRaisesRegex(RuntimeError, "business"):
            with CanBus(backend=second_backend, receiver_poll_s=0.01):
                raise RuntimeError("business")
        self.assertEqual(second_backend.close_count, 1)

    def test_concurrent_senders_all_reach_backend(self):
        """
        @description         : 验证多个业务线程可安全共享一个CanBus发送
        @param self          : 当前测试用例
        @return              : 无
        """
        test_bus = self.make_bus().open()
        threads = [
            threading.Thread(
                target=test_bus.send_frame,
                args=(CanFrame(0x120 + index, bytes([index])),),
            )
            for index in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(self.backend.sent_frames), 20)
        self.assertEqual(test_bus.sent_frames, 20)

    def test_close_waits_for_active_send_before_backend_close(self):
        """
        @description         : 验证close等待正在执行的send释放同一把发送锁
        @param self          : 当前测试用例
        @return              : 无
        """
        test_bus = self.make_bus().open()
        self.backend.release_send.clear()
        send_errors = []
        close_errors = []

        def run_send():
            """
            @description         : 在线程中执行一帧可控阻塞发送
            @param               : 无
            @return              : 无
            """
            try:
                test_bus.send_frame(CanFrame(0x123, b"\x01"))
            except Exception as error:
                send_errors.append(error)

        def run_close():
            """
            @description         : 在线程中关闭同一个CanBus并收集异常
            @param               : 无
            @return              : 无
            """
            try:
                test_bus.close()
            except Exception as error:
                close_errors.append(error)

        sender = threading.Thread(target=run_send)
        closer = threading.Thread(target=run_close)
        try:
            sender.start()
            self.assertTrue(self.backend.send_entered.wait(timeout=0.5))
            closer.start()
            self.assertFalse(self.backend.close_called.wait(timeout=0.1))
            self.assertTrue(closer.is_alive())
        finally:
            self.backend.release_send.set()

        sender.join(timeout=1.0)
        closer.join(timeout=1.0)
        self.assertFalse(sender.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertEqual(send_errors, [])
        self.assertEqual(close_errors, [])
        self.assertEqual(
            self.backend.operation_log,
            ["send_finished", "close_called"],
        )

    def test_socketcan_backend_device_must_match_bus_interface(self):
        """
        @description         : 验证CanBus显示接口与SocketCAN实际设备不能错配
        @param self          : 当前测试用例
        @return              : 无
        """
        backend = SocketCANBackend(device="can1")
        with self.assertRaisesRegex(
            CANConfigurationError,
            "device does not match",
        ):
            CanBus(interface="can0", backend=backend)
        self.assertFalse(backend.is_open)

    def test_describe_rx_only_message_has_no_payload_source(self):
        """
        @description         : 验证纯接收报文不会被诊断信息误报为使用encode
        @param self          : 当前测试用例
        @return              : 无
        """
        messages = {
            "status": MessageDefinition(
                0x301,
                direction="rx",
                decode=lambda data: data,
            )
        }
        report = self.make_bus(messages=messages).describe()
        self.assertIsNone(report["messages"]["status"]["payload_source"])
        self.assertTrue(report["messages"]["status"]["has_decode"])


if __name__ == "__main__":
    unittest.main()
