"""CAN V1 正式契约和数值边界永久回归测试。"""

import inspect
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
from zdt_motor.commands import common
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
