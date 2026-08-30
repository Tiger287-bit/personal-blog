"""
@description         : 使用Python标准库封装Linux SocketCAN经典CAN扩展帧收发
@param               : 无
@return              : 无
"""

from dataclasses import dataclass
import socket
import struct


CAN_EFF_FLAG = 0x80000000
CAN_EFF_MASK = 0x1FFFFFFF
CAN_FRAME_FORMAT = "=IB3x8s"
CAN_FRAME_SIZE = struct.calcsize(CAN_FRAME_FORMAT)


@dataclass(frozen=True)
class CanFrame:
    """
    @description         : 保存一帧经典CAN报文的标识符、帧类型和有效数据
    @param arbitration_id: 11位或29位CAN标识符
    @param is_extended   : true为29位扩展帧; false为11位标准帧
    @param data          : 有效数据，长度0至8字节
    @return              : CanFrame实例
    """

    arbitration_id: int
    is_extended: bool
    data: bytes


class SocketCanTransport:
    """
    @description         : 管理指定Linux SocketCAN网络接口的经典CAN通信
    @param interface     : SocketCAN接口名称，例如can0
    @return              : SocketCanTransport实例
    """

    def __init__(self, interface):
        """
        @description         : 保存SocketCAN接口名称并初始化未连接状态
        @param interface     : SocketCAN接口名称，例如can0
        @return              : 无
        """
        if not interface:
            raise ValueError("interface must not be empty")
        self._interface = interface
        self._socket = None

    def open(self):
        """
        @description         : 创建并绑定Linux原始SocketCAN套接字
        @param               : 无
        @return              : 当前SocketCanTransport实例
        """
        if self._socket is not None:
            return self
        can_socket = socket.socket(
            socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW
        )
        try:
            can_socket.bind((self._interface,))
        except Exception:
            can_socket.close()
            raise
        self._socket = can_socket
        return self

    def close(self):
        """
        @description         : 关闭SocketCAN套接字并释放资源
        @param               : 无
        @return              : 无
        """
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def clear_receive_queue(self):
        """
        @description         : 清空套接字中尚未处理的历史CAN报文
        @param               : 无
        @return              : 被清除的报文数量
        """
        can_socket = self._require_open()
        previous_timeout = can_socket.gettimeout()
        cleared_count = 0
        try:
            can_socket.setblocking(False)
            while True:
                can_socket.recv(CAN_FRAME_SIZE)
                cleared_count += 1
        except BlockingIOError:
            pass
        finally:
            can_socket.settimeout(previous_timeout)
        return cleared_count

    def send(self, arbitration_id, data, is_extended=True):
        """
        @description         : 发送一帧经典CAN报文
        @param arbitration_id: CAN标识符，扩展帧范围0至0x1FFFFFFF
        @param data          : 待发送数据，长度0至8字节
        @param is_extended   : true发送29位扩展帧; false发送11位标准帧
        @return              : 实际写入套接字的字节数
        """
        payload = bytes(data)
        if len(payload) > 8:
            raise ValueError("classic CAN payload must not exceed 8 bytes")
        if arbitration_id < 0 or arbitration_id > CAN_EFF_MASK:
            raise ValueError("arbitration_id is out of range")
        can_id = arbitration_id | (CAN_EFF_FLAG if is_extended else 0)
        packed_frame = struct.pack(
            CAN_FRAME_FORMAT,
            can_id,
            len(payload),
            payload.ljust(8, b"\x00"),
        )
        return self._require_open().send(packed_frame)

    def receive(self, timeout_s):
        """
        @description         : 在限定时间内接收一帧经典CAN报文
        @param timeout_s     : 最大等待时间，单位秒
        @return              : 收到时返回CanFrame; 超时返回None
        """
        if timeout_s < 0:
            raise ValueError("timeout_s must not be negative")
        can_socket = self._require_open()
        previous_timeout = can_socket.gettimeout()
        try:
            can_socket.settimeout(timeout_s)
            raw_frame = can_socket.recv(CAN_FRAME_SIZE)
        except socket.timeout:
            return None
        finally:
            can_socket.settimeout(previous_timeout)
        can_id, data_length, payload = struct.unpack(
            CAN_FRAME_FORMAT, raw_frame
        )
        return CanFrame(
            arbitration_id=can_id & CAN_EFF_MASK,
            is_extended=bool(can_id & CAN_EFF_FLAG),
            data=payload[:data_length],
        )

    def _require_open(self):
        """
        @description         : 获取已打开的SocketCAN套接字
        @param               : 无
        @return              : 已绑定的socket对象
        """
        if self._socket is None:
            raise RuntimeError("SocketCAN transport is not open")
        return self._socket

    def __enter__(self):
        """
        @description         : 进入上下文管理器并打开SocketCAN套接字
        @param               : 无
        @return              : 当前SocketCanTransport实例
        """
        return self.open()

    def __exit__(self, exception_type, exception, traceback):
        """
        @description         : 退出上下文管理器并关闭SocketCAN套接字
        @param exception_type: 上下文内异常类型或None
        @param exception     : 上下文内异常对象或None
        @param traceback     : 上下文内异常堆栈或None
        @return              : false表示不抑制上下文内异常
        """
        self.close()
        return False
