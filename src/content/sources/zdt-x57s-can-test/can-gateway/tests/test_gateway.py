import unittest

from gateway import GatewayRequestError, MotorGateway


class GatewayValidationTests(unittest.TestCase):
    """
    @description         : 验证网关鉴权、方法白名单和运动安全限制
    @param               : unittest自动创建
    @return              : 无
    """

    def setUp(self):
        """
        @description         : 为每个测试创建不访问真实CAN的网关实例
        @param               : 无
        @return              : 无
        """
        self.gateway = MotorGateway("can0", "secret", 60, 0.5)

    def request(self, method, params=None, token="secret"):
        """
        @description         : 构造版本1网关请求字典
        @param method        : 网关方法名
        @param params        : 方法参数字典
        @param token         : 鉴权令牌
        @return              : 请求字典
        """
        return {
            "version": 1,
            "request_id": "test",
            "token": token,
            "method": method,
            "params": params or {},
        }

    def test_rejects_wrong_token(self):
        """
        @description         : 校验错误令牌被拒绝
        @param               : 无
        @return              : 无
        """
        with self.assertRaises(GatewayRequestError) as caught:
            self.gateway.dispatch(self.request("status", token="wrong"))
        self.assertEqual(caught.exception.code, "unauthorized")

    def test_rejects_unknown_method(self):
        """
        @description         : 校验未列入白名单的方法被拒绝
        @param               : 无
        @return              : 无
        """
        with self.assertRaises(GatewayRequestError) as caught:
            self.gateway.dispatch(self.request("raw_can_send"))
        self.assertEqual(caught.exception.code, "unknown_method")

    def test_rejects_removed_batch_methods(self):
        """
        @description         : 校验批量探测和批量停车不属于单电机网关API
        @param               : 无
        @return              : 无
        """
        for method_name in ("probe", "stop_all"):
            with self.subTest(method=method_name):
                with self.assertRaises(GatewayRequestError) as caught:
                    self.gateway.dispatch(self.request(method_name))
                self.assertEqual(caught.exception.code, "unknown_method")

    def test_motion_needs_confirmation(self):
        """
        @description         : 校验使能命令缺少运动确认时不会访问CAN
        @param               : 无
        @return              : 无
        """
        with self.assertRaises(GatewayRequestError) as caught:
            self.gateway.dispatch(
                self.request("enable", {"motor_id": 1})
            )
        self.assertEqual(caught.exception.code, "confirmation_required")

    def test_rejects_unsafe_speed_before_can(self):
        """
        @description         : 校验超过60RPM的命令在访问CAN前被拒绝
        @param               : 无
        @return              : 无
        """
        with self.assertRaises(GatewayRequestError) as caught:
            self.gateway.dispatch(
                self.request(
                    "set_speed",
                    {
                        "motor_id": 1,
                        "rpm": 61,
                        "acceleration_level": 10,
                        "confirmation": "RUN_ZDT_X57S_V1_0",
                    },
                )
            )
        self.assertEqual(caught.exception.code, "invalid_params")

    def test_rejects_unsafe_watchdog_configuration(self):
        """
        @description         : 校验速度命令看门狗不能被配置为过长时间
        @param               : 无
        @return              : 无
        """
        with self.assertRaises(ValueError):
            MotorGateway("can0", "secret", 60, 0.5, 5.1)

    def test_accepts_full_protocol_motor_id_range(self):
        """
        @description         : 校验单电机网关支持第二代协议地址1至255
        @param               : 无
        @return              : 无
        """
        self.assertEqual(self.gateway._validate_motor_id(1), 1)
        self.assertEqual(self.gateway._validate_motor_id(255), 255)

    def test_rejects_motor_id_outside_protocol_range(self):
        """
        @description         : 校验地址0、256和布尔值在访问CAN前被拒绝
        @param               : 无
        @return              : 无
        """
        for motor_id in (0, 256, True):
            with self.subTest(motor_id=motor_id):
                with self.assertRaises(GatewayRequestError) as caught:
                    self.gateway._validate_motor_id(motor_id)
                self.assertEqual(caught.exception.code, "invalid_params")


if __name__ == "__main__":
    unittest.main()
