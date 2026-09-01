#!/usr/bin/env python3
"""需要明确确认的电机使能和失能测试。"""

import argparse
import json

from _common import add_motor_arguments, create_bus_and_motor


def parse_args():
    """
    @description         : 解析使能测试参数和确认开关
    @param               : 无参数
    @return              : argparse.Namespace
    """
    parser = argparse.ArgumentParser(description="Explicit ZDT enable/disable test.")
    add_motor_arguments(parser)
    parser.add_argument("--yes", action="store_true")
    return parser.parse_args()


def main():
    """
    @description         : 明确确认后使能、读取状态并在finally中失能
    @param               : 无参数
    @return              : 成功0，拒绝2，失败1
    """
    args = parse_args()
    if not args.yes:
        print("REFUSED: enable changes actuator state; add --yes after checking safety")
        return 2
    print(
        f"Motor ID={args.motor_id} device={args.device} action=enable -> disable",
        flush=True,
    )
    bus, motor = create_bus_and_motor(args, trace=True)
    result = {}
    try:
        with bus:
            try:
                result["enable"] = motor.enable()
                result["status_after_enable"] = motor.get_status()
            finally:
                result["disable"] = motor.disable()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("PASS: enable and disable acknowledgements were valid")
        return 0
    except Exception as error:
        print(f"FAIL: {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
