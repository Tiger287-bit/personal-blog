# 四电机 RPM 驱动

普通 ROS 2 原型，复用现有 `zdt-motor-demo` 的 ZDT Brick。
当前部署已构建，未执行本轮测试或真实运动。

## 启动

先关闭旧的 Fake 驱动和其他控制这四台电机的进程，确保仅有一个控制者。
现有 `can0` 必须已启动为 500 kbit/s；本节点不会修改网络接口。
当前配置为 X57S、Emm、fixed_6b。电机菜单 Response 需为 Receive 或 Both。

终端 1：

```bash
source /opt/ros/jazzy/setup.bash
source /home/arduino/ros2_ws/codex/install/setup.bash
/home/arduino/ArduinoApps/zdt-motor-demo/scripts/run_host_python.sh \
  /home/arduino/ros2_ws/codex/install/zdt_motor_ros2/lib/zdt_motor_ros2/four_motor_driver \
  --ros-args -p backend:=can
```

脚本复用 App 现有 Python 依赖，但进程在 Linux 主机运行，可以访问 can0。
默认 `backend:=fake` 不访问 CAN；实机启动只打开接口并周期回读，等待显式使能和目标命令。

终端 2（车轮悬空、急停可用时操作，发布后四台电机将转动）：

```bash
source /opt/ros/jazzy/setup.bash
source /home/arduino/ros2_ws/codex/install/setup.bash
ros2 service call /zdt_motors/enable std_srvs/srv/SetBool '{data: true}'
ros2 topic pub -r 10 /zdt_motors/target_rpm std_msgs/msg/Int32MultiArray '{data: [20, 20, 20, 20]}'
```

确认使能返回 `success: true` 后再发布。上层节点只需按相同接口持续发命令。
数组当前按 ID `[1,2,3,4]` 顺序；约定轮位为 `[FL,FR,RL,RR]`，实际接线轮位需一致。
参数 `motor_ids` 可调整顺序，`direction_signs` 的四个 `+1/-1` 可反转各轮逻辑方向。
正号不直接代表小车前进；RPM 是电机轴转速，未包含减速比或底盘运动学换算。
四条速度命令缓存后，通过 Brick 的广播同步触发接口执行。

## 停止和故障

- 在发布命令的终端按 Ctrl+C，默认断流 0.5 秒后触发软件停车；驱动必须继续运行且 CAN 可通信。
- 也可先停止命令发布，再调用 `ros2 service call /zdt_motors/stop std_srvs/srv/Trigger '{}'`。
- 驱动终端 Ctrl+C 时尝试对全部电机停车、失能并关闭总线。
- 通信/反馈异常会锁定非零命令并尝试停车失能；排除故障后重新成功调用 enable 服务，再发布新命令。
- 软件 watchdog 不是硬实时保障：同步 CAN 请求会延迟回调，物理 CAN 断开、主机掉电或强杀进程时无法保证停车，仍依赖独立急停/驱动端保障。

## 接口

- `/zdt_motors/target_rpm`：Int32MultiArray，长度 4，默认各项范围 ±60 RPM；非法输入拒绝且不刷新超时。
- `/zdt_motors/actual_rpm`：Int32MultiArray，实机模式以 1 Hz 回读真实 RPM，应用相同方向符号；读取失败不发布伪造零值。
- `/zdt_motors/enabled`：Bool，驱动的软件命令使能状态，不是每台电机的实时硬件使能反馈。
- `/zdt_motors/connected`：Bool，总线打开、已成功回读且节点无锁存故障；不是硬件安全认证。
- `/zdt_motors/simulated`：Bool，fake 模式为 true。
- `/zdt_motors/enable`：SetBool；`/zdt_motors/stop`：Trigger。

配置参数在启动时读取：`backend`、`motor_ids`、`direction_signs`、`maximum_rpm`、`command_timeout_s`、`acceleration`。
Emm acceleration 为 0–255 档，默认 10；参数修改后需重启节点。

构建日志与修改前两文件位于 `/home/arduino/ros2_ws/codex/logs/zdt_can_backend_20260902T1020/`。
