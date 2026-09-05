#!/usr/bin/env python3
"""默认安全、不会让电机运动的只读硬件测试。"""

import argparse
import json

from _common import add_motor_arguments, create_bus_and_motor


def parse_args():
    """
    @description         : 解析只读电机测试参数
    @param               : 无参数
    @return              : argparse.Namespace
    """
    parser = argparse.ArgumentParser(description="Safe read-only ZDT motor test.")
    add_motor_arguments(parser)
    return parser.parse_args()


def main():
    """
    @description         : 打印原始CAN并读取X57S明确支持的安全参数
    @param               : 无参数
    @return              : 成功0，失败1
    """
    args = parse_args()
    bus, motor = create_bus_and_motor(args, trace=True)
    try:
        with bus:
            result = {
                "motor_id": motor.motor_id,
                "model": motor.model,
                "firmware": motor.firmware.value,
                "version": motor.get_version(),
                "position_degrees": motor.get_position(),
                "speed_rpm": motor.get_speed(),
                "position_error_degrees": motor.get_position_error(),
                "status": motor.get_status(),
                "home_status": motor.get_home_status(),
                "bus_voltage_v": motor.get_bus_voltage(),
                "phase_current_ma": motor.get_phase_current(),
                "phase_parameters": motor.get_phase_parameters(),
                "encoder_degrees": motor.get_encoder_degrees(),
                "input_pulses": motor.get_input_pulses(),
            }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("PASS: read-only motor communication and decoding succeeded")
        return 0
    except Exception as error:
        print(f"FAIL: {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
