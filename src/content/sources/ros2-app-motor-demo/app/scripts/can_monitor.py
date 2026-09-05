#!/usr/bin/env python3
"""仅监听的精简版 ZDT candump。"""

import argparse
import time

from _common import format_frame
from zdt_motor.backends import SocketCANBackend


def parse_args():
    """
    @description         : 解析CAN监听参数
    @param               : 无参数
    @return              : argparse.Namespace
    """
    parser = argparse.ArgumentParser(description="Monitor ZDT Classical CAN frames.")
    parser.add_argument("--device", default="can0")
    parser.add_argument("--duration", type=float, default=0.0)
    parser.add_argument("--count", type=int, default=0)
    return parser.parse_args()


def main():
    """
    @description         : 监听并显示时间戳、扩展ID、电机地址、分包号和数据
    @param               : 无参数
    @return              : 成功0
    """
    args = parse_args()
    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    received = 0
    with SocketCANBackend(device=args.device) as backend:
        print(f"Monitoring {args.device}; Ctrl+C to stop", flush=True)
        try:
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    break
                frame = backend.receive(0.2)
                if frame is None:
                    continue
                print(format_frame(frame), flush=True)
                received += 1
                if args.count > 0 and received >= args.count:
                    break
        except KeyboardInterrupt:
            pass
    print(f"received={received}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
