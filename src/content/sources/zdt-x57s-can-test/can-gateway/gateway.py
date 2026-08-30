#!/usr/bin/env python3
"""
@description         : 向App Lab Custom Brick提供受鉴权的Linux SocketCAN网关
@param               : 无
@return              : 无
"""

import argparse
import hmac
import json
import os
import socketserver
import subprocess
import threading
import time

from socketcan_transport import SocketCanTransport
from zdt_x57s_driver import ZdtX57S


PROTOCOL_VERSION = 1
MOTION_CONFIRMATION = "RUN_ZDT_X57S_V1_0"
MIN_MOTOR_ID = 1
MAX_MOTOR_ID = 255
MAX_REQUEST_BYTES = 16384


class GatewayRequestError(RuntimeError):
    """
    @description         : 表示网关请求字段、鉴权或方法不合法
    @param code          : 稳定错误码
    @param message       : 错误说明
    @return              : GatewayRequestError实例
    """

    def __init__(self, code, message):
        """
        @description         : 初始化网关请求异常
        @param code          : 稳定错误码
        @param message       : 错误说明
        @return              : 无
        """
        super().__init__(message)
        self.code = str(code)


class MotorGateway:
    """
    @description         : 串行化CAN操作并执行电机参数与安全边界校验
    @param interface     : SocketCAN接口名称
    @param token         : Brick和网关共享的随机鉴权令牌
    @param max_rpm       : 允许的最大绝对转速
    @param reply_timeout_s: 单帧电机应答超时时间
    @param command_timeout_s: 非零速度命令看门狗超时时间
    @return              : MotorGateway实例
    """

    def __init__(
        self,
        interface,
        token,
        max_rpm,
        reply_timeout_s,
        command_timeout_s=0.5,
    ):
        """
        @description         : 初始化网关配置和CAN互斥锁
        @param interface     : SocketCAN接口名称
        @param token         : 共享鉴权令牌
        @param max_rpm       : 允许的最大绝对转速
        @param reply_timeout_s: 单帧电机应答超时时间
        @param command_timeout_s: 非零速度命令看门狗超时时间
        @return              : 无
        """
        if not token:
            raise ValueError("gateway token must not be empty")
        if max_rpm < 1 or max_rpm > 3000:
            raise ValueError("max_rpm must be in range 1-3000")
        if reply_timeout_s <= 0:
            raise ValueError("reply_timeout_s must be greater than zero")
        if command_timeout_s < 0.1 or command_timeout_s > 5.0:
            raise ValueError("command_timeout_s must be in range 0.1-5.0")
        self.interface = str(interface)
        self.max_rpm = int(max_rpm)
        self.reply_timeout_s = float(reply_timeout_s)
        self.command_timeout_s = float(command_timeout_s)
        self._token = str(token)
        self._can_lock = threading.Lock()
        self._watchdog_lock = threading.Lock()
        self._watchdogs = {}
        self._started_at = time.monotonic()

    def dispatch(self, request):
        """
        @description         : 校验请求并分发到允许的CAN网关方法
        @param request       : 反序列化后的请求字典
        @return              : 方法执行结果字典
        """
        if not isinstance(request, dict):
            raise GatewayRequestError("invalid_request", "request must be an object")
        if request.get("version") != PROTOCOL_VERSION:
            raise GatewayRequestError(
                "version_mismatch", "unsupported protocol version"
            )
        supplied_token = str(request.get("token", ""))
        if not hmac.compare_digest(supplied_token, self._token):
            raise GatewayRequestError("unauthorized", "invalid gateway token")
        params = request.get("params", {})
        if not isinstance(params, dict):
            raise GatewayRequestError("invalid_params", "params must be an object")

        methods = {
            "status": self.status,
            "read_speed": self.read_speed,
            "enable": self.enable,
            "disable": self.disable,
            "set_speed": self.set_speed,
            "stop": self.stop,
            "timed_speed_test": self.timed_speed_test,
        }
        method_name = request.get("method")
        method = methods.get(method_name)
        if method is None:
            raise GatewayRequestError("unknown_method", "method is not allowed")
        return method(params)

    def status(self, params):
        """
        @description         : 返回网关和can0状态且不发送CAN报文
        @param params        : 空参数字典
        @return              : 网关状态字典
        """
        del params
        return {
            "interface": self.interface,
            "interface_state": self._read_interface_state(),
            "max_rpm": self.max_rpm,
            "command_timeout_ms": int(self.command_timeout_s * 1000),
            "motor_id_range": [MIN_MOTOR_ID, MAX_MOTOR_ID],
            "uptime_s": round(time.monotonic() - self._started_at, 3),
        }

    def read_speed(self, params):
        """
        @description         : 查询请求中唯一一台电机的实时转速
        @param params        : 包含motor_id的参数字典
        @return              : 当前电机地址和实时RPM字典
        """
        motor_id = self._validate_motor_id(params.get("motor_id"))

        def operation(transport):
            """
            @description         : 在SocketCAN会话中读取当前唯一一台电机速度
            @param transport     : 已打开的SocketCanTransport实例
            @return              : 带符号实时RPM
            """
            motor = ZdtX57S(transport, motor_id, self.reply_timeout_s)
            return motor.read_speed()

        return {
            "motor_id": motor_id,
            "speed_rpm": self._with_can(operation),
        }

    def enable(self, params):
        """
        @description         : 校验运动确认后使能单台电机
        @param params        : 包含motor_id和confirmation的字典
        @return              : 成功状态字典
        """
        self._require_motion_confirmation(params)
        motor_id = self._validate_motor_id(params.get("motor_id"))
        return self._single_motor_command(
            motor_id, lambda motor: motor.enable(True)
        )

    def disable(self, params):
        """
        @description         : 失能单台电机
        @param params        : 包含motor_id的字典
        @return              : 成功状态字典
        """
        motor_id = self._validate_motor_id(params.get("motor_id"))
        self._cancel_watchdog(motor_id)
        return self._single_motor_command(
            motor_id, lambda motor: motor.enable(False)
        )

    def set_speed(self, params):
        """
        @description         : 校验运动确认、转速和加速度后控制单台电机
        @param params        : 包含motor_id、rpm、acceleration_level和confirmation
        @return              : 成功状态字典
        """
        self._require_motion_confirmation(params)
        motor_id = self._validate_motor_id(params.get("motor_id"))
        rpm = self._validate_rpm(params.get("rpm"))
        acceleration = self._validate_acceleration(
            params.get("acceleration_level")
        )
        result = self._single_motor_command(
            motor_id,
            lambda motor: motor.set_speed(rpm, acceleration),
        )
        if rpm == 0:
            self._cancel_watchdog(motor_id)
        else:
            self._arm_watchdog(motor_id)
        result["watchdog_timeout_ms"] = (
            0 if rpm == 0 else int(self.command_timeout_s * 1000)
        )
        return result

    def stop(self, params):
        """
        @description         : 对单台电机发送零速并尽力执行停止和失能
        @param params        : 包含motor_id的字典
        @return              : 三条安全命令的独立结果
        """
        motor_id = self._validate_motor_id(params.get("motor_id"))
        self._cancel_watchdog(motor_id)
        return self._with_can(
            lambda transport: self._safe_stop_motor(transport, motor_id)
        )

    def timed_speed_test(self, params):
        """
        @description         : 运行最多5秒的单电机测试并在finally阶段发送零速停车
        @param params        : 电机地址、转速、加速度、时长和确认口令
        @return              : 实时速度采样及停车结果
        """
        self._require_motion_confirmation(params)
        motor_id = self._validate_motor_id(params.get("motor_id"))
        self._cancel_watchdog(motor_id)
        rpm = self._validate_rpm(params.get("rpm"), allow_zero=False)
        acceleration = self._validate_acceleration(
            params.get("acceleration_level")
        )
        try:
            duration_s = float(params.get("duration_s"))
        except (TypeError, ValueError) as error:
            raise GatewayRequestError(
                "invalid_params", "duration_s must be a number"
            ) from error
        if duration_s < 0.2 or duration_s > 5.0:
            raise GatewayRequestError(
                "invalid_params", "duration_s must be in range 0.2-5.0"
            )

        def operation(transport):
            """
            @description         : 执行使能、限时速度运行、反馈采样和finally安全停车
            @param transport     : 已打开的SocketCanTransport实例
            @return              : 测试结果字典
            """
            motor = ZdtX57S(transport, motor_id, self.reply_timeout_s)
            samples = []
            test_error = None
            shutdown = None
            try:
                motor.enable(True)
                motor.set_speed(rpm, acceleration)
                deadline = time.monotonic() + duration_s
                while time.monotonic() < deadline:
                    samples.append(motor.read_speed())
                    time.sleep(0.2)
            except Exception as error:
                test_error = str(error)
            finally:
                shutdown = self._safe_stop_motor(transport, motor_id)

            if test_error is not None:
                raise GatewayRequestError("motor_test_failed", test_error)
            return {
                "motor_id": motor_id,
                "target_rpm": rpm,
                "samples_rpm": samples,
                "shutdown": shutdown,
            }

        return self._with_can(operation)

    def _arm_watchdog(self, motor_id):
        """
        @description         : 为非零速度命令创建一次性通信超时安全停车定时器
        @param motor_id      : 已校验的电机地址
        @return              : 无
        """
        generation = object()
        timer = threading.Timer(
            self.command_timeout_s,
            self._watchdog_expired,
            args=(motor_id, generation),
        )
        timer.daemon = True
        with self._watchdog_lock:
            previous = self._watchdogs.pop(motor_id, None)
            if previous is not None:
                previous[0].cancel()
            self._watchdogs[motor_id] = (timer, generation)
        timer.start()

    def _cancel_watchdog(self, motor_id):
        """
        @description         : 取消指定电机尚未触发的速度命令看门狗
        @param motor_id      : 已校验的电机地址
        @return              : 无
        """
        with self._watchdog_lock:
            current = self._watchdogs.pop(motor_id, None)
        if current is not None:
            current[0].cancel()

    def _watchdog_expired(self, motor_id, generation):
        """
        @description         : 速度命令超时后验证定时器代次并执行安全停车
        @param motor_id      : 超时电机地址
        @param generation    : 防止旧定时器误停新命令的代次对象
        @return              : 无
        """
        with self._watchdog_lock:
            current = self._watchdogs.get(motor_id)
            if current is None or current[1] is not generation:
                return
            self._watchdogs.pop(motor_id, None)
        try:
            result = self._with_can(
                lambda transport: self._safe_stop_motor(
                    transport, motor_id
                )
            )
            print(
                f"motor {motor_id} command watchdog expired: {result}",
                flush=True,
            )
        except Exception as error:
            print(
                f"motor {motor_id} watchdog stop failed: {error}",
                flush=True,
            )

    def _single_motor_command(self, motor_id, command):
        """
        @description         : 在独占CAN会话中执行单台电机命令
        @param motor_id      : 已校验的电机地址
        @param command       : 接受ZdtX57S实例的可调用对象
        @return              : 成功状态字典
        """
        def operation(transport):
            """
            @description         : 创建电机对象并执行传入命令
            @param transport     : 已打开的SocketCanTransport实例
            @return              : 成功状态字典
            """
            motor = ZdtX57S(transport, motor_id, self.reply_timeout_s)
            command(motor)
            return {"motor_id": motor_id, "accepted": True}

        return self._with_can(operation)

    def _safe_stop_motor(self, transport, motor_id):
        """
        @description         : 以F6零速为主路径并继续尝试FE停止和F3失能
        @param transport     : 已打开的SocketCanTransport实例
        @param motor_id      : 已校验的电机地址
        @return              : 每条命令的成功状态或错误文本
        """
        motor = ZdtX57S(transport, motor_id, self.reply_timeout_s)
        result = {}
        actions = (
            ("zero_speed", lambda: motor.set_speed(0, 0)),
            ("stop", lambda: motor.stop(False)),
            ("disable", lambda: motor.enable(False)),
        )
        for name, action in actions:
            try:
                action()
                result[name] = {"ok": True}
            except Exception as error:
                result[name] = {"ok": False, "error": str(error)}
        return result

    def _with_can(self, operation):
        """
        @description         : 串行打开can0、执行操作并可靠关闭SocketCAN
        @param operation     : 接受SocketCanTransport实例的可调用对象
        @return              : 操作返回值
        """
        with self._can_lock:
            try:
                with SocketCanTransport(self.interface) as transport:
                    return operation(transport)
            except GatewayRequestError:
                raise
            except Exception as error:
                raise GatewayRequestError("can_error", str(error)) from error

    def _validate_motor_id(self, motor_id):
        """
        @description         : 校验第二代FW_Emm协议支持的单电机地址
        @param motor_id      : 待校验地址
        @return              : 合法整数地址
        """
        if isinstance(motor_id, bool) or not isinstance(motor_id, int):
            raise GatewayRequestError(
                "invalid_params", "motor_id must be an integer"
            )
        if motor_id < MIN_MOTOR_ID or motor_id > MAX_MOTOR_ID:
            raise GatewayRequestError(
                "invalid_params", "motor_id must be in range 1-255"
            )
        return motor_id

    def _validate_rpm(self, rpm, allow_zero=True):
        """
        @description         : 将目标转速限制在网关配置的安全范围
        @param rpm           : 待校验带符号转速
        @param allow_zero    : 是否允许零转速
        @return              : 合法整数RPM
        """
        try:
            normalized_rpm = int(rpm)
        except (TypeError, ValueError) as error:
            raise GatewayRequestError(
                "invalid_params", "rpm must be an integer"
            ) from error
        if abs(normalized_rpm) > self.max_rpm:
            raise GatewayRequestError(
                "invalid_params",
                f"absolute rpm must not exceed {self.max_rpm}",
            )
        if not allow_zero and normalized_rpm == 0:
            raise GatewayRequestError(
                "invalid_params", "rpm must not be zero for a motion test"
            )
        return normalized_rpm

    def _validate_acceleration(self, acceleration_level):
        """
        @description         : 校验FW_Emm加减速档位
        @param acceleration_level: 待校验档位
        @return              : 合法整数档位
        """
        try:
            normalized_acceleration = int(acceleration_level)
        except (TypeError, ValueError) as error:
            raise GatewayRequestError(
                "invalid_params", "acceleration_level must be an integer"
            ) from error
        if normalized_acceleration < 0 or normalized_acceleration > 255:
            raise GatewayRequestError(
                "invalid_params",
                "acceleration_level must be in range 0-255",
            )
        return normalized_acceleration

    def _require_motion_confirmation(self, params):
        """
        @description         : 要求运动请求携带固定人工确认口令
        @param params        : 网关方法参数字典
        @return              : 校验成功无返回值
        """
        if params.get("confirmation") != MOTION_CONFIRMATION:
            raise GatewayRequestError(
                "confirmation_required",
                "motion confirmation must be " + MOTION_CONFIRMATION,
            )

    def _read_interface_state(self):
        """
        @description         : 使用ip工具只读获取SocketCAN接口摘要
        @param               : 无
        @return              : 接口状态文本或错误说明
        """
        try:
            result = subprocess.run(
                ["ip", "-brief", "link", "show", self.interface],
                check=False,
                capture_output=True,
                text=True,
                timeout=1.0,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return "unavailable: " + str(error)
        output = (result.stdout or result.stderr).strip()
        return output or "not found"


class GatewayTcpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """
    @description         : 支持并发连接且进程退出时关闭工作线程的TCP服务器
    @param server_address: 监听地址和端口
    @param handler_class : 请求处理器类型
    @return              : GatewayTcpServer实例
    """

    allow_reuse_address = True
    daemon_threads = True


class GatewayRequestHandler(socketserver.StreamRequestHandler):
    """
    @description         : 读取单条JSON请求并返回单条JSON响应
    @param               : 由socketserver创建
    @return              : 无
    """

    def handle(self):
        """
        @description         : 限长读取、解析、分发并编码网关响应
        @param               : 无
        @return              : 无
        """
        request_id = None
        try:
            raw_request = self.rfile.readline(MAX_REQUEST_BYTES + 1)
            if not raw_request or len(raw_request) > MAX_REQUEST_BYTES:
                raise GatewayRequestError(
                    "invalid_request", "request is empty or too large"
                )
            request = json.loads(raw_request.decode("utf-8"))
            if isinstance(request, dict):
                request_id = request.get("request_id")
            result = self.server.gateway.dispatch(request)
            response = {
                "version": PROTOCOL_VERSION,
                "request_id": request_id,
                "ok": True,
                "result": result,
            }
        except GatewayRequestError as error:
            response = self._error_response(request_id, error.code, str(error))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            response = self._error_response(
                request_id, "invalid_json", str(error)
            )
        except Exception as error:
            response = self._error_response(
                request_id, "internal_error", str(error)
            )
        self.wfile.write(
            (
                json.dumps(response, separators=(",", ":")) + "\n"
            ).encode("utf-8")
        )

    def _error_response(self, request_id, code, message):
        """
        @description         : 构造统一失败响应
        @param request_id    : 请求关联ID或None
        @param code          : 稳定错误码
        @param message       : 错误说明
        @return              : 失败响应字典
        """
        return {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": False,
            "error": {"code": str(code), "message": str(message)},
        }


def read_token(token_file):
    """
    @description         : 从仅当前用户可读的文件加载网关鉴权令牌
    @param token_file    : 令牌文件路径
    @return              : 非空令牌字符串
    """
    with open(token_file, "r", encoding="utf-8") as token_stream:
        token = token_stream.read().strip()
    if not token:
        raise ValueError("gateway token file is empty")
    return token


def parse_args():
    """
    @description         : 解析Linux原生CAN网关启动参数
    @param               : 无
    @return              : argparse.Namespace参数对象
    """
    parser = argparse.ArgumentParser(
        description="Native SocketCAN gateway for the ZDT X57S CAN Brick."
    )
    parser.add_argument("--interface", default="can0")
    parser.add_argument("--bind", default="172.17.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--max-rpm", type=int, default=60)
    parser.add_argument("--reply-timeout", type=float, default=0.5)
    parser.add_argument("--command-timeout", type=float, default=0.5)
    parser.add_argument(
        "--token-file",
        default=os.path.join(os.path.dirname(__file__), ".gateway-token"),
    )
    return parser.parse_args()


def main():
    """
    @description         : 创建MotorGateway并持续处理Brick请求
    @param               : 无
    @return              : 正常退出返回0
    """
    args = parse_args()
    gateway = MotorGateway(
        interface=args.interface,
        token=read_token(args.token_file),
        max_rpm=args.max_rpm,
        reply_timeout_s=args.reply_timeout,
        command_timeout_s=args.command_timeout,
    )
    with GatewayTcpServer(
        (args.bind, args.port), GatewayRequestHandler
    ) as server:
        server.gateway = gateway
        print(
            f"ZDT X57S CAN gateway listening on {args.bind}:{args.port}; "
            f"interface={args.interface}; max_rpm={args.max_rpm}",
            flush=True,
        )
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            print("ZDT X57S CAN gateway stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
