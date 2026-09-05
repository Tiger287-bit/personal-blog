"""CanFrame边界和数据规范化测试。"""

import unittest

from generic_can import CANConfigurationError, CanFrame


class CanFrameTests(unittest.TestCase):
    """验证标准帧、扩展帧、Classical CAN和CAN FD边界。"""

    def test_classical_and_extended_boundaries(self):
        """
        @description         : 验证标准ID和扩展ID的最大合法值
        @param self          : 当前测试用例
        @return              : 无
        """
        self.assertEqual(CanFrame(0x7FF).arbitration_id, 0x7FF)
        self.assertEqual(
            CanFrame(0x1FFFFFFF, is_extended=True).arbitration_id,
            0x1FFFFFFF,
        )

    def test_rejects_invalid_identifiers(self):
        """
        @description         : 验证越界ID和布尔ID会被拒绝
        @param self          : 当前测试用例
        @return              : 无
        """
        for arguments in (
            {"arbitration_id": -1},
            {"arbitration_id": 0x800},
            {"arbitration_id": 0x20000000, "is_extended": True},
            {"arbitration_id": True},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(CANConfigurationError):
                    CanFrame(**arguments)

    def test_classical_can_accepts_at_most_eight_bytes(self):
        """
        @description         : 验证Classical CAN DATA长度上限为8字节
        @param self          : 当前测试用例
        @return              : 无
        """
        self.assertEqual(len(CanFrame(1, range(8)).data), 8)
        with self.assertRaises(CANConfigurationError):
            CanFrame(1, range(9))

    def test_can_fd_accepts_at_most_sixty_four_bytes(self):
        """
        @description         : 验证CAN FD DATA长度上限和BRS约束
        @param self          : 当前测试用例
        @return              : 无
        """
        frame = CanFrame(1, range(64), is_fd=True, bitrate_switch=True)
        self.assertEqual(len(frame.data), 64)
        with self.assertRaises(CANConfigurationError):
            CanFrame(1, bytes(65), is_fd=True)
        with self.assertRaises(CANConfigurationError):
            CanFrame(1, bitrate_switch=True)

    def test_can_fd_accepts_only_valid_dlc_payload_lengths(self):
        """
        @description         : 验证CAN FD只接受能够直接对应DLC的DATA长度
        @param self          : 当前测试用例
        @return              : 无
        """
        valid_lengths = (
            0,
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            12,
            16,
            20,
            24,
            32,
            48,
            64,
        )
        for length in valid_lengths:
            with self.subTest(length=length):
                self.assertEqual(
                    len(CanFrame(1, bytes(length), is_fd=True).data),
                    length,
                )

    def test_can_fd_rejects_non_dlc_payload_lengths(self):
        """
        @description         : 验证CAN FD拒绝不能直接对应DLC的DATA长度
        @param self          : 当前测试用例
        @return              : 无
        """
        invalid_lengths = (9, 10, 11, 13, 15, 17, 31, 33, 47, 49, 63, 65)
        for length in invalid_lengths:
            with self.subTest(length=length):
                with self.assertRaises(CANConfigurationError):
                    CanFrame(1, bytes(length), is_fd=True)

    def test_normalizes_mutable_payload(self):
        """
        @description         : 验证可变字节序列会被复制成不可变bytes
        @param self          : 当前测试用例
        @return              : 无
        """
        source = bytearray([1, 2])
        frame = CanFrame(1, source)
        source[0] = 9
        self.assertEqual(frame.data, b"\x01\x02")

    def test_rejects_text_and_integer_payloads(self):
        """
        @description         : 验证字符串和整数不会被意外转换成CAN DATA
        @param self          : 当前测试用例
        @return              : 无
        """
        for value in ("01 02", 2, True):
            with self.subTest(value=value):
                with self.assertRaises(CANConfigurationError):
                    CanFrame(1, value)


if __name__ == "__main__":
    unittest.main()
