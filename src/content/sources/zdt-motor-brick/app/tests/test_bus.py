"""ZDTBus 请求、异步事件、分包和同步启动测试。"""

import threading
import time
import unittest

from fake_backend import FakeBackend
from zdt_motor import (
    BusKind,
    SocketCanEndpoint,
    ZDTBus,
    ZDTBusBusyError,
    ZDTCanBus,
    ZDTConfigurationError,
    ZDTMotor,
    ZDTMotorBus,
    ZDTProtocolError,
)
from zdt_motor.backends import CanFrame
from zdt_motor.protocols import LogicalCommand, calculate_checksum, split_can_frames


def response_frames(address, function_code, data):
    """
    @description         : 构造固定0x6B校验的测试应答帧
    @param address       : 应答电机地址
    @param function_code : 应答功能码
    @param data          : 应答数据，不含功能码和校验码
    @return              : CanFrame元组
    """
    body = bytes((function_code,)) + bytes(data)
    checksum = calculate_checksum("fixed_6b", address, body)
    return split_can_frames(address, body + bytes((checksum,)))


def wait_until(predicate, timeout_s=0.2):
    """
    @description         : 在测试超时内等待条件成立
    @param predicate     : 返回布尔值的条件函数
    @param timeout_s     : 最大等待秒数
    @return              : 条件是否在超时前成立
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return bool(predicate())


class ExplicitCanBusTests(unittest.TestCase):
    """验证总线种类和系统接口都能被明确读取。"""

    def test_default_can0_endpoint_is_explicit(self):
        """
        @description         : 校验默认对象明确表示CAN和can0接口
        @param               : 无参数
        @return              : 无返回值
        """
        bus = ZDTCanBus(backend=FakeBackend())
        self.assertIsInstance(bus, ZDTMotorBus)
        self.assertEqual(bus.kind, BusKind.CAN)
        self.assertEqual(bus.endpoint.interface, "can0")
        self.assertEqual(bus.endpoint.expected_bitrate, 500_000)
        self.assertEqual(bus.device, "can0")

    def test_named_can_bus_describes_custom_endpoint(self):
        """
        @description         : 校验自定义CAN接口和物理端口信息可用于诊断
        @param               : 无参数
        @return              : 无返回值
        """
        endpoint = SocketCanEndpoint(
            interface="can1",
            expected_bitrate=250_000,
            physical_port="USB-CAN adapter A",
        )
        bus = ZDTCanBus(
            name="motor_can_a",
            endpoint=endpoint,
            backend=FakeBackend(),
        )
        self.assertEqual(
            bus.describe(),
            {
                "name": "motor_can_a",
                "kind": "can",
                "endpoint": {
                    "transport": "socketcan",
                    "owner": "linux",
                    "interface": "can1",
                    "expected_bitrate": 250_000,
                    "physical_port": "USB-CAN adapter A",
                },
                "checksum": "fixed_6b",
                "backend": "FakeBackend",
                "state": "closed",
            },
        )

    def test_legacy_bus_name_and_device_remain_compatible(self):
        """
        @description         : 校验旧ZDTBus名称和device参数仍可继续使用
        @param               : 无参数
        @return              : 无返回值
        """
        bus = ZDTBus(device="can2", backend=FakeBackend())
        self.assertIsInstance(bus, ZDTCanBus)
        self.assertEqual(bus.endpoint.interface, "can2")

    def test_endpoint_and_legacy_device_cannot_be_mixed(self):
        """
        @description         : 校验新旧接口参数同时填写时给出明确配置错误
        @param               : 无参数
        @return              : 无返回值
        """
        with self.assertRaises(ZDTConfigurationError):
            ZDTCanBus(
                endpoint=SocketCanEndpoint(interface="can0"),
                device="can1",
                backend=FakeBackend(),
            )

    def test_endpoint_rejects_invalid_bitrate_metadata(self):
        """
        @description         : 校验期望波特率必须为正整数
        @param               : 无参数
        @return              : 无返回值
        """
        with self.assertRaises(ZDTConfigurationError):
            SocketCanEndpoint(expected_bitrate=0)


class BusLifecycleTests(unittest.TestCase):
    """验证一个接收线程可以稳定服务多个请求和事件。"""

    def test_immediate_ack_completes_request(self):
        """
        @description         : 校验02立即应答完成普通控制请求
        @param               : 无参数
        @return              : 无返回值
        """
        def on_send(frame, backend):
            if frame.data and frame.data[0] == 0xF3:
                for reply in response_frames(1, 0xF3, b"\x02"):
                    backend.queue_frame(reply)

        backend = FakeBackend(on_send=on_send)
        bus = ZDTBus(backend=backend, default_timeout_s=0.1)
        motor = ZDTMotor(bus=bus, motor_id=1, model="X57S", firmware="emm")
        try:
            result = motor.enable()
            self.assertEqual(result["status"], 0x02)
            self.assertEqual(result["status_name"], "received")
        finally:
            bus.close()

    def test_immediate_ack_and_completion_event_are_separated(self):
        """
        @description         : 校验02完成请求而随后9F进入异步事件队列
        @param               : 无参数
        @return              : 无返回值
        """
        replied = False

        def on_send(frame, backend):
            nonlocal replied
            if replied or not frame.data or frame.data[0] != 0xFD:
                return
            replied = True
            for status in (0x02, 0x9F):
                for reply in response_frames(1, 0xFD, bytes((status,))):
                    backend.queue_frame(reply)

        backend = FakeBackend(on_send=on_send)
        bus = ZDTBus(backend=backend, default_timeout_s=0.2)
        motor = ZDTMotor(bus=bus, motor_id=1, model="X57S", firmware="emm")
        try:
            result = motor.move_relative(10, rpm=10)
            event = bus.next_event(timeout_s=0.2)
            self.assertEqual(result["status"], 0x02)
            self.assertIsNotNone(event)
            self.assertEqual(event.data, b"\x9F")
            self.assertTrue(bus.is_open)
        finally:
            bus.close()

    def test_previous_completion_does_not_complete_next_request(self):
        """
        @description         : 校验上一条FD命令的9F不会完成下一条FD请求
        @param               : 无参数
        @return              : 无返回值
        """
        backend = FakeBackend()
        bus = ZDTBus(backend=backend, default_timeout_s=0.3)
        command = LogicalCommand(0xFD, b"", 3, "test position")
        results = []

        def run_request():
            """
            @description         : 在线程中发送FD请求并保存结果
            @param               : 无参数
            @return              : 无返回值
            """
            try:
                results.append(bus.request(1, command))
            except Exception as error:
                results.append(error)

        try:
            first = threading.Thread(target=run_request)
            first.start()
            self.assertTrue(wait_until(lambda: len(backend.sent_frames) >= 1))
            for frame in response_frames(1, 0xFD, b"\x02"):
                backend.queue_frame(frame)
            first.join(0.2)
            self.assertFalse(first.is_alive())
            self.assertEqual(results.pop().data, b"\x02")

            sent_before_second = len(backend.sent_frames)
            second = threading.Thread(target=run_request)
            second.start()
            self.assertTrue(
                wait_until(lambda: len(backend.sent_frames) > sent_before_second)
            )
            for frame in response_frames(1, 0xFD, b"\x9F"):
                backend.queue_frame(frame)
            event = bus.next_event(timeout_s=0.2)
            self.assertIsNotNone(event)
            self.assertEqual(event.data, b"\x9F")
            self.assertTrue(second.is_alive())
            self.assertEqual(results, [])

            for frame in response_frames(1, 0xFD, b"\x02"):
                backend.queue_frame(frame)
            second.join(0.2)
            self.assertFalse(second.is_alive())
            self.assertEqual(results.pop().data, b"\x02")
        finally:
            bus.close()

    def test_repeated_completion_events_keep_receiver_alive(self):
        """
        @description         : 校验连续多个9F事件不会使接收线程退出
        @param               : 无参数
        @return              : 无返回值
        """
        backend = FakeBackend()
        bus = ZDTBus(backend=backend, default_timeout_s=0.1)
        try:
            bus.open()
            for _ in range(20):
                for frame in response_frames(1, 0xFD, b"\x9F"):
                    backend.queue_frame(frame)
            events = [bus.next_event(timeout_s=0.2) for _ in range(20)]
            self.assertTrue(all(event is not None for event in events))
            self.assertTrue(bus.is_open)
            self.assertIsNone(bus._receiver_error)
        finally:
            bus.close()

    def test_single_byte_read_value_9f_is_not_completion_event(self):
        """
        @description         : 校验3A读取值9F仍完成普通请求且不进入事件队列
        @param               : 无参数
        @return              : 无返回值
        """
        def on_send(frame, backend):
            if frame.data and frame.data[0] == 0x3A:
                for reply in response_frames(1, 0x3A, b"\x9F"):
                    backend.queue_frame(reply)

        backend = FakeBackend(on_send=on_send)
        bus = ZDTBus(backend=backend, default_timeout_s=0.1)
        try:
            response = bus.request(
                1,
                LogicalCommand(0x3A, b"", 3, "read motor status"),
            )
            self.assertEqual(response.function_code, 0x3A)
            self.assertEqual(response.data, b"\x9F")
            self.assertIsNone(bus.next_event())
            self.assertTrue(bus.is_open)
            self.assertIsNone(bus._receiver_error)
        finally:
            bus.close()

    def test_duplicate_immediate_ack_does_not_kill_receiver(self):
        """
        @description         : 校验重复02应答队列已满时接收线程仍可继续请求
        @param               : 无参数
        @return              : 无返回值
        """
        send_count = 0
        queue_full_observed = threading.Event()

        def on_send(frame, backend):
            nonlocal send_count
            if not frame.data or frame.data[0] != 0xF3:
                return
            send_count += 1
            reply_count = 2 if send_count == 1 else 1
            for _ in range(reply_count):
                for reply in response_frames(1, 0xF3, b"\x02"):
                    backend.queue_frame(reply)
            if send_count == 1:
                self.assertTrue(queue_full_observed.wait(0.2))

        backend = FakeBackend(on_send=on_send)
        bus = ZDTBus(backend=backend, default_timeout_s=0.2)
        command = LogicalCommand(0xF3, b"\xAB\x01\x00", 3, "enable motor")
        original_put = bus._put_pending_result

        def tracking_put(pending, result):
            """
            @description         : 记录重复应答确实触发请求结果队列已满分支
            @param pending       : 当前等待请求
            @param result        : 待投递响应
            @return              : 原投递函数结果
            """
            delivered = original_put(pending, result)
            if not delivered:
                queue_full_observed.set()
            return delivered

        bus._put_pending_result = tracking_put
        try:
            first = bus.request(1, command)
            self.assertEqual(first.data, b"\x02")
            self.assertTrue(queue_full_observed.is_set())
            self.assertTrue(bus.is_open)
            self.assertIsNone(bus._receiver_error)

            second = bus.request(1, command)
            self.assertEqual(second.data, b"\x02")
            self.assertTrue(bus.is_open)
            self.assertIsNone(bus._receiver_error)
        finally:
            bus.close()

    def test_same_function_from_two_motors_is_dispatched_by_address(self):
        """
        @description         : 校验两台电机同时返回35时按地址分别投递
        @param               : 无参数
        @return              : 无返回值
        """
        def on_send(frame, backend):
            address = (frame.arbitration_id >> 8) & 0xFF
            if frame.data and frame.data[0] == 0x35:
                speed_data = b"\x00\x00\x0A" if address == 1 else b"\x01\x00\x14"
                for reply in response_frames(address, 0x35, speed_data):
                    backend.queue_frame(reply)

        backend = FakeBackend(on_send=on_send)
        bus = ZDTBus(backend=backend, default_timeout_s=0.2)
        motors = {
            motor_id: ZDTMotor(
                bus=bus,
                motor_id=motor_id,
                model="X57S",
                firmware="emm",
            )
            for motor_id in (1, 2)
        }
        speeds = {}

        def read_speed(motor_id):
            """
            @description         : 在线程中读取指定电机速度
            @param motor_id      : 电机地址
            @return              : 无返回值
            """
            speeds[motor_id] = motors[motor_id].get_speed()

        try:
            workers = [
                threading.Thread(target=read_speed, args=(motor_id,))
                for motor_id in (1, 2)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(0.3)
            self.assertEqual(speeds, {1: 10.0, 2: -20.0})
            self.assertTrue(bus.is_open)
        finally:
            bus.close()

    def test_duplicate_pending_key_is_rejected(self):
        """
        @description         : 校验同地址同功能码同时请求时抛出BusBusy错误
        @param               : 无参数
        @return              : 无返回值
        """
        backend = FakeBackend()
        bus = ZDTBus(backend=backend, default_timeout_s=0.3)
        command = LogicalCommand(0x35, b"", 5, "read speed")
        first_result = []

        def first_request():
            """
            @description         : 创建保持等待状态的第一个请求
            @param               : 无参数
            @return              : 无返回值
            """
            try:
                first_result.append(bus.request(1, command))
            except Exception as error:
                first_result.append(error)

        try:
            worker = threading.Thread(target=first_request)
            worker.start()
            self.assertTrue(wait_until(lambda: len(backend.sent_frames) == 1))
            with self.assertRaises(ZDTBusBusyError):
                bus.request(1, command)
            for frame in response_frames(1, 0x35, b"\x00\x00\x0A"):
                backend.queue_frame(frame)
            worker.join(0.2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(first_result[0].data, b"\x00\x00\x0A")
        finally:
            bus.close()

    def test_long_response_reassembles_packet_zero_and_one(self):
        """
        @description         : 校验长应答的第0包和第1包能够正常重组
        @param               : 无参数
        @return              : 无返回值
        """
        data = bytes.fromhex("00 01 02 03 04 05 06 07")

        def on_send(frame, backend):
            for reply in response_frames(1, 0x36, data):
                backend.queue_frame(reply)

        backend = FakeBackend(on_send=on_send)
        bus = ZDTBus(backend=backend, default_timeout_s=0.2)
        try:
            response = bus.request(1, LogicalCommand(0x36, b"", 10))
            self.assertEqual(response.data, data)
            self.assertTrue(bus.is_open)
        finally:
            bus.close()

    def test_bad_packet_sequence_fails_request_but_not_receiver(self):
        """
        @description         : 校验0包后收到2包会报协议错误但接收线程继续运行
        @param               : 无参数
        @return              : 无返回值
        """
        backend = FakeBackend()
        bus = ZDTBus(backend=backend, default_timeout_s=0.2)
        command = LogicalCommand(0x36, b"", 10)
        result = []

        def run_request():
            """
            @description         : 在线程中执行等待长应答的请求
            @param               : 无参数
            @return              : 无返回值
            """
            try:
                result.append(bus.request(1, command))
            except Exception as error:
                result.append(error)

        try:
            worker = threading.Thread(target=run_request)
            worker.start()
            self.assertTrue(wait_until(lambda: len(backend.sent_frames) == 1))
            frames = response_frames(1, 0x36, bytes(range(8)))
            backend.queue_frame(frames[0])
            backend.queue_frame(
                CanFrame(
                    arbitration_id=(1 << 8) | 2,
                    data=frames[1].data,
                    is_extended=True,
                )
            )
            worker.join(0.2)
            self.assertFalse(worker.is_alive())
            self.assertIsInstance(result[0], ZDTProtocolError)
            self.assertTrue(bus.is_open)
            self.assertIsInstance(bus.last_protocol_error, ZDTProtocolError)

            result.clear()
            worker = threading.Thread(target=run_request)
            worker.start()
            self.assertTrue(wait_until(lambda: len(backend.sent_frames) == 2))
            for frame in frames:
                backend.queue_frame(frame)
            worker.join(0.2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result[0].data, bytes(range(8)))
        finally:
            bus.close()

    def test_short_response_fails_request_without_stopping_receiver(self):
        """
        @description         : 校验可识别的短应答立即返回协议错误且线程继续工作
        @param               : 无参数
        @return              : 无返回值
        """
        send_count = 0

        def on_send(frame, backend):
            nonlocal send_count
            if not frame.data or frame.data[0] != 0x35:
                return
            send_count += 1
            data = b"\x00" if send_count == 1 else b"\x00\x00\x0A"
            for reply in response_frames(1, 0x35, data):
                backend.queue_frame(reply)

        backend = FakeBackend(on_send=on_send)
        bus = ZDTBus(backend=backend, default_timeout_s=0.2)
        command = LogicalCommand(0x35, b"", 5, "read speed")
        try:
            with self.assertRaises(ZDTProtocolError):
                bus.request(1, command)
            self.assertIsInstance(bus.last_protocol_error, ZDTProtocolError)
            self.assertTrue(bus.is_open)

            response = bus.request(1, command)
            self.assertEqual(response.data, b"\x00\x00\x0A")
            self.assertTrue(bus.is_open)
            self.assertIsNone(bus._receiver_error)
        finally:
            bus.close()

    def test_start_synchronized_sends_broadcast_without_waiting(self):
        """
        @description         : 校验同步启动使用广播地址0发送FF 66 6B且不等待应答
        @param               : 无参数
        @return              : 无返回值
        """
        backend = FakeBackend()
        bus = ZDTBus(backend=backend, default_timeout_s=0.1)
        try:
            result = bus.start_synchronized()
            self.assertIsNone(result)
            self.assertEqual(len(backend.sent_frames), 1)
            self.assertEqual(backend.sent_frames[0].arbitration_id, 0x0000)
            self.assertTrue(backend.sent_frames[0].is_extended)
            self.assertEqual(backend.sent_frames[0].data, bytes.fromhex("FF 66 6B"))
            self.assertTrue(bus.is_open)
        finally:
            bus.close()


if __name__ == "__main__":
    unittest.main()
