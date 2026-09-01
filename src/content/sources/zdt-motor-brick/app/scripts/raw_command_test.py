#!/usr/bin/env python3
"""需要明确确认的 ZDT 原始逻辑命令工具。"""

import argparse

from _common import add_motor_arguments, create_bus_and_motor, parse_hex_bytes


def integer_auto(text):
    """
    @description         : 支持十进制或0x前缀整数参数
    @param text          : 命令行文本
    @return              : 整数
    """
    return int(text, 0)


def parse_args():
    """
    @description         : 解析原始功能码、载荷和响应长度
    @param               : 无参数
    @return              : argparse.Namespace
    """
    parser = argparse.ArgumentParser(description="Advanced raw ZDT command test.")
    add_motor_arguments(parser)
    parser.add_argument("--function", type=integer_auto, required=True)
    parser.add_argument("--payload", default="")
    parser.add_argument("--expected-length", type=int, default=3)
    parser.add_argument("--unsafe-raw", action="store_true")
    return parser.parse_args()


def main():
    """
    @description         : 由Brick计算ID、分包和校验后发送原始逻辑命令
    @param               : 无参数
    @return              : 成功0，拒绝2，失败1
    """
    args = parse_args()
    if not args.unsafe_raw:
        print("REFUSED: raw commands may move or reconfigure hardware; add --unsafe-raw")
        return 2
    payload = parse_hex_bytes(args.payload)
    bus, motor = create_bus_and_motor(args, trace=True)
    try:
        with bus:
            response = motor.raw.request(
                args.function,
                payload,
                expected_response_length=args.expected_length,
                timeout_s=args.timeout,
            )
        print(
            f"PASS: motor={response.address} function=0x{response.function_code:02X} "
            f"data={response.data.hex(' ').upper()} raw={response.raw.hex(' ').upper()}"
        )
        return 0
    except Exception as error:
        print(f"FAIL: {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
