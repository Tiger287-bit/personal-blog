"""ZDT Motor Brick V1 架构边界永久回归测试。"""

import inspect
from pathlib import Path
import time
import unittest

from fake_backend import FakeBackend
import zdt_motor
from zdt_motor import (
    BusKind,
    ChecksumType,
    SocketCanEndpoint,
    ZDTCanBus,
    ZDTMotor,
    ZDTMotorBus,
)
from zdt_motor.backends import CanBackend, CanFrame, SocketCANBackend
from zdt_motor.commands import common, emm, x
from zdt_motor.messages import LogicalCommand, ZDTResponse
from zdt_motor.protocols import ZDTCanProtocol, calculate_checksum, split_can_frames


def response_frames(address, function_code, data):
    """
    @description         : 构造固定0x6B校验的测试应答帧
    @param address       : 应答电机地址
    @param function_code : 应答功能码
    @param data          : 不含功能码和校验码的应答数据
    @return              : CanFrame元组
    """
    body = bytes((function_code,)) + bytes(data)
    checksum = calculate_checksum("fixed_6b", address, body)
    return split_can_frames(address, body + bytes((checksum,)))


def wait_until(predicate, timeout_s=0.3):
    """
    @description         : 在测试超时内等待条件成立
    @param predicate     : 返回布尔值的条件函数
    @param timeout_s     : 最大等待秒数
    @return              : 条件是否在超时前成立
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return bool(predicate())


class RecordingMotorBus(ZDTMotorBus):
    """记录逻辑请求而不接触任何 CAN 实现的测试总线。"""

    def __init__(self):
        """
        @description         : 初始化逻辑请求记录
        @param               : 无参数
        @return              : 无返回值
        """
        self.requests = []

    @property
    def kind(self):
        """
        @description         : 返回测试总线种类
        @param               : 无参数
        @return              : BusKind.CAN
        """
        return BusKind.CAN

    @property
    def endpoint(self):
        """
        @description         : 返回测试端点
        @param               : 无参数
        @return              : None
        """
        return None

    @property
    def checksum(self):
        """
        @description         : 返回测试校验方式
        @param               : 无参数
        @return              : ChecksumType.FIXED_6B
        """
        return ChecksumType.FIXED_6B

    @property
    def default_timeout_s(self):
        """
        @description         : 返回测试默认超时
        @param               : 无参数
        @return              : 0.5秒
        """
        return 0.5

    def open(self):
        """
        @description         : 打开测试总线
        @param               : 无参数
        @return              : 当前测试总线
        """
        return self

    def close(self):
        """
        @description         : 关闭测试总线
        @param               : 无参数
        @return              : 无返回值
        """

    def request(self, address, command, **kwargs):
        """
        @description         : 记录逻辑请求并返回测试应答
        @param address       : 电机地址
        @param command       : LogicalCommand实例
        @param kwargs        : 超时等可选参数
        @return              : ZDTResponse测试应答
        """
        self.requests.append((address, command, kwargs))
        return ZDTResponse(address, command.function_code, b"\x02", b"", 0.0)

    def describe(self):
        """
        @description         : 返回测试总线描述
        @param               : 无参数
        @return              : 测试描述字典
        """
        return {"kind": self.kind.value}


class ArchitectureBoundaryTests(unittest.TestCase):
    """验证命令、电机、CAN Session、协议和 Backend 的职责边界。"""

    def test_can_backend_contract(self):
        """
        @description         : 验证真实和测试CAN Backend继承CanBackend
        @param               : 无参数
        @return              : 无返回值
        """
        self.assertTrue(issubclass(SocketCANBackend, CanBackend))
        self.assertIsInstance(FakeBackend(), CanBackend)

    def test_motor_accepts_zdt_motor_bus(self):
        """
        @description         : 验证ZDTMotor只依赖正式ZDTMotorBus契约
        @param               : 无参数
        @return              : 无返回值
        """
        bus = RecordingMotorBus()
        motor = ZDTMotor(bus=bus, motor_id=1, model="X57S", firmware="emm")
        self.assertIs(motor.bus, bus)

    def test_commands_return_logical_command(self):
        """
        @description         : 验证三组命令构造器只返回LogicalCommand
        @param               : 无参数
        @return              : 无返回值
        """
        commands = (
            common.build_enable(),
            emm.build_speed(10),
            x.build_speed(10),
        )
        self.assertTrue(all(isinstance(item, LogicalCommand) for item in commands))
        self.assertTrue(all(not isinstance(item, CanFrame) for item in commands))

    def test_commands_do_not_require_can_backend(self):
        """
        @description         : 验证命令模块源码不依赖CAN帧或Backend
        @param               : 无参数
        @return              : 无返回值
        """
        for module in (common, emm, x):
            source = inspect.getsource(module)
            self.assertNotIn("CanFrame", source)
            self.assertNotIn("backends", source)
            self.assertNotIn("import can", source)

    def test_can_protocol_encodes_logical_command(self):
        """
        @description         : 验证ZDTCanProtocol把逻辑命令编码成正确扩展帧
        @param               : 无参数
        @return              : 无返回值
        """
        command = LogicalCommand(0xF3, bytes.fromhex("AB 01 00"), 3)
        frames = ZDTCanProtocol().encode_command(1, command)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].arbitration_id, 0x0100)
        self.assertTrue(frames[0].is_extended)
        self.assertEqual(frames[0].data, bytes.fromhex("F3 AB 01 00 6B"))

    def test_can_protocol_multiframe(self):
        """
        @description         : 验证长逻辑命令的CAN分包编号和续包功能码
        @param               : 无参数
        @return              : 无返回值
        """
        command = LogicalCommand(0xFD, bytes(range(1, 15)), 3)
        frames = ZDTCanProtocol().encode_command(2, command)
        self.assertEqual(
            [frame.arbitration_id for frame in frames],
            [0x0200, 0x0201, 0x0202],
        )
        self.assertTrue(all(len(frame.data) <= 8 for frame in frames))
        self.assertTrue(all(frame.data[0] == 0xFD for frame in frames))

    def test_raw_request_remains_logical(self):
        """
        @description         : 验证RawMotorAPI把逻辑命令交给ZDTMotorBus请求
        @param               : 无参数
        @return              : 无返回值
        """
        bus = RecordingMotorBus()
        motor = ZDTMotor(bus=bus, motor_id=3, model="X57S", firmware="emm")
        response = motor.raw.request(
            0x35,
            expected_response_length=5,
            timeout_s=0.2,
        )
        address, command, kwargs = bus.requests[0]
        self.assertEqual(address, 3)
        self.assertIsInstance(command, LogicalCommand)
        self.assertEqual(command.function_code, 0x35)
        self.assertEqual(command.expected_response_length, 5)
        self.assertEqual(kwargs["timeout_s"], 0.2)
        self.assertIsInstance(response, ZDTResponse)

    def test_raw_api_does_not_expose_frames(self):
        """
        @description         : 验证RawMotorAPI不再暴露CAN专属frames接口
        @param               : 无参数
        @return              : 无返回值
        """
        motor = ZDTMotor(
            bus=RecordingMotorBus(),
            motor_id=1,
            model="X57S",
            firmware="emm",
        )
        self.assertFalse(hasattr(motor.raw, "frames"))

    def test_only_socketcan_backend_imports_python_can(self):
        """
        @description         : 验证python-can只出现在SocketCANBackend实现文件
        @param               : 无参数
        @return              : 无返回值
        """
        package_root = Path(zdt_motor.__file__).resolve().parent
        importers = []
        for source_path in package_root.rglob("*.py"):
            if "import can" in source_path.read_text(encoding="utf-8"):
                importers.append(source_path.relative_to(package_root).as_posix())
        self.assertEqual(importers, ["backends/socketcan.py"])

    def test_completion_function_set_is_specific(self):
        """
        @description         : 验证F5和9A完成返回进入事件队列
        @param               : 无参数
        @return              : 无返回值
        """
        backend = FakeBackend()
        bus = ZDTCanBus(backend=backend)
        try:
            bus.open()
            for function_code in (0xF5, 0x9A):
                for frame in response_frames(1, function_code, b"\x9F"):
                    backend.queue_frame(frame)
            first = bus.next_event(timeout_s=0.2)
            second = bus.next_event(timeout_s=0.2)
            self.assertEqual(
                [(first.function_code, first.data), (second.function_code, second.data)],
                [(0xF5, b"\x9F"), (0x9A, b"\x9F")],
            )
        finally:
            bus.close()

    def test_event_queue_is_bounded_and_keeps_newest(self):
        """
        @description         : 验证事件队列满时丢弃最旧事件并累计计数
        @param               : 无参数
        @return              : 无返回值
        """
        backend = FakeBackend()
        bus = ZDTCanBus(backend=backend, event_queue_size=2)
        try:
            bus.open()
            for address in (1, 2, 3):
                for frame in response_frames(address, 0xFD, b"\x9F"):
                    backend.queue_frame(frame)
            self.assertTrue(wait_until(lambda: bus.dropped_event_count == 1))
            self.assertEqual(bus.next_event().address, 2)
            self.assertEqual(bus.next_event().address, 3)
            self.assertIsNone(bus.next_event())
        finally:
            bus.close()

    def test_socketcan_endpoint_normalizes_strings(self):
        """
        @description         : 验证SocketCAN接口名和物理端口会去除首尾空白
        @param               : 无参数
        @return              : 无返回值
        """
        endpoint = SocketCanEndpoint(
            interface="  can0  ",
            physical_port="  VENTUNO Q FDCAN1  ",
        )
        self.assertEqual(endpoint.interface, "can0")
        self.assertEqual(endpoint.physical_port, "VENTUNO Q FDCAN1")


if __name__ == "__main__":
    unittest.main()
