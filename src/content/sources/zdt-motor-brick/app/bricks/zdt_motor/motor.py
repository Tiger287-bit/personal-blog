"""面向工程单位的可复用单电机 ZDTMotor API。"""

from dataclasses import replace

from .capabilities import capabilities_for
from .bus_base import ZDTMotorBus
from .commands import common, emm, x
from .compat import brick
from .config import ChecksumType, Firmware, HomeMode, MotorConfig
from .errors import (
    ZDTCommandError,
    ZDTConfigurationError,
    ZDTFormatError,
    ZDTParameterError,
    ZDTProtocolError,
)
from .raw import RawMotorAPI


ACK_RECEIVED = 0x02
ACK_HOME_ALREADY_ACTIVE = 0x12
ACK_LIMIT_ALREADY_ACTIVE = 0x22
ACK_PARAMETER_ERROR = 0xE2
ACK_FORMAT_ERROR = 0xEE
ACK_ACTION_COMPLETE = 0x9F


def _u16(data):
    """
    @description         : 从高字节在前的两字节解析无符号整数
    @param data          : 两字节数据
    @return              : 0至65535整数
    """
    payload = bytes(data)
    if len(payload) != 2:
        raise ZDTProtocolError("uint16 field must contain 2 bytes")
    return int.from_bytes(payload, "big")


def _u32(data):
    """
    @description         : 从高字节在前的四字节解析无符号整数
    @param data          : 四字节数据
    @return              : 0至4294967295整数
    """
    payload = bytes(data)
    if len(payload) != 4:
        raise ZDTProtocolError("uint32 field must contain 4 bytes")
    return int.from_bytes(payload, "big")


def _signed_magnitude(data, magnitude_size):
    """
    @description         : 解析手册中的方向字节加无符号绝对值格式
    @param data          : 方向字节和绝对值
    @param magnitude_size: 绝对值字节数
    @return              : 带符号整数
    """
    payload = bytes(data)
    if len(payload) != magnitude_size + 1:
        raise ZDTProtocolError("signed-magnitude response length is invalid")
    if payload[0] not in (0x00, 0x01):
        raise ZDTProtocolError("signed-magnitude sign must be 0x00 or 0x01")
    magnitude = int.from_bytes(payload[1:], "big")
    return -magnitude if payload[0] == 0x01 else magnitude


def _decode_ack(response, *, allow_home_no_motion=False):
    """
    @description         : 解析02、12、22、E2、EE和9F命令状态
    @param response      : ZDTResponse
    @param allow_home_no_motion: 回零时是否接受已在零点或限位状态
    @return              : 包含状态码和状态名称的字典
    """
    if len(response.data) != 1:
        raise ZDTProtocolError("command acknowledgement must contain one status byte")
    status = response.data[0]
    if status == ACK_RECEIVED:
        return {"status": status, "status_name": "received", "accepted": True}
    if status == ACK_ACTION_COMPLETE:
        return {"status": status, "status_name": "completed", "accepted": True}
    if status in (ACK_HOME_ALREADY_ACTIVE, ACK_LIMIT_ALREADY_ACTIVE):
        status_name = (
            "already_at_home" if status == ACK_HOME_ALREADY_ACTIVE else "limit_active"
        )
        if allow_home_no_motion:
            return {"status": status, "status_name": status_name, "accepted": True}
        raise ZDTCommandError(
            f"motor did not move because {status_name}",
            status=status,
            function_code=response.function_code,
        )
    if status == ACK_PARAMETER_ERROR:
        raise ZDTParameterError(
            "motor rejected parameters or current state does not allow the command",
            status=status,
            function_code=response.function_code,
        )
    if status == ACK_FORMAT_ERROR:
        raise ZDTFormatError(
            "motor reported an invalid command format",
            status=status,
            function_code=response.function_code,
        )
    raise ZDTCommandError(
        f"unknown motor command status 0x{status:02X}",
        status=status,
        function_code=response.function_code,
    )


