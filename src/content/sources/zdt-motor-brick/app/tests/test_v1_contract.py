"""CAN V1 正式契约和数值边界永久回归测试。"""

import inspect
import threading
import time
import unittest

import zdt_motor
from fake_backend import FakeBackend
from zdt_motor import (
    MotorConfig,
    ZDTCanBus,
    ZDTConfigurationError,
    ZDTMotor,
    ZDTMotorBus,
)
from zdt_motor.backends import SocketCANBackend
from zdt_motor.commands import common, emm, x
from zdt_motor.config import validate_number
from zdt_motor.protocols import ZDTCanProtocol


INVALID_REQUEST_TIMEOUTS = (
    True,
    False,
    0,
    -1,
    float("nan"),
    float("inf"),
    float("-inf"),
)

INVALID_POLL_TIMEOUTS = (
    True,
    False,
    -1,
    float("nan"),
    float("inf"),
    float("-inf"),
)

INVALID_BOOLEAN_VALUES = (
    "False",
    0,
    1,
    None,
    [],
    {},
)

EXPECTED_PUBLIC_API = {
    "BusKind",
    "BusTrace",
    "ChecksumType",
    "Direction",
    "EndpointOwner",
    "Firmware",
    "HomeMode",
    "MotionMode",
    "MotorConfig",
    "SocketCanEndpoint",
    "ZDTBackendError",
    "ZDTBus",
    "ZDTBusBusyError",
    "ZDTCanBus",
    "ZDTCommandError",
    "ZDTConfigurationError",
    "ZDTError",
    "ZDTFormatError",
    "ZDTMotor",
    "ZDTMotorBus",
    "ZDTParameterError",
    "ZDTProtocolError",
    "ZDTTimeoutError",
    "ZDTUnsupportedFeatureError",
}


class FakeSocketReceiveBus:
    """记录 SocketCAN receive 传入的轮询等待时间。"""

    def __init__(self):
        """
        @description         : 初始化最近一次接收等待时间
        @param               : 无参数
        @return              : 无返回值
        """
        self.last_timeout = None

    def recv(self, *, timeout):
        """
        @description         : 记录等待时间并模拟当前没有CAN帧
        @param timeout       : SocketCAN接收等待秒数
        @return              : None
        """
        self.last_timeout = timeout
        return None


class SlowOpenBackend(FakeBackend):
    """放大并发首次打开窗口并记录实际打开次数。"""

    def __init__(self):
        """
        @description         : 初始化线程安全的Backend打开计数
        @param               : 无参数
        @return              : 无返回值
        """
        super().__init__()
        self.open_count = 0
        self._count_lock = threading.Lock()

    def open(self):
        """
        @description         : 记录打开次数并延长首次打开窗口
        @param               : 无参数
        @return              : 当前Backend
        """
        with self._count_lock:
            self.open_count += 1
        time.sleep(0.02)
        self.opened = True
        return self

    def receive(self, timeout_s):
        """
        @description         : 短暂等待并模拟当前没有CAN帧
        @param timeout_s     : 最大等待秒数
        @return              : None
        """
        time.sleep(min(float(timeout_s), 0.005))
        return None


