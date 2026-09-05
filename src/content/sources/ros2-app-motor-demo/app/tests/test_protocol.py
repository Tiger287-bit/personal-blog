"""ZDT CAN 扩展 ID、分包和应答校验测试。"""

import unittest

from zdt_motor import ZDTProtocolError
from zdt_motor.backends import CanFrame
from zdt_motor.messages import LogicalCommand
from zdt_motor.protocols import (
    ZDTCanProtocol,
    arbitration_id,
    parse_arbitration_id,
    reassemble_can_frames,
    split_can_frames,
)


class ProtocolTests(unittest.TestCase):
    """逐字节验证手册第4章 CAN 规则。"""

    def test_extended_id_generation(self):
        """
        @description         : 校验地址和分包号生成扩展CAN ID
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertEqual(arbitration_id(1, 0), 0x0100)
        self.assertEqual(arbitration_id(4, 2), 0x0402)
        self.assertEqual(parse_arbitration_id(0x0402), (4, 2))

    def test_single_frame_omits_address(self):
        """
        @description         : 校验串口01 36 6B在CAN中变成ID0100和DATA36 6B
        @param               : 无参数
        @return              : 无返回值
        """
        frames = ZDTCanProtocol().encode_command(1, LogicalCommand(0x36, b"", 7))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].arbitration_id, 0x0100)
        self.assertTrue(frames[0].is_extended)
        self.assertEqual(frames[0].data, bytes.fromhex("36 6B"))

    def test_manual_fd_packet_split(self):
        """
        @description         : 复现手册01 FD命令的两包CAN示例
        @param               : 无参数
        @return              : 无返回值
        """
        logical = bytes.fromhex("FD 01 0F A0 00 00 01 FA 00 00 00 6B")
        frames = split_can_frames(1, logical)
        self.assertEqual(
            [(frame.arbitration_id, frame.data.hex(" ").upper()) for frame in frames],
            [
                (0x0100, "FD 01 0F A0 00 00 01 FA"),
                (0x0101, "FD 00 00 00 6B"),
            ],
        )

    def test_manual_fd_reassembly(self):
        """
        @description         : 校验后续包重复功能码不会进入逻辑数据
        @param               : 无参数
        @return              : 无返回值
        """
        logical = bytes.fromhex("FD 01 0F A0 00 00 01 FA 00 00 00 6B")
        self.assertEqual(
            reassemble_can_frames(split_can_frames(1, logical), len(logical)),
            logical,
        )

    def test_rejects_wrong_continuation_code(self):
        """
        @description         : 校验后续分包功能码不一致时拒绝重组
        @param               : 无参数
        @return              : 无返回值
        """
        frames = (
            CanFrame(0x0100, bytes.fromhex("FD 01 02 03 04 05 06 07")),
            CanFrame(0x0101, bytes.fromhex("F6 08 6B")),
        )
        with self.assertRaises(ZDTProtocolError):
            reassemble_can_frames(frames, 10)

    def test_response_checksum_and_function(self):
        """
        @description         : 校验应答功能码和校验码
        @param               : 无参数
        @return              : 无返回值
        """
        response = ZDTCanProtocol().validate_response(1, bytes.fromhex("35 00 00 6B"))
        self.assertEqual(response.function_code, 0x35)
        with self.assertRaises(ZDTProtocolError):
            ZDTCanProtocol().validate_response(1, bytes.fromhex("35 00 00 00"))

    def test_xor_checksum_keeps_address_out_of_can_data(self):
        """
        @description         : 校验XOR包含地址但CAN DATA仍不发送地址
        @param               : 无参数
        @return              : 无返回值
        """
        frame = ZDTCanProtocol("xor").encode_command(
            1,
            LogicalCommand(0x06, b"\x45", 3),
        )[0]
        self.assertEqual(frame.data, bytes.fromhex("06 45 42"))


if __name__ == "__main__":
    unittest.main()
