"""共享 Bus、响应解析、异常和 capability 测试。"""

import time
import unittest

from fake_backend import FakeBackend
from zdt_motor import (
    ChecksumType,
    ZDTBus,
    ZDTFormatError,
    ZDTMotor,
    ZDTParameterError,
    ZDTTimeoutError,
    ZDTUnsupportedFeatureError,
)
from zdt_motor.protocols import calculate_checksum, parse_arbitration_id, split_can_frames


def response_frames(address, function_code, data):
    """
    @description         : 构造固定0x6B校验的测试响应帧
    @param address       : 响应电机地址
    @param function_code : 功能码
    @param data          : 返回数据，不含功能码和校验码
    @return              : CanFrame元组
    """
    body = bytes((function_code,)) + bytes(data)
    checksum = calculate_checksum("fixed_6b", address, body)
    return split_can_frames(address, body + bytes((checksum,)))


def make_reply_callback(replies, *, address_override=None):
    """
    @description         : 创建按地址和功能码自动应答的FakeBackend回调
    @param replies       : 功能码到返回数据或地址功能码到返回数据的映射
    @param address_override: 可选固定响应地址
    @return              : on_send回调
    """
    def on_send(frame, backend):
        """
        @description         : 对第0包测试命令注入对应完整响应
        @param frame         : FakeBackend收到的发送帧
        @param backend       : FakeBackend实例
        @return              : 无返回值
        """
        address, packet = parse_arbitration_id(frame.arbitration_id)
        if packet != 0 or not frame.data:
            return
        function_code = frame.data[0]
        response_data = replies.get((address, function_code), replies.get(function_code))
        if response_data is None:
            return
        response_address = address if address_override is None else address_override
        for response_frame in response_frames(
            response_address,
            function_code,
            response_data,
        ):
            backend.queue_frame(response_frame)

    return on_send


