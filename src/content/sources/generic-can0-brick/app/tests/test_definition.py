"""MessageDefinition静态约束测试。"""

import unittest

from generic_can import CANConfigurationError, MessageDefinition


class MessageDefinitionTests(unittest.TestCase):
    """验证命名报文方向与编解码字段的组合规则。"""

    def test_valid_tx_rx_and_both_definitions(self):
        """
        @description         : 验证三种方向的最小合法定义
        @param self          : 当前测试用例
        @return              : 无
        """
        tx = MessageDefinition(1, direction="tx", fixed_data=b"\x01")
        rx = MessageDefinition(2, direction="rx", decode=lambda data: data)
        both = MessageDefinition(3, direction="both", encode=bytes)
        self.assertTrue(tx.allows_tx)
        self.assertFalse(tx.allows_rx)
        self.assertTrue(rx.allows_rx)
        self.assertTrue(both.allows_tx)
        self.assertTrue(both.allows_rx)

    def test_rejects_conflicting_or_missing_payload_source(self):
        """
        @description         : 验证发送定义必须且只能选择一种DATA来源
        @param self          : 当前测试用例
        @return              : 无
        """
        with self.assertRaises(CANConfigurationError):
            MessageDefinition(1, direction="tx")
        with self.assertRaises(CANConfigurationError):
            MessageDefinition(
                1,
                direction="tx",
                fixed_data=b"\x01",
                encode=bytes,
            )
        with self.assertRaises(CANConfigurationError):
            MessageDefinition(1, direction="tx", fixed_data=2)

    def test_rejects_direction_specific_misuse(self):
        """
        @description         : 验证只收和只发定义不能配置反方向处理函数
        @param self          : 当前测试用例
        @return              : 无
        """
        with self.assertRaises(CANConfigurationError):
            MessageDefinition(1, direction="rx", fixed_data=b"\x01")
        with self.assertRaises(CANConfigurationError):
            MessageDefinition(
                1,
                direction="tx",
                fixed_data=b"\x01",
                decode=bytes,
            )

    def test_match_key_includes_frame_format(self):
        """
        @description         : 验证相同ID的标准帧、扩展帧和FD帧不会混配
        @param self          : 当前测试用例
        @return              : 无
        """
        definition = MessageDefinition(
            0x123,
            direction="rx",
            is_extended=True,
            is_fd=True,
        )
        self.assertEqual(definition.match_key(), (0x123, True, True))


if __name__ == "__main__":
    unittest.main()
