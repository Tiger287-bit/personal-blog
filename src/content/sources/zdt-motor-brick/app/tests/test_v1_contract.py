"""CAN V1 正式契约和数值边界永久回归测试。"""

import inspect
import unittest

from fake_backend import FakeBackend
from zdt_motor import (
    MotorConfig,
    ZDTCanBus,
    ZDTConfigurationError,
    ZDTMotorBus,
)
from zdt_motor.backends import SocketCANBackend
from zdt_motor.commands import common
from zdt_motor.protocols import ZDTCanProtocol


INVALID_TIMEOUTS = (
    True,
    False,
    0,
    -1,
    float("nan"),
    float("inf"),
    float("-inf"),
)


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
        for value in INVALID_TIMEOUTS:
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
            for value in INVALID_TIMEOUTS:
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
        for value in INVALID_TIMEOUTS:
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

    def test_socketcan_receive_rejects_invalid_timeout(self):
        """
        @description         : 验证SocketCAN接收超时使用统一正数校验
        @param               : 无参数
        @return              : 无返回值
        """
        backend = SocketCANBackend()
        for value in INVALID_TIMEOUTS:
            with self.subTest(value=value):
                with self.assertRaises(ZDTConfigurationError):
                    backend.receive(value)

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
