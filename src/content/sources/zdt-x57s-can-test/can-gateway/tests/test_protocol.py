import unittest

from zdt_x57s_protocol import (
    ZdtProtocolError,
    arbitration_id,
    build_enable_command,
    build_speed_command,
    build_speed_query,
    build_stop_command,
    parse_ack,
    parse_speed_reply,
)


class ProtocolTests(unittest.TestCase):
    """
    @description         : 验证第二代FW_Emm固定CAN报文字节和解析边界
    @param               : unittest自动创建
    @return              : 无
    """

    def test_command_bytes(self):
        """
        @description         : 校验地址映射、速度查询、使能、速度和停止报文
        @param               : 无
        @return              : 无
        """
        self.assertEqual(arbitration_id(1), 0x100)
        self.assertEqual(arbitration_id(4), 0x400)
        self.assertEqual(build_speed_query(), bytes.fromhex("35 6B"))
        self.assertEqual(
            build_enable_command(True), bytes.fromhex("F3 AB 01 00 6B")
        )
        self.assertEqual(
            build_speed_command(-20, 10),
            bytes.fromhex("F6 01 00 14 0A 00 6B"),
        )
        self.assertEqual(
            build_stop_command(), bytes.fromhex("FE 98 00 6B")
        )

    def test_speed_reply(self):
        """
        @description         : 校验正反方向速度应答解析
        @param               : 无
        @return              : 无
        """
        self.assertEqual(parse_speed_reply(bytes.fromhex("35 00 00 3C 6B")), 60)
        self.assertEqual(parse_speed_reply(bytes.fromhex("35 01 00 14 6B")), -20)

    def test_rejected_ack(self):
        """
        @description         : 校验E2拒绝状态会抛出协议异常
        @param               : 无
        @return              : 无
        """
        with self.assertRaises(ZdtProtocolError):
            parse_ack(bytes.fromhex("F3 E2 6B"), 0xF3)


if __name__ == "__main__":
    unittest.main()
