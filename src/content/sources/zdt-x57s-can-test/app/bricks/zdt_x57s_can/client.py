"""
@description         : 封装单台ZDT X57S电机到Linux原生CAN网关的可复用Brick API
@param               : 无
@return              : 无
"""

import json
import os
import socket
import threading
import uuid

from arduino.app_utils import brick


PROTOCOL_VERSION = 1
MAX_RESPONSE_BYTES = 65536
MOTION_CONFIRMATION = "RUN_ZDT_X57S_V1_0"


class ZdtX57SCanError(RuntimeError):
    """
    @description         : 表示Brick参数、连接或Linux CAN网关返回的错误
    @param message       : 错误说明
    @return              : ZdtX57SCanError实例
    """

    def __init__(self, message):
        """
        @description         : 初始化Brick异常
        @param message       : 错误说明
        @return              : 无
        """
        super().__init__(message)


def validate_motor_id(motor_id):
    """
    @description         : 校验单台ZDT电机对象绑定的协议地址
    @param motor_id      : 整数电机地址，范围1至255
    @return              : 合法电机地址
    """
    if isinstance(motor_id, bool) or not isinstance(motor_id, int):
        raise ZdtX57SCanError("motor_id must be an integer")
    if motor_id < 1 or motor_id > 255:
        raise ZdtX57SCanError("motor_id must be in range 1-255")
    return motor_id


