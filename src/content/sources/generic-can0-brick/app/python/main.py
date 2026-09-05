"""Generic CAN0 Lab安全入口：默认只监听，不发送任何CAN报文。"""

import atexit
import os
import time

from arduino.app_utils import App
from generic_can import CANError, CanBus

from can_messages import MESSAGES


INTERFACE = os.getenv("GENERIC_CAN_INTERFACE", "can0")
RAW_QUEUE_SIZE = int(os.getenv("GENERIC_CAN_RAW_QUEUE_SIZE", "256"))
MESSAGE_QUEUE_SIZE = int(
    os.getenv("GENERIC_CAN_MESSAGE_QUEUE_SIZE", "64")
)

bus = CanBus(
    interface=INTERFACE,
    messages=MESSAGES,
    raw_queue_size=RAW_QUEUE_SIZE,
    message_queue_size=MESSAGE_QUEUE_SIZE,
)
next_open_attempt = 0.0
last_error = None


def raw_send_example():
    """
    @description         : 演示如何发送一帧原始标准CAN报文但不自动调用
    @param               : 无
    @return              : 成功发送的CanFrame
    """
    from generic_can import CanFrame

    return bus.send_frame(
        CanFrame(
            arbitration_id=0x123,
            data=b"\x01\x02\x03",
        )
    )


def named_send_example():
    """
    @description         : 演示通过can_messages.py定义的名称发送120RPM示例
    @param               : 无
    @return              : 成功发送的CanFrame
    """
    return bus.send("set_speed", rpm=120)


def named_receive_example():
    """
    @description         : 演示等待并解码一条名为status的反馈报文
    @param               : 无
    @return              : decode_motor_status返回的工程值字典
    """
    return bus.receive("status", timeout_s=1.0)


def format_frame(frame):
    """
    @description         : 把CanFrame格式化成适合终端教学观察的一行文本
    @param frame         : 已通过Brick验证的CanFrame
    @return              : 包含时间、帧类型、ID、长度和DATA的字符串
    """
    identifier = (
        f"0x{frame.arbitration_id:08X}"
        if frame.is_extended
        else f"0x{frame.arbitration_id:03X}"
    )
    id_kind = "EXT" if frame.is_extended else "STD"
    frame_kind = "FD+BRS" if frame.bitrate_switch else (
        "FD" if frame.is_fd else "CAN"
    )
    data = " ".join(f"{byte:02X}" for byte in frame.data) or "--"
    return (
        f"{frame.timestamp:12.6f} RX {id_kind} {frame_kind} "
        f"{identifier} [{len(frame.data)}] {data}"
    )


def close_bus():
    """
    @description         : App退出时幂等关闭接收线程和SocketCAN资源
    @param               : 无
    @return              : 无
    """
    try:
        bus.close()
    except CANError as error:
        print(f"[generic-can] close failed: {error}", flush=True)


atexit.register(close_bus)


def loop():
    """
    @description         : 重试打开已有can0并非阻塞打印收到的原始数据帧
    @param               : 无
    @return              : 无
    """
    global next_open_attempt, last_error

    now = time.monotonic()
    if not bus.is_open and now >= next_open_attempt:
        try:
            bus.open()
            last_error = None
            print(
                f"[generic-can] listening on {INTERFACE}; "
                "startup sends no CAN frames",
                flush=True,
            )
            print(f"[generic-can] {bus.describe()}", flush=True)
        except CANError as error:
            message = str(error)
            if message != last_error:
                print(
                    f"[generic-can] {INTERFACE} unavailable: {message}. "
                    "The Brick never runs ip link automatically.",
                    flush=True,
                )
                last_error = message
            next_open_attempt = now + 10.0

    if bus.is_open:
        try:
            frame = bus.receive_frame(timeout_s=0)
            if frame is not None:
                print(format_frame(frame), flush=True)
        except CANError as error:
            print(f"[generic-can] receive failed: {error}", flush=True)
            close_bus()
            next_open_attempt = time.monotonic() + 10.0

    time.sleep(0.01)


App.run(user_loop=loop)
