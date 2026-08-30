# SPDX-License-Identifier: MIT

import json
import math
import time


PROTOCOL_VERSION = 1
ALLOWED_MODES = {"IDLE", "ROS_TELEOP", "ESTOP"}
FUTURE_TOLERANCE_MS = 2000


class ProtocolError(ValueError):
    """WebSocket 消息协议错误。"""

    def __init__(self, code, message, seq=None):
        """
        @description         : 创建包含机器可读错误码的协议异常
        @param code          : 机器可读错误码
        @param message       : 面向日志的错误说明
        @param seq           : 可选的原始消息序号
        @return              : 无返回值
        """
        super().__init__(message)
        self.code = code
        self.seq = seq


def now_ms():
    """
    @description         : 获取 Unix 毫秒时间戳
    @param               : 无参数
    @return              : 当前 Unix 毫秒时间戳
    """
    return time.time_ns() // 1_000_000


def decode_message(raw_message):
    """
    @description         : 将文本 WebSocket 帧解析为基础协议消息
    @param raw_message   : WebSocket 接收到的文本或 UTF-8 字节数据
    @return              : 已完成版本和类型检查的字典
    """
    if isinstance(raw_message, bytes):
        try:
            raw_message = raw_message.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("invalid_encoding", "message must be UTF-8") from exc

    if not isinstance(raw_message, str):
        raise ProtocolError("invalid_frame", "message must be a text frame")

    try:
        message = json.loads(raw_message)
    except json.JSONDecodeError as exc:
        raise ProtocolError("invalid_json", f"invalid JSON: {exc.msg}") from exc

    if not isinstance(message, dict):
        raise ProtocolError("invalid_message", "JSON root must be an object")

    seq = message.get("seq") if type(message.get("seq")) is int else None
    if type(message.get("version")) is not int or message["version"] != PROTOCOL_VERSION:
        raise ProtocolError(
            "unsupported_version",
            f"version must be {PROTOCOL_VERSION}",
            seq,
        )

    message_type = message.get("type")
    if not isinstance(message_type, str) or not message_type:
        raise ProtocolError("invalid_type", "type must be a non-empty string", seq)

    return message


def validate_hello(message):
    """
    @description         : 校验 ROS 2 客户端握手消息
    @param message       : 已解析的基础协议消息
    @return              : 客户端节点名称
    """
    if message["type"] != "hello":
        raise ProtocolError("hello_required", "first message must be hello")
    if message.get("role") != "ros2":
        raise ProtocolError("invalid_role", "hello role must be ros2")

    node = message.get("node")
    if not isinstance(node, str) or not node.strip() or len(node) > 128:
        raise ProtocolError("invalid_node", "hello node must contain 1 to 128 characters")

    return node.strip()


def validate_sequence(message, last_sequence):
    """
    @description         : 校验命令序号为非负且严格递增
    @param message       : 已解析的协议消息
    @param last_sequence : 当前连接最近接受的序号
    @return              : 已校验的新序号
    """
    sequence = message.get("seq")
    if type(sequence) is not int or sequence < 0:
        raise ProtocolError("invalid_seq", "seq must be a non-negative integer")
    if sequence <= last_sequence:
        raise ProtocolError(
            "non_monotonic_seq",
            f"seq must be greater than {last_sequence}",
            sequence,
        )
    return sequence


def validate_timestamp(message, maximum_age_ms, current_timestamp_ms=None):
    """
    @description             : 校验消息时间戳并拒绝过期或明显来自未来的消息
    @param message           : 已解析的协议消息
    @param maximum_age_ms    : 允许的最大消息年龄，None 表示不检查过期
    @param current_timestamp_ms : 测试时可注入的当前 Unix 毫秒时间戳
    @return                  : 已校验的消息时间戳
    """
    timestamp = message.get("timestamp_ms")
    sequence = message.get("seq") if type(message.get("seq")) is int else None
    if type(timestamp) is not int or timestamp <= 0:
        raise ProtocolError(
            "invalid_timestamp",
            "timestamp_ms must be a positive integer",
            sequence,
        )

    current = now_ms() if current_timestamp_ms is None else current_timestamp_ms
    if timestamp > current + FUTURE_TOLERANCE_MS:
        raise ProtocolError(
            "future_timestamp",
            "timestamp_ms is too far in the future",
            sequence,
        )
    if maximum_age_ms is not None and current - timestamp > maximum_age_ms:
        raise ProtocolError(
            "stale_command",
            f"message age exceeds {maximum_age_ms} ms",
            sequence,
        )
    return timestamp


