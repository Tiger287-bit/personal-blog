#!/usr/bin/env python3
"""默认拒绝运动的低速短距离位置测试。"""

import argparse
import json
import time

from _common import add_motor_arguments, create_bus_and_motor


def parse_args():
    """
    @description         : 解析受保护的运动测试参数
    @param               : 无参数
    @return              : argparse.Namespace
    """
    parser = argparse.ArgumentParser(description="Guarded ZDT relative motion test.")
    add_motor_arguments(parser)
    parser.add_argument("--rpm", type=float, default=10.0)
    parser.add_argument("--degrees", type=float, default=30.0)
    parser.add_argument("--direction", choices=("cw", "ccw"))
    parser.add_argument("--acceleration", type=int)
    parser.add_argument("--deceleration", type=int)
    parser.add_argument("--wait-timeout", type=float, default=5.0)
    parser.add_argument("--unsafe-motion", action="store_true")
    return parser.parse_args()


def wait_for_position(motor, timeout_s):
    """
    @description         : 轮询位置到达标志直到成功或超时
    @param motor         : ZDTMotor
    @param timeout_s     : 最大等待秒数
    @return              : 最后一次状态字典
    """
    deadline = time.monotonic() + timeout_s
    status = {}
    while time.monotonic() < deadline:
        status = motor.get_status()
        if status["position_reached"]:
            return status
        time.sleep(0.1)
    raise TimeoutError(f"position was not reached within {timeout_s:.1f}s")


def main():
    """
    @description         : 确认后执行使能、低速相对运动、停止、读取和失能
    @param               : 无参数
    @return              : 成功0，拒绝2，失败1
    """
    args = parse_args()
    if not args.unsafe_motion:
        print("REFUSED: add --unsafe-motion only after lifting the wheel and clearing the area")
        return 2
    command_summary = {
        "motor_id": args.motor_id,
        "device": args.device,
        "firmware": args.firmware,
        "rpm": args.rpm,
        "degrees": args.degrees,
        "direction": args.direction or "from degrees sign",
        "acceleration": args.acceleration,
        "deceleration": args.deceleration,
    }
    print(json.dumps(command_summary, ensure_ascii=False, indent=2), flush=True)
    for remaining in (3, 2, 1):
        print(f"Starting in {remaining}...", flush=True)
        time.sleep(1)

    bus, motor = create_bus_and_motor(args, trace=True)
    result = {}
    failure = None
    try:
        with bus:
            try:
                result["enable"] = motor.enable()
                result["move"] = motor.move_relative(
                    args.degrees,
                    rpm=args.rpm,
                    direction=args.direction,
                    acceleration=args.acceleration,
                    deceleration=args.deceleration,
                )
                result["reached_status"] = wait_for_position(
                    motor,
                    args.wait_timeout,
                )
            except Exception as error:
                failure = error
            finally:
                try:
                    result["stop"] = motor.stop()
                except Exception as error:
                    result["stop_error"] = str(error)
                    failure = failure or error
                try:
                    result["final_status"] = motor.get_status()
                except Exception as error:
                    result["status_error"] = str(error)
                    failure = failure or error
                try:
                    result["disable"] = motor.disable()
                except Exception as error:
                    result["disable_error"] = str(error)
                    failure = failure or error
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if failure is not None:
            raise failure
        print("PASS: guarded motion sequence completed and motor was disabled")
        return 0
    except Exception as error:
        print(f"FAIL: {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
