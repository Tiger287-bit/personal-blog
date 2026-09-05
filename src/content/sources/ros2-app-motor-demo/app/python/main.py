# SPDX-License-Identifier: MIT

import time

from arduino.app_utils import App
from zdt_motor import ZDTBus, ZDTError, ZDTMotor


probe_complete = False
next_probe_time = 0.0
last_error = None


def read_motor_safely():
    """
    @description         : 创建can0共享Bus并只读查询1号X57S电机基础信息
    @param               : 无参数
    @return              : 电机基础信息字典
    """
    with ZDTBus(interface="can", device="can0") as bus:
        motor = ZDTMotor(
            bus=bus,
            model="X57S",
            motor_id=1,
            firmware="emm",
        )
        return motor.read_basic_info()


def loop():
    """
    @description         : 以只读方式尝试一次电机查询并清晰报告容器can0边界
    @param               : 无参数
    @return              : 无返回值
    """
    global probe_complete, next_probe_time, last_error
    now = time.monotonic()
    if not probe_complete and now >= next_probe_time:
        try:
            info = read_motor_safely()
            print(f"[zdt-motor] read-only PASS: {info}", flush=True)
            probe_complete = True
            last_error = None
        except (ZDTError, OSError) as error:
            message = str(error)
            if message != last_error:
                print(
                    "[zdt-motor] read-only probe unavailable: "
                    f"{message}. App Lab main runs in a container; run "
                    "scripts/motor_read_test.py on the Ventuno Linux host "
                    "when can0 is UP.",
                    flush=True,
                )
                last_error = message
            next_probe_time = now + 10.0
    time.sleep(0.05)


App.run(user_loop=loop)