def validate_heartbeat(message):
    """
    @description         : 校验应用层心跳消息
    @param message       : 已解析的协议消息
    @return              : 心跳时间戳
    """
    if message["type"] != "heartbeat":
        raise ProtocolError("invalid_type", "message type must be heartbeat")
    return validate_timestamp(message, None)


def validate_mode_change(message):
    """
    @description         : 校验模式切换请求
    @param message       : 已解析的协议消息
    @return              : 已校验的目标模式
    """
    if message["type"] != "mode_change":
        raise ProtocolError("invalid_type", "message type must be mode_change")
    validate_timestamp(message, None)

    mode = message.get("mode")
    if mode not in ALLOWED_MODES:
        raise ProtocolError(
            "invalid_mode",
            f"mode must be one of {sorted(ALLOWED_MODES)}",
            message.get("seq"),
        )
    return mode


def validate_cmd_vel(message, mode, limits, command_timeout_ms, current_timestamp_ms=None):
    """
    @description             : 校验速度指令字段、模式、范围和时效性
    @param message           : 已解析的 cmd_vel 消息
    @param mode              : 当前底盘模式
    @param limits            : vx、vy、wz 的绝对值上限
    @param command_timeout_ms : 允许的最大指令年龄
    @param current_timestamp_ms : 测试时可注入的当前 Unix 毫秒时间戳
    @return                  : 规范化后的速度指令字典
    """
    if message["type"] != "cmd_vel":
        raise ProtocolError("invalid_type", "message type must be cmd_vel")

    timestamp = validate_timestamp(message, command_timeout_ms, current_timestamp_ms)
    values = {}
    for field_name in ("vx", "vy", "wz"):
        field_value = message.get(field_name)
        if isinstance(field_value, bool) or not isinstance(field_value, (int, float)):
            raise ProtocolError(
                "invalid_field",
                f"{field_name} must be a finite number",
                message.get("seq"),
            )
        field_value = float(field_value)
        if not math.isfinite(field_value):
            raise ProtocolError(
                "invalid_field",
                f"{field_name} must be a finite number",
                message.get("seq"),
            )
        if abs(field_value) > limits[field_name]:
            raise ProtocolError(
                "out_of_range",
                f"abs({field_name}) must be <= {limits[field_name]}",
                message.get("seq"),
            )
        values[field_name] = field_value

    if mode != "ROS_TELEOP" and any(value != 0.0 for value in values.values()):
        raise ProtocolError(
            "mode_denied",
            "non-zero cmd_vel requires ROS_TELEOP mode",
            message.get("seq"),
        )

    return {
        "seq": message["seq"],
        "timestamp_ms": timestamp,
        **values,
    }


def build_message(message_type, sequence=None, timestamp_ms=None, **fields):
    """
    @description         : 构造统一版本的出站协议消息
    @param message_type  : 消息类型
    @param sequence      : 可选的消息序号
    @param timestamp_ms  : 可选的 Unix 毫秒时间戳
    @param fields        : 需要附加的消息字段
    @return              : 可直接 JSON 序列化的消息字典
    """
    message = {
        "version": PROTOCOL_VERSION,
        "type": message_type,
        "timestamp_ms": now_ms() if timestamp_ms is None else timestamp_ms,
    }
    if sequence is not None:
        message["seq"] = sequence
    message.update(fields)
    return message
