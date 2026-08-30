# SPDX-License-Identifier: MIT

import time

from arduino.app_utils import App
from zdt_x57s_can import ZdtX57SCan, ZdtX57SCanError


MOTOR_IDS = (1, 2, 3, 4)
motors = tuple(ZdtX57SCan(motor_id) for motor_id in MOTOR_IDS)
probe_complete = False
next_probe_time = 0.0
last_error = None


def read_all_motor_speeds():
    """
    @description         : 由测试App组合四个单电机对象并依次读取实时速度
    @param               : 无参数
    @return              : 电机地址到实时RPM的字典
    """
    speeds = {}
    for motor in motors:
        try:
            speeds[motor.motor_id] = motor.read_speed()
        except ZdtX57SCanError as error:
            raise ZdtX57SCanError(
                f"motor {motor.motor_id}: {error}"
            ) from error
    return speeds


def loop():
    """
    @description         : 等待Linux原生CAN网关就绪并对1至4号电机执行一次无运动探测
    @param               : 无参数
    @return              : 无返回值
    """
    global probe_complete, next_probe_time, last_error

    current_time = time.monotonic()
    if not probe_complete and current_time >= next_probe_time:
        try:
            speeds = read_all_motor_speeds()
            print(
                "[zdt-x57s] 四电机CAN通信正常: "
                + ", ".join(
                    f"id{motor_id}={speeds[motor_id]}RPM"
                    for motor_id in MOTOR_IDS
                ),
                flush=True,
            )
            probe_complete = True
            last_error = None
        except ZdtX57SCanError as error:
            error_text = str(error)
            if error_text != last_error:
                print(
                    "[zdt-x57s] 等待CAN网关或电机应答: " + error_text,
                    flush=True,
                )
                last_error = error_text
            next_probe_time = current_time + 3.0

    time.sleep(0.05)


App.run(user_loop=loop)
