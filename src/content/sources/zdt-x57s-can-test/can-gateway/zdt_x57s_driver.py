"""
@description         : 基于SocketCAN封装单台ZDT X57S FW_Emm电机控制API
@param               : 无
@return              : 无
"""

import time

from zdt_x57s_protocol import (
    ZdtProtocolError,
    arbitration_id,
    build_enable_command,
    build_speed_command,
    build_speed_query,
    build_stop_command,
    parse_ack,
    parse_speed_reply,
    validate_motor_id,
)


class ZdtReplyTimeout(TimeoutError):
    """
    @description         : 表示等待ZDT电机CAN应答超时
    @param message       : 超时说明
    @return              : ZdtReplyTimeout实例
    """

    def __init__(self, message):
        """
        @description         : 初始化ZDT应答超时异常
        @param message       : 超时说明
        @return              : 无
        """
        super().__init__(message)


class ZdtX57S:
    """
    @description         : 控制一台使用FW_Emm和固定CAN协议的ZDT X57S电机
    @param transport     : 已打开的SocketCanTransport实例
    @param motor_id      : 电机地址
    @param reply_timeout_s: 应答超时时间，单位秒
    @return              : ZdtX57S实例
    """

    def __init__(self, transport, motor_id, reply_timeout_s=0.5):
        """
        @description         : 初始化电机驱动参数
        @param transport     : 已打开的SocketCanTransport实例
        @param motor_id      : 电机地址
        @param reply_timeout_s: 应答超时时间，单位秒
        @return              : 无
        """
        if reply_timeout_s <= 0:
            raise ValueError("reply_timeout_s must be greater than zero")
        self._transport = transport
        self._motor_id = validate_motor_id(motor_id)
        self._frame_id = arbitration_id(self._motor_id)
        self._reply_timeout_s = float(reply_timeout_s)

    def enable(self, enabled=True, synchronized=False):
        """
        @description         : 使能或失能当前电机
        @param enabled       : true使能; false失能
        @param synchronized  : true等待同步启动; false立即执行
        @return              : 成功返回True
        """
        return self._send_and_wait_ack(
            build_enable_command(enabled, synchronized)
        )

    def set_speed(self, rpm, acceleration_level=0, synchronized=False):
        """
        @description         : 使用FW_Emm速度模式设置目标转速
        @param rpm           : 带符号目标转速，单位整数RPM
        @param acceleration_level: 加减速档位，范围0至255
        @param synchronized  : true等待同步启动; false立即执行
        @return              : 成功返回True
        """
        return self._send_and_wait_ack(
            build_speed_command(rpm, acceleration_level, synchronized)
        )

    def read_speed(self):
        """
        @description         : 查询编码器反馈实时转速
        @param               : 无
        @return              : 带符号实时转速，单位整数RPM
        """
        command = build_speed_query()
        self._transport.clear_receive_queue()
        self._transport.send(self._frame_id, command, is_extended=True)
        deadline = time.monotonic() + self._reply_timeout_s
        while True:
            frame = self._receive_matching_frame(deadline)
            if frame is None:
                raise ZdtReplyTimeout(
                    f"motor {self._motor_id} speed reply timed out"
                )
            if not frame.data:
                continue
            if frame.data[0] == 0x35:
                return parse_speed_reply(frame.data)
            if len(frame.data) >= 2 and frame.data[:2] == b"\x00\xEE":
                raise ZdtProtocolError("motor returned a command error")

    def stop(self, synchronized=False):
        """
        @description         : 立即停止当前电机
        @param synchronized  : true等待同步启动; false立即执行
        @return              : 成功返回True
        """
        return self._send_and_wait_ack(build_stop_command(synchronized))

    def _send_and_wait_ack(self, command):
        """
        @description         : 发送控制命令并等待相同功能码的确认应答
        @param command       : 完整ZDT命令数据
        @return              : 应答校验成功返回True
        """
        payload = bytes(command)
        self._transport.clear_receive_queue()
        self._transport.send(self._frame_id, payload, is_extended=True)
        deadline = time.monotonic() + self._reply_timeout_s
        while True:
            frame = self._receive_matching_frame(deadline)
            if frame is None:
                raise ZdtReplyTimeout(
                    f"motor {self._motor_id} command 0x{payload[0]:02X} "
                    "reply timed out"
                )
            if not frame.data:
                continue
            if len(frame.data) >= 2 and frame.data[:2] == b"\x00\xEE":
                raise ZdtProtocolError("motor returned a command error")
            if frame.data[0] == payload[0]:
                return parse_ack(frame.data, payload[0])

    def _receive_matching_frame(self, deadline):
        """
        @description         : 在截止时间前读取当前电机的29位扩展帧
        @param deadline      : time.monotonic生成的绝对截止时间
        @return              : 匹配时返回CanFrame; 超时返回None
        """
        while True:
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                return None
            frame = self._transport.receive(remaining_s)
            if frame is None:
                return None
            if frame.is_extended and frame.arbitration_id == self._frame_id:
                return frame
