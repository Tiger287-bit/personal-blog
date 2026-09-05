# SPDX-License-Identifier: MIT
"""真实 ZDT CAN 后端；只使用已经配置好的 Linux can0。"""


class CanMotorBackend:
    """把四个 ZDTMotor 对象封装成与 FakeBackend 相同的接口。"""

    simulated = False

    def __init__(
        self,
        motor_ids=(1, 2, 3, 4),
        direction_signs=(1, 1, 1, 1),
        acceleration=10,
    ):
        # 延迟导入，让默认 fake 模式不依赖 App Lab Brick 环境。
        from zdt_motor import SocketCanEndpoint, ZDTCanBus, ZDTMotor

        if len(motor_ids) != 4 or len(set(motor_ids)) != 4:
            raise ValueError("motor_ids must contain four different IDs")
        if len(direction_signs) != 4:
            raise ValueError("direction_signs must contain four values")
        if any(sign not in (-1, 1) for sign in direction_signs):
            raise ValueError("direction_signs must be +1 or -1")
        if not 0 <= acceleration <= 255:
            raise ValueError("Emm acceleration must be in [0, 255]")

        self.motor_ids = tuple(int(motor_id) for motor_id in motor_ids)
        self.direction_signs = tuple(
            int(sign) for sign in direction_signs
        )
        self.acceleration = int(acceleration)
        self._enabled = False
        self._opened = False
        self._feedback_seen = False
        self._rpm = [0, 0, 0, 0]

        endpoint = SocketCanEndpoint(
            interface="can0",
            expected_bitrate=500_000,
            physical_port="VENTUNO Q FDCAN1 via CANnectivity",
        )
        self.bus = ZDTCanBus(
            name="chassis_motor_can",
            endpoint=endpoint,
            checksum="fixed_6b",
            default_timeout_s=0.5,
        )
        self.motors = [
            ZDTMotor(
                bus=self.bus,
                model="X57S",
                motor_id=motor_id,
                firmware="emm",
            )
            for motor_id in self.motor_ids
        ]

        # 打开 SocketCAN，但启动时不发送使能或速度命令。
        try:
            self.bus.open()
            self._opened = True
        except Exception:
            self.bus.close()
            raise

    @property
    def enabled(self):
        return self._enabled

    @property
    def hardware_connected(self):
        return self._opened and self.bus.is_open and self._feedback_seen

    def set_enabled(self, enabled):
        """使能或停止并失能四台电机。"""
        if enabled:
            if self._enabled:
                return
            try:
                for motor in self.motors:
                    motor.enable()
            except Exception:
                self._enabled = False
                self.safe_stop_and_disable()
                raise
            self._enabled = True
            return

        self.safe_stop_and_disable()

    def set_target_rpm(self, values):
        """发送四个逻辑 RPM；符号方向由 ZDT Emm API 解释。"""
        rpms = [int(value) for value in values]
        if len(rpms) != 4:
            raise ValueError("RPM command must contain four values")
        if not self._enabled and any(rpm != 0 for rpm in rpms):
            raise RuntimeError("motors are not enabled")

        physical_rpms = [
            rpm * sign
            for rpm, sign in zip(rpms, self.direction_signs)
        ]

        if all(rpm == 0 for rpm in physical_rpms):
            self.stop()
            return

        try:
            for motor, rpm in zip(self.motors, physical_rpms):
                motor.set_speed(
                    rpm,
                    acceleration=self.acceleration,
                    synchronized=True,
                )
            self.bus.start_synchronized()
            self._rpm = list(rpms)
        except Exception:
            self._rpm = [0, 0, 0, 0]
            raise

    def get_actual_rpm(self):
        """回读真实电机轴转速；转换回与输入相同的逻辑方向。"""
        try:
            actual = [
                int(round(motor.get_speed() * sign))
                for motor, sign in zip(self.motors, self.direction_signs)
            ]
        except Exception:
            self._feedback_seen = False
            raise
        self._feedback_seen = True
        return actual

    def stop(self):
        """向全部电机发送停止命令；尽量完成四台后再报告错误。"""
        errors = []
        for motor in self.motors:
            try:
                motor.stop()
            except Exception as error:
                errors.append(f"motor {motor.motor_id}: {error}")
        self._rpm = [0, 0, 0, 0]
        if errors:
            raise RuntimeError("; ".join(errors))

    def disable(self):
        """向全部电机发送失能命令；尽量完成四台后再报告错误。"""
        errors = []
        for motor in self.motors:
            try:
                motor.disable()
            except Exception as error:
                errors.append(f"motor {motor.motor_id}: {error}")
        self._enabled = False
        if errors:
            raise RuntimeError("; ".join(errors))

    def safe_stop_and_disable(self):
        """无论单台是否报错，都尝试完成全部 stop 和 disable。"""
        errors = []
        try:
            self.stop()
        except Exception as error:
            errors.append(f"stop: {error}")
        try:
            self.disable()
        except Exception as error:
            errors.append(f"disable: {error}")
        self._enabled = False
        self._rpm = [0, 0, 0, 0]
        if errors:
            raise RuntimeError("; ".join(errors))

    def close(self):
        """只释放 CAN 资源；停车和失能由调用方先完成。"""
        if self._opened:
            self.bus.close()
            self._opened = False