@brick
class ZdtX57SCan:
    """
    @description         : 表示一台使用第二代FW_Emm固定CAN协议的ZDT X57S电机
    @param motor_id      : 当前对象绑定的电机地址，范围1至255
    @param host          : Linux原生CAN网关地址; 默认读取环境变量
    @param port          : Linux原生CAN网关端口; 默认读取环境变量
    @param token         : 网关鉴权令牌; 默认读取环境变量
    @param timeout_s     : 单次请求超时时间; 默认读取环境变量
    @return              : 单台ZdtX57SCan电机对象
    """

    def __init__(
        self,
        motor_id,
        host=None,
        port=None,
        token=None,
        timeout_s=None,
    ):
        """
        @description         : 绑定一台电机地址并初始化网关连接参数
        @param motor_id      : 当前对象绑定的电机地址，范围1至255
        @param host          : Linux原生CAN网关地址
        @param port          : Linux原生CAN网关端口
        @param token         : 网关鉴权令牌
        @param timeout_s     : 单次请求超时时间
        @return              : 无
        """
        self._motor_id = validate_motor_id(motor_id)
        self._host = host or os.getenv(
            "ZDT_CAN_GATEWAY_HOST", "msgpack-rpc-router"
        )
        self._port = int(port or os.getenv("ZDT_CAN_GATEWAY_PORT", "8766"))
        self._token = token or os.getenv("ZDT_CAN_GATEWAY_TOKEN", "")
        self._timeout_s = float(
            timeout_s or os.getenv("ZDT_CAN_REQUEST_TIMEOUT_S", "1.5")
        )
        self._lock = threading.Lock()

        if not self._token or self._token == "replace-me":
            raise ZdtX57SCanError("ZDT CAN gateway token is not configured")
        if self._port < 1 or self._port > 65535:
            raise ZdtX57SCanError("gateway port must be in range 1-65535")
        if self._timeout_s <= 0:
            raise ZdtX57SCanError("request timeout must be greater than zero")

    @property
    def motor_id(self):
        """
        @description         : 获取当前对象绑定的电机地址
        @param               : 无参数
        @return              : 范围1至255的电机地址
        """
        return self._motor_id

    def status(self):
        """
        @description         : 查询Linux原生CAN网关状态且不发送CAN帧
        @param               : 无参数
        @return              : 包含本对象地址和网关运行状态的字典
        """
        result = dict(self._call("status", {}))
        result["motor_id"] = self._motor_id
        return result

    def read_speed(self):
        """
        @description         : 读取当前对象绑定电机的实时转速
        @param               : 无参数
        @return              : 带符号实时转速，单位整数RPM
        """
        result = self._call("read_speed", {"motor_id": self._motor_id})
        if result.get("motor_id") != self._motor_id:
            raise ZdtX57SCanError("CAN gateway returned a different motor_id")
        speed_rpm = result.get("speed_rpm")
        if isinstance(speed_rpm, bool) or not isinstance(speed_rpm, int):
            raise ZdtX57SCanError("CAN gateway returned an invalid speed_rpm")
        return speed_rpm

    def probe(self):
        """
        @description         : 读取当前单台电机速度并返回便于诊断的结构化结果
        @param               : 无参数
        @return              : 包含motor_id和speed_rpm的字典
        """
        return {"motor_id": self._motor_id, "speed_rpm": self.read_speed()}

    def enable(self, confirmation):
        """
        @description         : 在显式确认后使能当前单台电机
        @param confirmation  : 固定运动确认口令
        @return              : 网关执行结果
        """
        return self._motion_call("enable", {}, confirmation)

    def disable(self):
        """
        @description         : 失能当前单台电机
        @param               : 无参数
        @return              : 网关执行结果
        """
        return self._call("disable", {"motor_id": self._motor_id})

    def set_speed(self, rpm, acceleration_level, confirmation):
        """
        @description         : 在显式确认后设置当前单台电机转速
        @param rpm           : 带符号目标转速
        @param acceleration_level: 加减速档位0至255
        @param confirmation  : 固定运动确认口令
        @return              : 网关执行结果
        """
        return self._motion_call(
            "set_speed",
            {
                "rpm": int(rpm),
                "acceleration_level": int(acceleration_level),
            },
            confirmation,
        )

    def stop(self):
        """
        @description         : 向当前单台电机依次发送零速、停止和失能安全命令
        @param               : 无参数
        @return              : 包含各安全命令结果的字典
        """
        return self._call("stop", {"motor_id": self._motor_id})

    def timed_speed_test(
        self,
        rpm,
        acceleration_level,
        duration_s,
        confirmation,
    ):
        """
        @description         : 对当前单台电机执行限时测试并在finally阶段安全停车
        @param rpm           : 带符号目标转速
        @param acceleration_level: 加减速档位0至255
        @param duration_s    : 测试持续时间0.2至5秒
        @param confirmation  : 固定运动确认口令
        @return              : 采样速度和停车结果
        """
        return self._motion_call(
            "timed_speed_test",
            {
                "rpm": int(rpm),
                "acceleration_level": int(acceleration_level),
                "duration_s": float(duration_s),
            },
            confirmation,
            timeout_s=max(self._timeout_s, float(duration_s) + 4.0),
        )

    def _motion_call(self, method, params, confirmation, timeout_s=None):
        """
        @description         : 绑定对象地址并校验运动确认后调用网关控制方法
        @param method        : 网关方法名称
        @param params        : 不含motor_id的网关方法参数
        @param confirmation  : 固定运动确认口令
        @param timeout_s     : 可选的本次请求超时时间
        @return              : 网关结果字典
        """
        if confirmation != MOTION_CONFIRMATION:
            raise ZdtX57SCanError(
                "motion confirmation must be " + MOTION_CONFIRMATION
            )
        request_params = dict(params)
        request_params["motor_id"] = self._motor_id
        request_params["confirmation"] = confirmation
        return self._call(method, request_params, timeout_s=timeout_s)

    def _call(self, method, params, timeout_s=None):
        """
        @description         : 通过换行分隔JSON请求调用Linux原生CAN网关
        @param method        : 网关方法名称
        @param params        : 网关方法参数字典
        @param timeout_s     : 可选的本次请求超时时间
        @return              : 网关成功结果
        """
        request_id = uuid.uuid4().hex
        request = {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "token": self._token,
            "method": str(method),
            "params": dict(params),
        }
        payload = (
            json.dumps(request, separators=(",", ":"), ensure_ascii=False)
            + "\n"
        ).encode("utf-8")
        effective_timeout = float(timeout_s or self._timeout_s)

        try:
            with self._lock:
                with socket.create_connection(
                    (self._host, self._port), timeout=effective_timeout
                ) as connection:
                    connection.settimeout(effective_timeout)
                    connection.sendall(payload)
                    response_payload = self._receive_line(connection)
        except (OSError, TimeoutError) as error:
            raise ZdtX57SCanError(
                f"CAN gateway connection failed: {error}"
            ) from error

        try:
            response = json.loads(response_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ZdtX57SCanError("CAN gateway returned invalid JSON") from error

        if response.get("version") != PROTOCOL_VERSION:
            raise ZdtX57SCanError("CAN gateway protocol version mismatch")
        if response.get("request_id") != request_id:
            raise ZdtX57SCanError("CAN gateway request_id mismatch")
        if response.get("ok") is not True:
            error_info = response.get("error") or {}
            error_code = error_info.get("code", "gateway_error")
            error_message = error_info.get("message", "unknown gateway error")
            raise ZdtX57SCanError(f"{error_code}: {error_message}")
        return response.get("result", {})

    def _receive_line(self, connection):
        """
        @description         : 从TCP连接读取一条有长度上限的换行分隔JSON响应
        @param connection    : 已连接的socket对象
        @return              : 不含换行符的响应字节
        """
        chunks = bytearray()
        while len(chunks) <= MAX_RESPONSE_BYTES:
            chunk = connection.recv(4096)
            if not chunk:
                break
            chunks.extend(chunk)
            newline_index = chunks.find(b"\n")
            if newline_index >= 0:
                return bytes(chunks[:newline_index])
        if len(chunks) > MAX_RESPONSE_BYTES:
            raise ZdtX57SCanError("CAN gateway response is too large")
        raise ZdtX57SCanError("CAN gateway closed without a complete response")
