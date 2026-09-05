"""教学can_messages.py中的大小端、符号位和状态位测试。"""

import unittest

from can_messages import (
    MESSAGES,
    decode_motor_status,
    encode_fd_bytes,
    encode_motor_speed,
)


class CustomMessageTests(unittest.TestCase):
    """验证文章可直接讲解的工程值编解码例子。"""

    def test_120_rpm_encodes_as_04_b0(self):
        """
        @description         : 验证120RPM按比例10编码成大端04 B0
        @param self          : 当前测试用例
        @return              : 无
        """
        self.assertEqual(encode_motor_speed(120), b"\x04\xB0")

    def test_negative_speed_uses_signed_big_endian(self):
        """
        @description         : 验证负转速使用16位有符号大端补码
        @param self          : 当前测试用例
        @return              : 无
        """
        self.assertEqual(encode_motor_speed(-1), b"\xFF\xF6")

    def test_status_decodes_flags_and_engineering_value(self):
        """
        @description         : 验证03 04 AF解析为使能、故障和119.9RPM
        @param self          : 当前测试用例
        @return              : 无
        """
        self.assertEqual(
            decode_motor_status(b"\x03\x04\xAF"),
            {"enabled": True, "fault": True, "speed_rpm": 119.9},
        )

    def test_table_contains_standard_extended_and_fd_examples(self):
        """
        @description         : 验证示例表覆盖标准帧、扩展帧和FD+BRS
        @param self          : 当前测试用例
        @return              : 无
        """
        self.assertFalse(MESSAGES["enable"].is_extended)
        self.assertTrue(MESSAGES["extended_ping"].is_extended)
        self.assertTrue(MESSAGES["fd_payload"].is_fd)
        self.assertTrue(MESSAGES["fd_payload"].bitrate_switch)

    def test_fd_example_rejects_integer_text_and_bool_payloads(self):
        """
        @description         : 验证FD示例不会把整数或文本静默转换成零字节
        @param self          : 当前测试用例
        @return              : 无
        """
        self.assertEqual(encode_fd_bytes(b"\x01\x02"), b"\x01\x02")
        self.assertEqual(
            encode_fd_bytes(bytearray([1, 2])),
            b"\x01\x02",
        )
        self.assertEqual(encode_fd_bytes([1, 2]), b"\x01\x02")
        for payload in (2, True, "0102"):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    encode_fd_bytes(payload)


if __name__ == "__main__":
    unittest.main()
