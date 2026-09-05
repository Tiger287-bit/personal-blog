#!/usr/bin/env python3
"""使用python/can_messages.py中的名称发送或接收一条报文。"""

import argparse
import json

from _bootstrap import format_frame
from can_messages import MESSAGES
from generic_can import CANError, CanBus, CanFrame


CONFIRMATION = "SEND_NAMED_CAN_MESSAGE"


def parse_values(text):
    """
    @description         : 把JSON对象转换成命名报文encode函数的关键字参数
    @param text          : JSON对象字符串
    @return              : Python字典
    """
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("values must be a JSON object")
    return value


def main():
    """
    @description         : 按报文名称执行一次显式发送或等待一次接收
    @param               : 命令行参数
    @return              : 进程退出码
    """
    parser = argparse.ArgumentParser(
        description="Use named definitions from python/can_messages.py"
    )
    parser.add_argument("--interface", default="can0")
    subparsers = parser.add_subparsers(dest="action", required=True)

    send_parser = subparsers.add_parser("send")
    send_parser.add_argument("name")
    send_parser.add_argument("--values", type=parse_values, default={})
    send_parser.add_argument("--confirm", required=True)

    receive_parser = subparsers.add_parser("receive")
    receive_parser.add_argument("name")
    receive_parser.add_argument("--timeout", type=float, default=1.0)
    args = parser.parse_args()

    try:
        with CanBus(interface=args.interface, messages=MESSAGES) as bus:
            if args.action == "send":
                if args.confirm != CONFIRMATION:
                    print(
                        "Refusing to send; use "
                        f"--confirm {CONFIRMATION}",
                        flush=True,
                    )
                    return 2
                frame = bus.send(args.name, **args.values)
                print(format_frame(frame, direction="TX"), flush=True)
                return 0

            result = bus.receive(args.name, timeout_s=args.timeout)
            if isinstance(result, CanFrame):
                print(format_frame(result), flush=True)
            else:
                print(
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    flush=True,
                )
            return 0
    except CANError as error:
        print(f"Named CAN operation failed: {error}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
