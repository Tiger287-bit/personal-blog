# SPDX-License-Identifier: MIT

import os
import threading
import time

from arduino.app_utils import App
from ros_gateway import RosGateway
from zdt_x57s_can import ZdtX57SCan, ZdtX57SCanError


MOTION_CONFIRMATION = "RUN_ZDT_X57S_V1_0"
MOTOR_ID = int(os.getenv("ZDT_MOTOR_ID", "1"))
STATE_PUBLISH_INTERVAL_S = 0.2

gateway = RosGateway()
motor = ZdtX57SCan(MOTOR_ID)
state_lock = threading.RLock()
motor_enabled = False
last_speed_rpm = 0
communication_ok = False
last_error = "waiting for first motor response"
last_state_publish = 0.0


def update_motor_state(enabled=None, speed_rpm=None, ok=None, error=None):
    """
    @description         : 在线程锁保护下更新单电机状态快照
    @param enabled       : 可选的新使能状态
    @param speed_rpm     : 可选的新实时转速
    @param ok            : 可选的CAN通信状态
    @param error         : 可选的最近错误文本
    @return              : 无返回值
    """
    global motor_enabled, last_speed_rpm, communication_ok, last_error

    with state_lock:
        if enabled is not None:
            motor_enabled = bool(enabled)
        if speed_rpm is not None:
            last_speed_rpm = int(speed_rpm)
        if ok is not None:
            communication_ok = bool(ok)
        if error is not None:
            last_error = str(error)


def get_motor_state():
    """
    @description         : 获取可安全发布给ROS 2的单电机状态快照
    @param               : 无参数
    @return              : 包含地址、转速、使能和通信状态的字典
    """
    with state_lock:
        return {
            "motor_id": motor.motor_id,
            "speed_rpm": last_speed_rpm,
            "enabled": motor_enabled,
            "communication_ok": communication_ok,
            "error": last_error,
        }


def handle_motor_enable(command):
    """
    @description         : 执行ROS 2请求的单电机使能或安全失能
    @param command       : 已完成WebSocket协议校验的使能命令
    @return              : 电机命令成功返回True
    """
    if command["enabled"]:
        motor.enable(MOTION_CONFIRMATION)
        update_motor_state(enabled=True, ok=True, error="")
        print(f"[ros-zdt] motor {motor.motor_id} enabled", flush=True)
    else:
        motor.stop()
        update_motor_state(enabled=False, speed_rpm=0, ok=True, error="")
        print(f"[ros-zdt] motor {motor.motor_id} stopped and disabled", flush=True)
    return True


def handle_motor_set_speed(command):
    """
    @description         : 将ROS 2整数RPM目标写入当前单电机对象
    @param command       : 包含rpm和acceleration_level的已校验命令
    @return              : 已执行返回True，未使能的非零命令返回False
    """
    with state_lock:
        enabled = motor_enabled
    if command["rpm"] != 0 and not enabled:
        print(
            f"[ros-zdt] rejected non-zero speed for disabled motor {motor.motor_id}",
            flush=True,
        )
        return False

    if command["rpm"] == 0 and not enabled:
        motor.stop()
        update_motor_state(speed_rpm=0, ok=True, error="")
    else:
        motor.set_speed(
            command["rpm"],
            command["acceleration_level"],
            MOTION_CONFIRMATION,
        )
        update_motor_state(ok=True, error="")
    return True


def handle_motor_stop(command):
    """
    @description         : 执行ROS 2主动停车并清除本地使能状态
    @param command       : 已完成WebSocket协议校验的停车命令
    @return              : 停车成功返回True
    """
    motor.stop()
    update_motor_state(enabled=False, speed_rpm=0, ok=True, error="")
    print(f"[ros-zdt] motor {motor.motor_id} stopped", flush=True)
    return True


def handle_mode_change(mode):
    """
    @description         : 接受ROS 2模式切换并在离开遥控模式前安全停车
    @param mode          : 目标模式字符串
    @return              : 模式处理完成返回True
    """
    if mode != "ROS_TELEOP":
        safe_stop(f"mode_changed_to_{mode}")
    print(f"[ros-zdt] mode changed: {mode}", flush=True)
    return True


def safe_stop(reason):
    """
    @description         : 在命令超时、WebSocket断线或模式变化时停车并失能
    @param reason        : 触发安全停车的原因
    @return              : 无返回值
    """
    try:
        motor.stop()
        update_motor_state(enabled=False, speed_rpm=0, ok=True, error="")
        print(
            f"[ros-zdt] SAFE_STOP motor={motor.motor_id} reason={reason}",
            flush=True,
        )
    except ZdtX57SCanError as error:
        update_motor_state(enabled=False, ok=False, error=str(error))
        print(
            f"[ros-zdt] SAFE_STOP failed motor={motor.motor_id}: {error}",
            flush=True,
        )


def loop():
    """
    @description         : 周期读取单电机实时RPM并通过WebSocket发布给ROS 2
    @param               : 无参数
    @return              : 无返回值
    """
    global last_state_publish

    current_time = time.monotonic()
    if current_time - last_state_publish >= STATE_PUBLISH_INTERVAL_S:
        try:
            speed_rpm = motor.read_speed()
            update_motor_state(speed_rpm=speed_rpm, ok=True, error="")
        except ZdtX57SCanError as error:
            update_motor_state(ok=False, error=str(error))
        gateway.publish_motor_state(get_motor_state())
        last_state_publish = current_time

    time.sleep(0.02)


gateway.on_motor_enable(handle_motor_enable)
gateway.on_motor_set_speed(handle_motor_set_speed)
gateway.on_motor_stop(handle_motor_stop)
gateway.on_mode_change(handle_mode_change)
gateway.on_stop(safe_stop)

print(
    f"[ros-zdt] ready: one ZDT X57S object bound to motor_id={motor.motor_id}",
    flush=True,
)
App.run(user_loop=loop)