class V1ContractTests(unittest.TestCase):
    """验证 CAN V1 冻结后的正式接口和参数语义。"""

    def test_motor_bus_request_contract_has_explicit_parameters(self):
        """
        @description         : 验证ZDTMotorBus请求契约显式声明可选参数
        @param               : 无参数
        @return              : 无返回值
        """
        parameters = inspect.signature(ZDTMotorBus.request).parameters
        self.assertEqual(
            tuple(parameters),
            ("self", "address", "command", "timeout_s", "response_address"),
        )
        self.assertIsNone(parameters["timeout_s"].default)
        self.assertIsNone(parameters["response_address"].default)
        self.assertEqual(
            parameters["timeout_s"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        self.assertEqual(
            parameters["response_address"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )

    def test_concurrent_open_starts_single_receiver(self):
        """
        @description         : 验证多个线程同时首次打开只启动一个Backend和接收线程
        @param               : 无参数
        @return              : 无返回值
        """
        backend = SlowOpenBackend()
        bus = ZDTCanBus(backend=backend)
        worker_count = 8
        barrier = threading.Barrier(worker_count)
        errors = []

        def open_bus():
            """
            @description         : 等待所有测试线程就绪后同时打开共享Bus
            @param               : 无参数
            @return              : 无返回值
            """
            try:
                barrier.wait()
                bus.open()
            except Exception as error:
                errors.append(error)

        workers = [
            threading.Thread(target=open_bus)
            for _ in range(worker_count)
        ]
        try:
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=2.0)

            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(errors, [])
            self.assertEqual(backend.open_count, 1)
            self.assertTrue(bus.is_open)
            receiver = bus._receiver_thread
            self.assertIsNotNone(receiver)
            self.assertTrue(receiver.is_alive())
        finally:
            bus.close()

    def test_default_timeout_rejects_invalid_values(self):
        """
        @description         : 验证默认超时拒绝布尔值、非有限值和非正数
        @param               : 无参数
        @return              : 无返回值
        """
        for value in INVALID_REQUEST_TIMEOUTS:
            with self.subTest(value=value):
                with self.assertRaises(ZDTConfigurationError):
                    ZDTCanBus(
                        backend=FakeBackend(),
                        default_timeout_s=value,
                    )

    def test_default_timeout_accepts_valid_numbers(self):
        """
        @description         : 验证有效默认超时统一保存为浮点数
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertEqual(
            ZDTCanBus(backend=FakeBackend(), default_timeout_s=1).default_timeout_s,
            1.0,
        )
        self.assertEqual(
            ZDTCanBus(
                backend=FakeBackend(),
                default_timeout_s=0.5,
            ).default_timeout_s,
            0.5,
        )

    def test_request_timeout_rejects_invalid_values(self):
        """
        @description         : 验证单次请求超时统一抛出配置错误
        @param               : 无参数
        @return              : 无返回值
        """
        bus = ZDTCanBus(backend=FakeBackend())
        command = common.build_read_speed()
        try:
            for value in INVALID_REQUEST_TIMEOUTS:
                with self.subTest(value=value):
                    with self.assertRaises(ZDTConfigurationError):
                        bus.request(1, command, timeout_s=value)
        finally:
            bus.close()

    def test_empty_response_address_collection_is_configuration_error(self):
        """
        @description         : 验证空应答地址集合在打开Backend和发送CAN前被拒绝
        @param               : 无参数
        @return              : 无返回值
        """
        backend = FakeBackend()
        bus = ZDTCanBus(backend=backend)
        command = common.build_read_speed()
        for value in ((), [], set(), frozenset()):
            with self.subTest(value=value):
                with self.assertRaises(ZDTConfigurationError):
                    bus.request(1, command, response_address=value)
                self.assertFalse(backend.opened)
                self.assertEqual(backend.sent_frames, [])

    def test_motor_config_timeout_rejects_invalid_values(self):
        """
        @description         : 验证电机配置超时拒绝所有非法数值
        @param               : 无参数
        @return              : 无返回值
        """
        for value in INVALID_REQUEST_TIMEOUTS:
            with self.subTest(value=value):
                with self.assertRaises(ZDTConfigurationError):
                    MotorConfig(timeout_s=value)

    def test_socketcan_backend_normalizes_device(self):
        """
        @description         : 验证SocketCAN Backend去除设备名首尾空格
        @param               : 无参数
        @return              : 无返回值
        """
        backend = SocketCANBackend(device="  can0  ")
        self.assertEqual(backend.device, "can0")

    def test_socketcan_backend_rejects_empty_device(self):
        """
        @description         : 验证SocketCAN Backend拒绝空设备名
        @param               : 无参数
        @return              : 无返回值
        """
        for device in ("", "   "):
            with self.subTest(device=device):
                with self.assertRaises(ZDTConfigurationError):
                    SocketCANBackend(device)

    def test_enable_rejects_non_boolean_enabled(self):
        """
        @description         : 验证使能命令拒绝字符串形式的False
        @param               : 无参数
        @return              : 无返回值
        """
        with self.assertRaises(ZDTConfigurationError):
            common.build_enable(enabled="False")

    def test_synchronized_rejects_non_boolean_values(self):
        """
        @description         : 验证所有同步控制命令拒绝非布尔配置值
        @param               : 无参数
        @return              : 无返回值
        """
        cases = (
            ("enable", common.build_enable, (), {"enabled": True}),
            ("stop", common.build_stop, (), {}),
            ("home", common.build_home, (), {}),
            ("emm_speed", emm.build_speed, (10,), {}),
            ("emm_position", emm.build_position, (10,), {"rpm": 10}),
            ("x_speed", x.build_speed, (10,), {}),
            ("x_position", x.build_position, (10,), {"rpm": 10}),
        )
        for value in INVALID_BOOLEAN_VALUES:
            for name, builder, args, base_kwargs in cases:
                with self.subTest(value=value, command=name):
                    kwargs = dict(base_kwargs)
                    kwargs["synchronized"] = value
                    with self.assertRaises(ZDTConfigurationError):
                        builder(*args, **kwargs)

    def test_store_rejects_non_boolean_values(self):
        """
        @description         : 验证所有Flash存储配置命令拒绝非布尔值
        @param               : 无参数
        @return              : 无返回值
        """
        cases = (
            (common.build_set_motor_id, (2,), {"store": "False"}),
            (common.build_set_microstep, (16,), {"store": 1}),
            (common.build_set_current_limit, (1000,), {"store": None}),
            (common.build_set_direction, ("cw",), {"store": "yes"}),
        )
        for builder, args, kwargs in cases:
            with self.subTest(command=builder.__name__):
                with self.assertRaises(ZDTConfigurationError):
                    builder(*args, **kwargs)

    def test_valid_boolean_values_keep_protocol_encoding(self):
        """
        @description         : 验证合法True和False仍编码为协议01和00
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertEqual(
            common.build_enable(True, synchronized=False).payload,
            bytes.fromhex("AB 01 00"),
        )
        self.assertEqual(
            common.build_enable(False, synchronized=True).payload,
            bytes.fromhex("AB 00 01"),
        )
        self.assertEqual(
            common.build_set_motor_id(2, store=True).payload,
            bytes.fromhex("4B 01 02"),
        )
        self.assertEqual(
            common.build_set_motor_id(2, store=False).payload,
            bytes.fromhex("4B 00 02"),
        )

    def test_socketcan_receive_own_messages_requires_bool(self):
        """
        @description         : 验证SocketCAN回环配置只接受真正的布尔值
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertIs(
            SocketCANBackend(receive_own_messages=True).receive_own_messages,
            True,
        )
        self.assertIs(
            SocketCANBackend(receive_own_messages=False).receive_own_messages,
            False,
        )
        for value in ("False", 0, 1, None):
            with self.subTest(value=value):
                with self.assertRaises(ZDTConfigurationError):
                    SocketCANBackend(receive_own_messages=value)

    def test_backend_receive_allows_zero_timeout(self):
        """
        @description         : 验证SocketCAN接收允许0秒非阻塞轮询
        @param               : 无参数
        @return              : 无返回值
        """
        backend = SocketCANBackend()
        fake_bus = FakeSocketReceiveBus()
        backend._bus = fake_bus
        self.assertIsNone(backend.receive(0))
        self.assertEqual(fake_bus.last_timeout, 0.0)

    def test_backend_receive_rejects_negative_and_nonfinite_timeout(self):
        """
        @description         : 验证SocketCAN接收拒绝负数布尔值和非有限等待时间
        @param               : 无参数
        @return              : 无返回值
        """
        backend = SocketCANBackend()
        for value in INVALID_POLL_TIMEOUTS:
            with self.subTest(value=value):
                with self.assertRaises(ZDTConfigurationError):
                    backend.receive(value)

    def test_next_event_allows_zero_timeout(self):
        """
        @description         : 验证事件轮询允许0秒立即检查
        @param               : 无参数
        @return              : 无返回值
        """
        bus = ZDTCanBus(backend=FakeBackend())
        self.assertIsNone(bus.next_event(0))

    def test_next_event_rejects_invalid_timeout(self):
        """
        @description         : 验证事件轮询拒绝负数布尔值和非有限等待时间
        @param               : 无参数
        @return              : 无返回值
        """
        bus = ZDTCanBus(backend=FakeBackend())
        for value in INVALID_POLL_TIMEOUTS:
            with self.subTest(value=value):
                with self.assertRaises(ZDTConfigurationError):
                    bus.next_event(value)

    def test_validate_number_rejects_nonfinite_values(self):
        """
        @description         : 验证工程数值校验拒绝NaN和正负无穷
        @param               : 无参数
        @return              : 无返回值
        """
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ZDTConfigurationError):
                    validate_number("value", value, 0, 100)

    def test_motor_speed_rejects_nan_before_send(self):
        """
        @description         : 验证Emm速度NaN在发送CAN前被拒绝
        @param               : 无参数
        @return              : 无返回值
        """
        backend = FakeBackend()
        bus = ZDTCanBus(backend=backend)
        motor = ZDTMotor(bus=bus, motor_id=1, firmware="emm")
        with self.assertRaises(ZDTConfigurationError):
            motor.set_speed(float("nan"))
        self.assertEqual(backend.sent_frames, [])

    def test_motor_position_rejects_nan_before_send(self):
        """
        @description         : 验证Emm相对和绝对位置NaN在发送CAN前被拒绝
        @param               : 无参数
        @return              : 无返回值
        """
        backend = FakeBackend()
        bus = ZDTCanBus(backend=backend)
        motor = ZDTMotor(bus=bus, motor_id=1, firmware="emm")
        for move in (motor.move_relative, motor.move_absolute):
            with self.subTest(method=move.__name__):
                with self.assertRaises(ZDTConfigurationError):
                    move(float("nan"))
                self.assertEqual(backend.sent_frames, [])

    def test_x_motion_rejects_infinity_before_send(self):
        """
        @description         : 验证X固件速度和位置无穷值在发送CAN前被拒绝
        @param               : 无参数
        @return              : 无返回值
        """
        backend = FakeBackend()
        bus = ZDTCanBus(backend=backend)
        motor = ZDTMotor(bus=bus, motor_id=1, firmware="x")
        with self.assertRaises(ZDTConfigurationError):
            motor.set_speed(float("inf"))
        with self.assertRaises(ZDTConfigurationError):
            motor.move_relative(10, rpm=float("inf"))
        with self.assertRaises(ZDTConfigurationError):
            motor.move_relative(float("inf"))
        with self.assertRaises(ZDTConfigurationError):
            motor.move_absolute(float("inf"))
        self.assertEqual(backend.sent_frames, [])

    def test_public_api_matches_documented_v1_exports(self):
        """
        @description         : 验证顶层导出与README声明的CAN V1公共API完全一致
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertEqual(set(zdt_motor.__all__), EXPECTED_PUBLIC_API)

    def test_zdt_response_raw_semantics(self):
        """
        @description         : 验证raw只保存功能码、数据和校验码组成的逻辑应答体
        @param               : 无参数
        @return              : 无返回值
        """
        logical_response = bytes.fromhex("35 00 00 00 6B")
        response = ZDTCanProtocol().validate_response(1, logical_response)
        self.assertEqual(response.function_code, 0x35)
        self.assertEqual(response.data, bytes.fromhex("00 00 00"))
        self.assertEqual(response.raw, logical_response)
        self.assertEqual(len(response.raw), 5)


if __name__ == "__main__":
    unittest.main()