@brick
class ZDTMotor:
    """一台 ZDT 第二代闭环电机；多个对象可共享同一个 ZDTBus。"""

    def __init__(
        self,
        *,
        bus,
        motor_id=1,
        model="X57S",
        firmware="emm",
        checksum=None,
        microstep=16,
        step_angle_degrees=1.8,
        timeout_s=None,
    ):
        """
        @description         : 将单电机对象绑定到共享Bus和固定电机地址
        @param bus           : 共享ZDTBus
        @param motor_id      : 电机地址1至255
        @param model         : V1确认型号X57S
        @param firmware      : emm或x
        @param checksum      : None表示沿用Bus校验方式
        @param microstep     : 当前细分1至256
        @param step_angle_degrees: 电机步距角0.9或1.8度
        @param timeout_s     : None表示沿用Bus默认超时
        @return              : 无返回值
        """
        if not isinstance(bus, ZDTMotorBus):
            raise TypeError("bus must implement ZDTMotorBus")
        resolved_checksum = bus.checksum if checksum is None else checksum
        resolved_timeout = bus.default_timeout_s if timeout_s is None else timeout_s
        self.bus = bus
        self._config = MotorConfig(
            model=model,
            firmware=firmware,
            motor_id=motor_id,
            checksum=resolved_checksum,
            microstep=microstep,
            step_angle_degrees=step_angle_degrees,
            timeout_s=resolved_timeout,
        )
        if self._config.checksum is not bus.checksum:
            raise ZDTConfigurationError(
                "all motors sharing one ZDTBus must use the bus checksum"
            )
        self.capabilities = capabilities_for(
            self._config.model,
            self._config.firmware,
        )
        self.raw = RawMotorAPI(self)

    @property
    def motor_id(self):
        """
        @description         : 获取当前对象绑定的电机地址
        @param               : 无参数
        @return              : 地址1至255
        """
        return self._config.motor_id

    @property
    def model(self):
        """
        @description         : 获取能力门控使用的电机型号
        @param               : 无参数
        @return              : 型号字符串
        """
        return self._config.model

    @property
    def firmware(self):
        """
        @description         : 获取当前对象使用的固件协议布局
        @param               : 无参数
        @return              : Firmware枚举
        """
        return self._config.firmware

    def supports(self, feature):
        """
        @description         : 查询当前型号和固件是否支持某能力
        @param feature       : 功能名称
        @return              : 支持返回True
        """
        return self.capabilities.supports(feature)

    def enable(self, *, synchronized=False):
        """
        @description         : 使能并锁定当前电机轴
        @param synchronized  : True缓存到同步触发，False立即执行
        @return              : 结构化命令状态
        """
        self.capabilities.require("enable")
        return self._execute(common.build_enable(True, synchronized=synchronized))

    def disable(self, *, synchronized=False):
        """
        @description         : 失能当前电机并允许电机轴自由转动
        @param synchronized  : True缓存到同步触发，False立即执行
        @return              : 结构化命令状态
        """
        self.capabilities.require("enable")
        return self._execute(common.build_enable(False, synchronized=synchronized))

    def stop(self, *, synchronized=False):
        """
        @description         : 向当前电机发送立即停止命令
        @param synchronized  : True缓存到同步触发，False立即执行
        @return              : 结构化命令状态
        """
        self.capabilities.require("stop")
        return self._execute(common.build_stop(synchronized=synchronized))

    def safe_stop_and_disable(self):
        """
        @description         : 尝试停止再失能，确保两条安全命令都发送
        @param               : 无参数
        @return              : stop和disable结果字典
        """
        results = {}
        first_error = None
        for name, action in (("stop", self.stop), ("disable", self.disable)):
            try:
                results[name] = action()
            except Exception as error:
                results[name] = {"error": str(error)}
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error
        return results

    def set_speed(
        self,
        rpm,
        *,
        direction=None,
        acceleration=None,
        synchronized=False,
    ):
        """
        @description         : 按固件布局用RPM工程单位设置速度
        @param rpm           : 目标RPM，可用符号表达方向
        @param direction     : cw、ccw或None
        @param acceleration  : Emm为0至255档，X为RPM/S
        @param synchronized  : True缓存到同步触发，False立即执行
        @return              : 结构化命令状态
        """
        self.capabilities.require("speed")
        if self.firmware is Firmware.EMM:
            command = emm.build_speed(
                rpm,
                direction=direction,
                acceleration=10 if acceleration is None else acceleration,
                synchronized=synchronized,
            )
        else:
            command = x.build_speed(
                rpm,
                direction=direction,
                acceleration=1000 if acceleration is None else acceleration,
                synchronized=synchronized,
            )
        return self._execute(command)

    def move_relative(
        self,
        degrees,
        *,
        rpm=60,
        direction=None,
        acceleration=None,
        deceleration=None,
        synchronized=False,
    ):
        """
        @description         : 相对当前位置运动指定工程角度
        @param degrees       : 相对角度，可用符号表达方向
        @param rpm           : 最大速度RPM
        @param direction     : cw、ccw或None
        @param acceleration  : Emm为档位，X为RPM/S
        @param deceleration  : X固件减速度，Emm忽略且必须为None
        @param synchronized  : True缓存到同步触发，False立即执行
        @return              : 结构化命令状态
        """
        return self._move(
            degrees,
            rpm=rpm,
            direction=direction,
            acceleration=acceleration,
            deceleration=deceleration,
            mode="relative_current",
            synchronized=synchronized,
        )

    def move_absolute(
        self,
        degrees,
        *,
        rpm=60,
        direction=None,
        acceleration=None,
        deceleration=None,
        synchronized=False,
    ):
        """
        @description         : 相对坐标零点运动到指定工程角度
        @param degrees       : 绝对目标角度，可用符号表达方向
        @param rpm           : 最大速度RPM
        @param direction     : cw、ccw或None
        @param acceleration  : Emm为档位，X为RPM/S
        @param deceleration  : X固件减速度，Emm忽略且必须为None
        @param synchronized  : True缓存到同步触发，False立即执行
        @return              : 结构化命令状态
        """
        return self._move(
            degrees,
            rpm=rpm,
            direction=direction,
            acceleration=acceleration,
            deceleration=deceleration,
            mode="absolute",
            synchronized=synchronized,
        )

    def get_speed(self):
        """
        @description         : 读取实时转速并转换为带符号RPM
        @param               : 无参数
        @return              : 浮点RPM
        """
        response = self._request(common.build_read_speed())
        raw_speed = _signed_magnitude(response.data, 2)
        return float(raw_speed) if self.firmware is Firmware.EMM else raw_speed / 10.0

    def get_position(self):
        """
        @description         : 读取实时位置并转换为带符号角度
        @param               : 无参数
        @return              : 浮点角度
        """
        response = self._request(common.build_read_position())
        return self._decode_position(_signed_magnitude(response.data, 4))

    def get_target_position(self):
        """
        @description         : 读取电机目标位置并转换为带符号角度
        @param               : 无参数
        @return              : 浮点角度
        """
        response = self._request(common.build_read_target_position())
        return self._decode_position(_signed_magnitude(response.data, 4))

    def get_position_error(self):
        """
        @description         : 读取位置误差并转换为带符号角度
        @param               : 无参数
        @return              : 浮点角度误差
        """
        self.capabilities.require("position_error")
        response = self._request(common.build_read_position_error())
        raw_error = _signed_magnitude(response.data, 4)
        if self.firmware is Firmware.EMM:
            return raw_error * 360.0 / 65536.0
        return raw_error / 100.0

    def get_status(self):
        """
        @description         : 读取并解析电机状态标志位
        @param               : 无参数
        @return              : 状态字节和布尔标志字典
        """
        self.capabilities.require("motor_status")
        response = self._request(common.build_read_motor_status())
        if len(response.data) != 1:
            raise ZDTProtocolError("motor status response length is invalid")
        value = response.data[0]
        return {
            "raw": value,
            "enabled": bool(value & 0x01),
            "position_reached": bool(value & 0x02),
            "stall": bool(value & 0x04),
            "stall_protection": bool(value & 0x08),
            "left_limit": bool(value & 0x10),
            "right_limit": bool(value & 0x20),
            "power_loss": bool(value & 0x80),
        }

    def get_home_status(self):
        """
        @description         : 读取并解析回零、编码器和保护状态
        @param               : 无参数
        @return              : 回零状态字典
        """
        self.capabilities.require("home_status")
        response = self._request(common.build_read_home_status())
        if len(response.data) != 1:
            raise ZDTProtocolError("home status response length is invalid")
        value = response.data[0]
        home_bits = value & 0x0C
        home_state = {
            0x04: "running",
            0x08: "failed",
            0x00: "complete_or_idle",
        }.get(home_bits, "invalid")
        return {
            "raw": value,
            "encoder_ready": bool(value & 0x01),
            "calibration_ready": bool(value & 0x02),
            "home_running": bool(value & 0x04),
            "home_failed": bool(value & 0x08),
            "over_temperature": bool(value & 0x10),
            "over_current": bool(value & 0x20),
            "home_state": home_state,
        }

    def get_version(self):
        """
        @description         : 读取固件版本和硬件系列型号
        @param               : 无参数
        @return              : 版本信息字典
        """
        self.capabilities.require("read_version")
        response = self._request(common.build_read_version())
        if len(response.data) != 4:
            raise ZDTProtocolError("version response length is invalid")
        firmware_number = _u16(response.data[:2])
        hardware_descriptor = response.data[2]
        hardware_version = response.data[3]
        hardware_type = hardware_descriptor & 0x0F
        type_names = {0: "20", 1: "28", 2: "35", 3: "42", 4: "57", 5: "86"}
        return {
            "firmware_raw": firmware_number,
            "firmware_version": (
                f"{firmware_number // 100}."
                f"{(firmware_number // 10) % 10}.{firmware_number % 10}"
            ),
            "hardware_series": (hardware_descriptor >> 4) & 0x0F,
            "hardware_type": hardware_type,
            "hardware_type_name": type_names.get(hardware_type, "unknown"),
            "hardware_version_raw": hardware_version,
        }

    def get_phase_parameters(self):
        """
        @description         : 读取电机相电阻和相电感
        @param               : 无参数
        @return              : 毫欧和微亨字典
        """
        self.capabilities.require("read_phase_parameters")
        response = self._request(common.build_read_phase_parameters())
        if len(response.data) != 4:
            raise ZDTProtocolError("phase parameter response length is invalid")
        return {
            "resistance_milliohm": _u16(response.data[:2]),
            "inductance_microhenry": _u16(response.data[2:]),
        }

    def get_bus_voltage(self):
        """
        @description         : 读取总线电压并返回伏特
        @param               : 无参数
        @return              : 浮点伏特
        """
        self.capabilities.require("bus_voltage")
        response = self._request(common.build_read_bus_voltage())
        return _u16(response.data) / 1000.0

    def get_phase_current(self):
        """
        @description         : 读取电机实际相电流
        @param               : 无参数
        @return              : 整数毫安
        """
        self.capabilities.require("phase_current")
        response = self._request(common.build_read_phase_current())
        return _u16(response.data)

    def get_encoder_degrees(self):
        """
        @description         : 读取单圈线性编码器并转换为0至360度
        @param               : 无参数
        @return              : 浮点角度
        """
        self.capabilities.require("encoder")
        response = self._request(common.build_read_encoder())
        return _u16(response.data) * 360.0 / 65536.0

    def get_input_pulses(self):
        """
        @description         : 读取带符号输入脉冲累计值
        @param               : 无参数
        @return              : 带符号整数脉冲数
        """
        self.capabilities.require("input_pulses")
        response = self._request(common.build_read_input_pulses())
        return _signed_magnitude(response.data, 4)

    def get_temperature(self):
        """
        @description         : 对明确标记X42S/Y42的温度功能执行能力门控
        @param               : 无参数
        @return              : X57S不支持并抛出异常
        """
        self.capabilities.require("temperature")

    def get_bus_current(self):
        """
        @description         : 对明确标记X42S/Y42的总线电流功能执行能力门控
        @param               : 无参数
        @return              : X57S不支持并抛出异常
        """
        self.capabilities.require("bus_current")

    def home(self, mode=HomeMode.NEAREST, *, synchronized=False):
        """
        @description         : 触发指定模式回零
        @param mode          : HomeMode或0至5
        @param synchronized  : True缓存到同步触发，False立即执行
        @return              : 结构化命令状态
        """
        self.capabilities.require("home")
        response = self._request(common.build_home(mode, synchronized=synchronized))
        return _decode_ack(response, allow_home_no_motion=True)

    def abort_home(self):
        """
        @description         : 强制中断当前回零操作
        @param               : 无参数
        @return              : 结构化命令状态
        """
        self.capabilities.require("home")
        return self._execute(common.build_abort_home())

    def set_motor_id(self, new_motor_id, *, store=True):
        """
        @description         : 修改地址并在成功后更新当前对象绑定地址
        @param new_motor_id  : 新地址1至255
        @param store         : True永久写入电机Flash
        @return              : 结构化命令状态
        """
        self.capabilities.require("set_motor_id")
        old_motor_id = self.motor_id
        command = common.build_set_motor_id(new_motor_id, store=store)
        response = self.bus.request(
            old_motor_id,
            command,
            timeout_s=self._config.timeout_s,
            response_address=(old_motor_id, new_motor_id),
        )
        result = _decode_ack(response)
        self._config = replace(self._config, motor_id=new_motor_id)
        result["old_motor_id"] = old_motor_id
        result["motor_id"] = new_motor_id
        result["stored"] = bool(store)
        return result

    def set_microstep(self, microstep, *, store=True):
        """
        @description         : 修改细分并同步更新角度换算配置
        @param microstep     : 细分1至256
        @param store         : True永久写入电机Flash
        @return              : 结构化命令状态
        """
        self.capabilities.require("set_microstep")
        result = self._execute(common.build_set_microstep(microstep, store=store))
        self._config = replace(self._config, microstep=microstep)
        result.update({"microstep": microstep, "stored": bool(store)})
        return result

    def set_current_limit(self, current_ma, *, store=True):
        """
        @description         : 修改闭环模式最大电流
        @param current_ma    : 0至5000mA
        @param store         : True永久写入电机Flash
        @return              : 结构化命令状态
        """
        self.capabilities.require("set_current_limit")
        result = self._execute(
            common.build_set_current_limit(current_ma, store=store)
        )
        result.update({"current_ma": current_ma, "stored": bool(store)})
        return result

    def set_direction(self, direction, *, store=True):
        """
        @description         : 修改电机定义的运动正方向
        @param direction     : cw或ccw
        @param store         : True永久写入电机Flash
        @return              : 结构化命令状态
        """
        self.capabilities.require("set_direction")
        result = self._execute(common.build_set_direction(direction, store=store))
        result.update({"direction": str(direction), "stored": bool(store)})
        return result

    def read_basic_info(self):
        """
        @description         : 执行默认安全只读的版本、位置、速度和状态查询
        @param               : 无参数
        @return              : 基础信息字典
        """
        return {
            "motor_id": self.motor_id,
            "model": self.model,
            "firmware": self.firmware.value,
            "version": self.get_version(),
            "position_degrees": self.get_position(),
            "speed_rpm": self.get_speed(),
            "status": self.get_status(),
        }

    def _move(
        self,
        degrees,
        *,
        rpm,
        direction,
        acceleration,
        deceleration,
        mode,
        synchronized,
    ):
        """
        @description         : 按固件选择Emm脉冲位置或X角度位置编码
        @param degrees       : 工程角度
        @param rpm           : 最大RPM
        @param direction     : cw、ccw或None
        @param acceleration  : 固件对应加速度
        @param deceleration  : X固件减速度或None
        @param mode          : 位置参考模式
        @param synchronized  : 是否缓存同步执行
        @return              : 结构化命令状态
        """
        self.capabilities.require("position")
        if self.firmware is Firmware.EMM:
            if deceleration is not None:
                raise ZDTConfigurationError(
                    "Emm position mode does not have a separate deceleration field"
                )
            command = emm.build_position(
                degrees,
                rpm=rpm,
                direction=direction,
                acceleration=10 if acceleration is None else acceleration,
                mode=mode,
                synchronized=synchronized,
                microstep=self._config.microstep,
                step_angle_degrees=self._config.step_angle_degrees,
            )
        else:
            command = x.build_position(
                degrees,
                rpm=rpm,
                direction=direction,
                acceleration=1000 if acceleration is None else acceleration,
                deceleration=deceleration,
                mode=mode,
                synchronized=synchronized,
            )
        return self._execute(command)

    def _decode_position(self, raw_position):
        """
        @description         : 按Emm或X固件规则把原始位置换算成角度
        @param raw_position  : 带符号原始位置
        @return              : 浮点角度
        """
        if self.firmware is Firmware.EMM:
            return raw_position * 360.0 / 65536.0
        return raw_position / 10.0

    def _execute(self, command):
        """
        @description         : 发送控制命令并严格解析命令状态
        @param command       : LogicalCommand
        @return              : 结构化命令状态
        """
        return _decode_ack(self._request(command))

    def _request(self, command):
        """
        @description         : 使用对象地址和超时调用共享Bus
        @param command       : LogicalCommand
        @return              : ZDTResponse
        """
        return self.bus.request(
            self.motor_id,
            command,
            timeout_s=self._config.timeout_s,
        )
