"""Common、Emm 和 X 命令 golden tests。"""

import unittest

from zdt_motor import ZDTConfigurationError
from zdt_motor.commands import common, emm, x
from zdt_motor.protocols import ZDTCanProtocol


def encoded_data(command, address=1):
    """
    @description         : 把单帧逻辑命令编码成便于断言的CAN DATA
    @param command       : LogicalCommand
    @param address       : 电机地址
    @return              : 单帧CAN DATA
    """
    frames = ZDTCanProtocol().encode_command(address, command)
    if len(frames) != 1:
        raise AssertionError("test helper expected one CAN frame")
    return frames[0].data


class CommandTests(unittest.TestCase):
    """根据手册示例检查命令数据布局。"""

    def test_enable_golden(self):
        """
        @description         : 复现手册01 F3 AB 01 00 6B使能命令
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertEqual(
            encoded_data(common.build_enable(True)),
            bytes.fromhex("F3 AB 01 00 6B"),
        )

    def test_stop_golden(self):
        """
        @description         : 复现手册01 FE 98 00 6B立即停止命令
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertEqual(
            encoded_data(common.build_stop()),
            bytes.fromhex("FE 98 00 6B"),
        )

    def test_read_speed_golden(self):
        """
        @description         : 复现手册01 35 6B读取实时速度命令
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertEqual(
            encoded_data(common.build_read_speed()),
            bytes.fromhex("35 6B"),
        )

    def test_emm_speed_golden(self):
        """
        @description         : 复现手册Emm速度1500RPM加速度10示例
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertEqual(
            encoded_data(
                emm.build_speed(1500, direction="ccw", acceleration=10)
            ),
            bytes.fromhex("F6 01 05 DC 0A 00 6B"),
        )

    def test_x_speed_layout(self):
        """
        @description         : 校验X速度使用加速度uint16和0.1RPM速度布局
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertEqual(
            encoded_data(
                x.build_speed(2000.0, direction="ccw", acceleration=1000)
            ),
            bytes.fromhex("F6 01 03 E8 4E 20 00 6B"),
        )

    def test_emm_position_degrees_to_pulses(self):
        """
        @description         : 校验1.8度16细分下360度转换为3200脉冲并正确分包
        @param               : 无参数
        @return              : 无返回值
        """
        command = emm.build_position(
            360,
            rpm=1500,
            acceleration=0,
            mode="relative_current",
        )
        frames = ZDTCanProtocol().encode_command(1, command)
        self.assertEqual(frames[0].data, bytes.fromhex("FD 00 05 DC 00 00 00 0C"))
        self.assertEqual(frames[1].data, bytes.fromhex("FD 80 02 00 6B"))

    def test_x_position_layout(self):
        """
        @description         : 校验X梯形位置命令分别编码加速减速速度和0.1度角度
        @param               : 无参数
        @return              : 无返回值
        """
        command = x.build_position(
            -360.0,
            rpm=1000.0,
            acceleration=511,
            deceleration=506,
            mode="relative_last",
        )
        frames = ZDTCanProtocol().encode_command(1, command)
        self.assertEqual(frames[0].data, bytes.fromhex("FD 01 01 FF 01 FA 27 10"))
        self.assertEqual(frames[1].data, bytes.fromhex("FD 00 00 0E 10 00 00 6B"))

    def test_set_motor_id_and_microstep(self):
        """
        @description         : 校验地址永久存储和256细分的特殊编码
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertEqual(
            encoded_data(common.build_set_motor_id(4, store=True)),
            bytes.fromhex("AE 4B 01 04 6B"),
        )
        self.assertEqual(
            encoded_data(common.build_set_microstep(256, store=True)),
            bytes.fromhex("84 8A 01 00 6B"),
        )

    def test_parameter_validation(self):
        """
        @description         : 校验超速、非法加速度和无效电机地址被本地拒绝
        @param               : 无参数
        @return              : 无返回值
        """
        with self.assertRaises(ZDTConfigurationError):
            emm.build_speed(3001)
        with self.assertRaises(ZDTConfigurationError):
            x.build_speed(10, acceleration=65536)
        with self.assertRaises(ZDTConfigurationError):
            common.build_set_motor_id(0)


if __name__ == "__main__":
    unittest.main()
