# SPDX-License-Identifier: MIT

"""zdt_motor Brick 的最小只读示例。

示例创建地址为 1 的电机对象，并读取基础信息。当前 App Lab 容器默认看不到
Linux 宿主系统的 can0，因此这里也会把这一运行边界清楚地输出到日志。
"""

import time

from arduino.app_utils import App
from zdt_motor import SocketCanEndpoint, ZDTCanBus, ZDTError, ZDTMotor


probe_complete = False
next_probe_time = 0.0
last_error = None


def read_motor_safely():
    """
    @description         : 创建can0总线和1号X57S电机对象，然后只读查询基础信息
    @param               : 无参数
    @return              : 电机基础信息字典
    """
    endpoint = SocketCanEndpoint(interface="can0", expected_bitrate=500_000)
    with ZDTCanBus(name="motor_can", endpoint=endpoint) as can_bus:
        motor = ZDTMotor(
            bus=can_bus,
            model="X57S",
            motor_id=1,
            firmware="emm",
        )
        return motor.read_basic_info()


def loop():
    """
    @description         : 尝试一次只读查询；can0不可见时定期输出原因
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
