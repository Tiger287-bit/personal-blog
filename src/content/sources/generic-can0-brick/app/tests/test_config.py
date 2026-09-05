"""SocketCAN接口名、超时和队列容量参数测试。"""

import math
import unittest

from generic_can import CANConfigurationError
from generic_can.config import (
    validate_device,
    validate_queue_size,
    validate_timeout,
)


class ConfigurationTests(unittest.TestCase):
    """验证V1公共配置入口具有一致的错误类型。"""

    def test_device_is_stripped_and_not_fixed_to_can0(self):
        """
        @description         : 验证接口名去除首尾空白且支持can0以外名称
        @param self          : 当前测试用例
        @return              : 无
        """
        self.assertEqual(validate_device("  can7  "), "can7")
        self.assertEqual(validate_device("vcan0"), "vcan0")

    def test_empty_or_invalid_device_is_rejected(self):
        """
        @description         : 验证空接口名和包含路径分隔符的名称会被拒绝
        @param self          : 当前测试用例
        @return              : 无
        """
        for value in ("", "  ", "can 0", "can/0", None):
            with self.subTest(value=value):
                with self.assertRaises(CANConfigurationError):
                    validate_device(value)

    def test_zero_timeout_is_legal(self):
        """
        @description         : 验证零秒表示非阻塞立即检查
        @param self          : 当前测试用例
        @return              : 无
        """
        self.assertEqual(validate_timeout(0), 0.0)

    def test_invalid_timeouts_use_configuration_error(self):
        """
        @description         : 验证负数、布尔值、NaN和无穷超时统一被拒绝
        @param self          : 当前测试用例
        @return              : 无
        """
        for value in (-1, True, False, math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(CANConfigurationError):
                    validate_timeout(value)

    def test_queue_size_requires_positive_integer(self):
        """
        @description         : 验证队列容量必须是严格正整数
        @param self          : 当前测试用例
        @return              : 无
        """
        self.assertEqual(validate_queue_size(1, "size"), 1)
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(CANConfigurationError):
                    validate_queue_size(value, "size")


if __name__ == "__main__":
    unittest.main()

