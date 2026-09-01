"""ZDT 手册校验算法测试。"""

import unittest

from zdt_motor import ChecksumType
from zdt_motor.protocols import CRC8_TABLE, calculate_checksum, crc8_checksum


class ChecksumTests(unittest.TestCase):
    """校验 fixed 0x6B、XOR 和手册 CRC8。"""

    def test_fixed_6b(self):
        """
        @description         : 固定校验始终返回0x6B
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertEqual(
            calculate_checksum(ChecksumType.FIXED_6B, 1, b"\x06\x45"),
            0x6B,
        )

    def test_xor_manual_example(self):
        """
        @description         : 校验手册01 06 45逐字节异或结果
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertEqual(calculate_checksum("xor", 1, b"\x06\x45"), 0x42)

    def test_crc8_manual_table_example(self):
        """
        @description         : 校验手册查表算法处理01 06 45得到0x17
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertEqual(crc8_checksum(b"\x01\x06\x45"), 0x17)
        self.assertEqual(calculate_checksum("crc8", 1, b"\x06\x45"), 0x17)

    def test_crc8_table_is_complete(self):
        """
        @description         : 防止手册256项CRC8表被截断
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertEqual(len(CRC8_TABLE), 256)
        self.assertEqual(CRC8_TABLE[:8], (0x00, 0x5E, 0xBC, 0xE2, 0x61, 0x3F, 0xDD, 0x83))
        self.assertEqual(CRC8_TABLE[-8:], (0xB6, 0xE8, 0x0A, 0x54, 0xD7, 0x89, 0x6B, 0x35))


if __name__ == "__main__":
    unittest.main()
