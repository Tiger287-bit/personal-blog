import unittest
from unittest import mock

from zdt_x57s_can import ZdtX57SCan, ZdtX57SCanError


class SingleMotorBrickTests(unittest.TestCase):
    """
    @description         : 验证每个Brick对象只绑定并操作一台ZDT X57S电机
    @param               : unittest自动创建
    @return              : 无
    """

    def create_motor(self, motor_id):
        """
        @description         : 创建不连接真实网关的单电机测试对象
        @param motor_id      : 测试电机地址
        @return              : ZdtX57SCan对象
        """
        return ZdtX57SCan(
            motor_id=motor_id,
            host="127.0.0.1",
            port=8766,
            token="unit-test-token",
            timeout_s=0.5,
        )

    def test_four_objects_keep_independent_ids(self):
        """
        @description         : 校验同一Brick类可创建四个地址互不影响的对象
        @param               : 无
        @return              : 无
        """
        motors = [self.create_motor(motor_id) for motor_id in range(1, 5)]
        self.assertEqual([motor.motor_id for motor in motors], [1, 2, 3, 4])

    def test_read_speed_uses_bound_motor_id(self):
        """
        @description         : 校验读取速度请求自动携带对象绑定地址
        @param               : 无
        @return              : 无
        """
        motor = self.create_motor(7)
        with mock.patch.object(
            motor,
            "_call",
            return_value={"motor_id": 7, "speed_rpm": -20},
        ) as gateway_call:
            self.assertEqual(motor.read_speed(), -20)
        gateway_call.assert_called_once_with(
            "read_speed", {"motor_id": 7}
        )

    def test_motion_call_uses_bound_motor_id(self):
        """
        @description         : 校验速度控制请求不能覆盖对象绑定地址
        @param               : 无
        @return              : 无
        """
        motor = self.create_motor(9)
        with mock.patch.object(
            motor,
            "_call",
            return_value={"motor_id": 9, "accepted": True},
        ) as gateway_call:
            motor.set_speed(
                rpm=20,
                acceleration_level=10,
                confirmation="RUN_ZDT_X57S_V1_0",
            )
        gateway_call.assert_called_once_with(
            "set_speed",
            {
                "rpm": 20,
                "acceleration_level": 10,
                "motor_id": 9,
                "confirmation": "RUN_ZDT_X57S_V1_0",
            },
            timeout_s=None,
        )

    def test_rejects_invalid_object_motor_id(self):
        """
        @description         : 校验对象构造时拒绝0、256、布尔值和字符串地址
        @param               : 无
        @return              : 无
        """
        for motor_id in (0, 256, True, "1"):
            with self.subTest(motor_id=motor_id):
                with self.assertRaises(ZdtX57SCanError):
                    self.create_motor(motor_id)


if __name__ == "__main__":
    unittest.main()
