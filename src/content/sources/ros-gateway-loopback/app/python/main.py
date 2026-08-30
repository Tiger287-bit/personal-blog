# SPDX-License-Identifier: MIT

import time

from arduino.app_utils import App
from ros_gateway import RosGateway


gateway = RosGateway()
last_state_publish = 0.0
last_status_signature = None


def handle_cmd_vel(command):
    """
    @description         : 将经过协议校验的速度指令写入 App Lab 日志，本阶段不控制真实电机
    @param command       : 包含 vx、vy、wz、seq 和 timestamp_ms 的速度指令
    @return              : 无返回值
    """
    print(
        "[loopback] cmd_vel accepted: "
        f"seq={command['seq']} vx={command['vx']:.3f} "
        f"vy={command['vy']:.3f} wz={command['wz']:.3f}",
        flush=True,
    )


def handle_mode_change(mode):
    """
    @description         : 记录 ROS 2 请求的底盘模式切换
    @param mode          : 新的底盘模式字符串
    @return              : True 表示允许本次模式切换
    """
    print(f"[loopback] mode changed: {mode}", flush=True)
    return True


def handle_safe_stop(reason):
    """
    @description         : 处理通信超时或断线产生的安全停车事件，本阶段只记录日志
    @param reason        : 触发安全停车的原因
    @return              : 无返回值
    """
    print(f"[loopback] SAFE_STOP: {reason}; no CAN command sent", flush=True)


def loop():
    """
    @description         : 周期发布模拟底盘状态并保持 App 主循环非阻塞运行
    @param               : 无参数
    @return              : 无返回值
    """
    global last_state_publish, last_status_signature

    current_time = time.monotonic()
    if current_time - last_state_publish >= 1.0:
        status = gateway.get_status()
        gateway.publish_base_state(
            {
                "mode": status["mode"],
                "enabled": False,
                "wheel_position": [0.0, 0.0, 0.0, 0.0],
                "wheel_velocity": [0.0, 0.0, 0.0, 0.0],
                "battery_voltage": 0.0,
                "estop": False,
                "fault_code": 0,
            }
        )
        status_signature = (
            status["connected"],
            status["mode"],
            status["client_node"],
            status["server_error"],
        )
        if status_signature != last_status_signature:
            print(
                "[loopback] status changed: "
                f"connected={status['connected']} mode={status['mode']} "
                f"client={status['client_node'] or '-'} "
                f"server_error={status['server_error'] or '-'}",
                flush=True,
            )
            last_status_signature = status_signature
        last_state_publish = current_time

    time.sleep(0.05)


gateway.on_cmd_vel(handle_cmd_vel)
gateway.on_mode_change(handle_mode_change)
gateway.on_stop(handle_safe_stop)

App.run(user_loop=loop)