class MotorTests(unittest.TestCase):
    """验证高级单电机 API 不泄漏协议字节。"""

    def create_motor(self, replies, *, motor_id=1, firmware="emm", timeout_s=0.1):
        """
        @description         : 创建带自动应答FakeBackend的电机和Bus
        @param replies       : 测试响应映射
        @param motor_id      : 电机地址
        @param firmware      : emm或x
        @param timeout_s     : 测试超时
        @return              : motor、bus、backend三元组
        """
        backend = FakeBackend(on_send=make_reply_callback(replies))
        bus = ZDTBus(backend=backend, default_timeout_s=timeout_s)
        motor = ZDTMotor(
            bus=bus,
            model="X57S",
            motor_id=motor_id,
            firmware=firmware,
            timeout_s=timeout_s,
        )
        return motor, bus, backend

    def test_emm_speed_position_and_status_decoding(self):
        """
        @description         : 校验Emm实时速度、角度和状态标志解析
        @param               : 无参数
        @return              : 无返回值
        """
        motor, bus, _ = self.create_motor(
            {
                0x35: bytes.fromhex("01 00 0A"),
                0x36: bytes.fromhex("00 00 01 00 00"),
                0x3A: bytes.fromhex("83"),
            }
        )
        try:
            self.assertEqual(motor.get_speed(), -10.0)
            self.assertAlmostEqual(motor.get_position(), 360.0)
            status = motor.get_status()
            self.assertTrue(status["enabled"])
            self.assertTrue(status["position_reached"])
            self.assertTrue(status["power_loss"])
        finally:
            bus.close()

    def test_x_speed_and_position_error_units(self):
        """
        @description         : 校验X固件速度0.1RPM和误差0.01度换算
        @param               : 无参数
        @return              : 无返回值
        """
        motor, bus, _ = self.create_motor(
            {
                0x35: bytes.fromhex("00 00 63"),
                0x37: bytes.fromhex("01 00 00 00 08"),
            },
            firmware="x",
        )
        try:
            self.assertEqual(motor.get_speed(), 9.9)
            self.assertEqual(motor.get_position_error(), -0.08)
        finally:
            bus.close()

    def test_command_success_and_structured_errors(self):
        """
        @description         : 校验02成功、E2参数错误和EE格式错误分开处理
        @param               : 无参数
        @return              : 无返回值
        """
        for status, expected_error in (
            (0x02, None),
            (0xE2, ZDTParameterError),
            (0xEE, ZDTFormatError),
        ):
            with self.subTest(status=status):
                motor, bus, _ = self.create_motor({0xF3: bytes((status,))})
                try:
                    if expected_error is None:
                        self.assertTrue(motor.enable()["accepted"])
                    else:
                        with self.assertRaises(expected_error):
                            motor.enable()
                finally:
                    bus.close()

    def test_capability_blocks_x42s_only_command_before_send(self):
        """
        @description         : 校验X57S温度读取在发送CAN前被拒绝
        @param               : 无参数
        @return              : 无返回值
        """
        motor, bus, backend = self.create_motor({})
        try:
            self.assertFalse(motor.supports("temperature"))
            with self.assertRaises(ZDTUnsupportedFeatureError):
                motor.get_temperature()
            self.assertEqual(backend.sent_frames, [])
        finally:
            bus.close()

    def test_two_motors_share_one_bus_and_match_addresses(self):
        """
        @description         : 校验共享Bus按扩展ID把响应分发给不同电机
        @param               : 无参数
        @return              : 无返回值
        """
        replies = {
            (1, 0x35): bytes.fromhex("00 00 0A"),
            (2, 0x35): bytes.fromhex("01 00 14"),
        }
        backend = FakeBackend(on_send=make_reply_callback(replies))
        bus = ZDTBus(backend=backend, default_timeout_s=0.1)
        motor1 = ZDTMotor(bus=bus, motor_id=1, model="X57S", firmware="emm")
        motor2 = ZDTMotor(bus=bus, motor_id=2, model="X57S", firmware="emm")
        try:
            self.assertEqual(motor1.get_speed(), 10.0)
            self.assertEqual(motor2.get_speed(), -20.0)
            self.assertIs(motor1.bus, motor2.bus)
        finally:
            bus.close()

    def test_motor_accepts_future_bus_contract(self):
        """
        @description         : 校验未来UART或Pulse Bus无需继承当前SocketCAN Bus
        @param               : 无参数
        @return              : 无返回值
        """
        class FutureBus:
            """仅实现ZDTMotor所需最小契约的测试Bus。"""

            checksum = ChecksumType.FIXED_6B
            default_timeout_s = 0.5

            def request(self, address, command, **kwargs):
                """
                @description         : 占位实现未来Bus请求接口
                @param address       : 电机地址
                @param command       : 逻辑命令
                @param kwargs        : 超时等可选参数
                @return              : 本测试不调用
                """
                raise AssertionError("construction test must not send")

        motor = ZDTMotor(
            bus=FutureBus(),
            motor_id=1,
            model="X57S",
            firmware="emm",
        )
        self.assertEqual(motor.motor_id, 1)

    def test_set_motor_id_accepts_response_from_new_address(self):
        """
        @description         : 校验地址修改应答可来自旧地址或新地址
        @param               : 无参数
        @return              : 无返回值
        """
        backend = FakeBackend(
            on_send=make_reply_callback({0xAE: b"\x02"}, address_override=2)
        )
        bus = ZDTBus(backend=backend, default_timeout_s=0.1)
        motor = ZDTMotor(bus=bus, motor_id=1, model="X57S", firmware="emm")
        try:
            result = motor.set_motor_id(2, store=True)
            self.assertEqual(motor.motor_id, 2)
            self.assertEqual(result["old_motor_id"], 1)
            self.assertTrue(result["stored"])
        finally:
            bus.close()

    def test_unsolicited_completion_enters_event_queue(self):
        """
        @description         : 校验9F主动完成返回不会被同步请求结构丢弃
        @param               : 无参数
        @return              : 无返回值
        """
        backend = FakeBackend()
        bus = ZDTBus(backend=backend, default_timeout_s=0.1)
        try:
            bus.open()
            for frame in response_frames(1, 0xFD, b"\x9F"):
                backend.queue_frame(frame)
            event = bus.next_event(timeout_s=0.2)
            self.assertIsNotNone(event)
            self.assertEqual(event.address, 1)
            self.assertEqual(event.function_code, 0xFD)
            self.assertEqual(event.data, b"\x9F")
        finally:
            bus.close()

    def test_timeout_is_specific(self):
        """
        @description         : 校验无应答时抛出ZDTTimeoutError
        @param               : 无参数
        @return              : 无返回值
        """
        motor, bus, _ = self.create_motor({}, timeout_s=0.03)
        try:
            with self.assertRaises(ZDTTimeoutError):
                motor.get_speed()
        finally:
            bus.close()

    def test_raw_api_calculates_id_and_checksum(self):
        """
        @description         : 校验raw接口仍由Brick计算扩展ID和校验码
        @param               : 无参数
        @return              : 无返回值
        """
        motor, bus, _ = self.create_motor({})
        try:
            frame = motor.raw.frames(0x36, b"", expected_response_length=7)[0]
            self.assertEqual(frame.arbitration_id, 0x0100)
            self.assertEqual(frame.data, b"\x36\x6B")
        finally:
            bus.close()


if __name__ == "__main__":
    unittest.main()
