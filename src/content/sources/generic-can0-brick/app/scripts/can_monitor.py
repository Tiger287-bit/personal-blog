#!/usr/bin/env python3
"""只读打印指定SocketCAN接口收到的所有数据帧。"""

import argparse

from _bootstrap import format_frame
from generic_can import CANError, CanBus


def main():
    """
    @description         : 打开已有SocketCAN接口并持续显示原始数据帧
    @param               : 命令行参数
    @return              : 进程退出码
    """
    parser = argparse.ArgumentParser(
        description="Read-only Generic CAN frame monitor"
    )
    parser.add_argument("--interface", default="can0")
    args = parser.parse_args()

    try:
        with CanBus(interface=args.interface) as bus:
            print(
                f"Listening on {args.interface}; Ctrl+C to stop",
                flush=True,
            )
            while True:
                frame = bus.receive_frame(timeout_s=1.0)
                if frame is not None:
                    print(format_frame(frame), flush=True)
    except KeyboardInterrupt:
        return 0
    except CANError as error:
        print(f"CAN monitor failed: {error}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
