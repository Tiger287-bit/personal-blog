# SPDX-License-Identifier: MIT

import argparse
import json

from zdt_x57s_can import ZdtX57SCan


MOTION_CONFIRMATION = "RUN_ZDT_X57S_V1_0"


def parse_args():
    """
    @description         : 解析无运动探测或单电机限时运行测试参数
    @param               : 无参数
    @return              : argparse.Namespace参数对象
    """
    parser = argparse.ArgumentParser(
        description="Test the reusable ZDT X57S CAN Brick."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--probe", action="store_true")
    action.add_argument("--motor-test", action="store_true")
    parser.add_argument("--motor-id", type=int, default=1)
    parser.add_argument("--rpm", type=int, default=20)
    parser.add_argument("--acceleration-level", type=int, default=10)
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def main():
    """
    @description         : 调用Custom Brick执行探测或带确认口令的单电机限时测试
    @param               : 无参数
    @return              : 成功返回0; 参数确认失败返回2
    """
    args = parse_args()
    motor = ZdtX57SCan(args.motor_id)

    if args.probe:
        print(
            json.dumps(
                motor.probe(),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.confirm != MOTION_CONFIRMATION:
        print(
            "拒绝运行：请确认电机已架空并添加 "
            f"--confirm {MOTION_CONFIRMATION}"
        )
        return 2

    result = motor.timed_speed_test(
        rpm=args.rpm,
        acceleration_level=args.acceleration_level,
        duration_s=args.duration,
        confirmation=args.confirm,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
