#!/usr/bin/env python3
"""在两个SocketCAN对象之间执行一帧显式确认的本机回环测试。"""

import argparse

from _bootstrap import format_frame, parse_can_id, parse_hex_data
from generic_can import CANError, CanBus, CanFrame


CONFIRMATION = "SEND_SOCKETCAN_LOOPBACK_FRAME"


def main():
    """
    @description         : 用两个CanBus验证同一SocketCAN接口的本机帧回环
    @param               : 命令行参数
    @return              : 进程退出码
    """
    parser = argparse.ArgumentParser(
        description="Send one frame and receive it through another socket"
    )
    parser.add_argument("--interface", default="vcan0")
    parser.add_argument("--id", type=parse_can_id, default=0x123)
    parser.add_argument("--data", nargs="*", default=["01", "02", "03"])
    parser.add_argument("--extended", action="store_true")
    parser.add_argument("--fd", action="store_true")
    parser.add_argument("--brs", action="store_true")
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()

    if args.confirm != CONFIRMATION:
        print(f"Refusing to send; use --confirm {CONFIRMATION}", flush=True)
        return 2

    try:
        frame = CanFrame(
            arbitration_id=args.id,
            data=parse_hex_data(args.data),
            is_extended=args.extended,
            is_fd=args.fd,
            bitrate_switch=args.brs,
        )
        with CanBus(interface=args.interface) as receiver:
            with CanBus(interface=args.interface) as sender:
                sender.send_frame(frame)
                received = receiver.receive_frame(timeout_s=args.timeout)

        if received is None:
            print("Loopback timed out", flush=True)
            return 1
        print(format_frame(frame, direction="TX"), flush=True)
        print(format_frame(received, direction="RX"), flush=True)
        if (
            frame.arbitration_id,
            frame.data,
            frame.is_extended,
            frame.is_fd,
            frame.bitrate_switch,
        ) != (
            received.arbitration_id,
            received.data,
            received.is_extended,
            received.is_fd,
            received.bitrate_switch,
        ):
            print("Loopback frame mismatch", flush=True)
            return 1
        print("Loopback PASS", flush=True)
        return 0
    except (CANError, ValueError) as error:
        print(f"Loopback failed: {error}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
