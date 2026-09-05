#!/usr/bin/env python3
"""显式确认后发送一帧用户指定的原始CAN报文。"""

import argparse

from _bootstrap import format_frame, parse_can_id, parse_hex_data
from generic_can import CANError, CanBus, CanFrame


CONFIRMATION = "SEND_GENERIC_CAN_FRAME"


def main():
    """
    @description         : 从命令行构造CanFrame并在确认字符串正确时发送
    @param               : 命令行参数
    @return              : 进程退出码
    """
    parser = argparse.ArgumentParser(
        description="Send one explicitly confirmed raw CAN frame"
    )
    parser.add_argument("--interface", default="can0")
    parser.add_argument("--id", required=True, type=parse_can_id)
    parser.add_argument("--data", nargs="*", default=[])
    parser.add_argument("--extended", action="store_true")
    parser.add_argument("--fd", action="store_true")
    parser.add_argument("--brs", action="store_true")
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
        with CanBus(interface=args.interface) as bus:
            bus.send_frame(frame)
        print(format_frame(frame, direction="TX"), flush=True)
        return 0
    except (CANError, ValueError) as error:
        print(f"CAN send failed: {error}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
