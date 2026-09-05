---
title: "ROS 2 与 App 通讯 02：控制四台 ZDT 电机"
description: "复用 Arduino App 中的 zdt_motor Brick，让原生 ROS 2 节点通过 Linux SocketCAN 独立控制地址 1、2、3、4 的四台 ZDT X57S 电机。"
section: "ros2-app"
appId: "zdt-motor-demo"
order: 2
status: "verified"
pubDate: "2026-09-05"
updatedDate: "2026-09-05"
environment:
  - "Arduino VENTUNO Q"
  - "ROS 2 Jazzy"
  - "SocketCAN can0"
  - "ZDT X57S / FW_Emm"
capabilities:
  - "ROS 2 Topic"
  - "ROS 2 Service"
  - "SocketCAN"
  - "四电机"
sourceDir: "ros2-app-motor-demo"
---

这个示例使用一个 ROS 2 驱动节点控制四台 ZDT X57S 第二代闭环步进电机。四台电机地址
分别为 `1`、`2`、`3`、`4`，CAN 波特率为 500 kbit/s。

## 先理解这个示例的边界

这个示例与 LED 示例不同：电机报文不经过 WebSocket，也不经过 App 的 `python/main.py`。

```text
ROS 2 zdt_motor_driver
          ↓
zdt_motor Brick
          ↓ python-can / SocketCAN
Linux can0
          ↓
CAN 总线 → 地址 1、2、3、4 电机
```

Arduino App 在这里负责两件事：

1. 携带经过验证的 `zdt_motor` Brick 和离线 Python 依赖；
2. 运行最小 Sketch，让系统 CANnectivity 把 VENTUNO Q 的 FDCAN1 提供为 Linux `can0`。

真正的 ROS 2 驱动进程运行在 Linux 宿主系统，因此能够访问 `can0`。它通过
`scripts/run_host_python.sh` 同时找到 ROS 2 环境和 App 中的 Brick。

## 硬件与电机设置

本教程对应的设置是：

| 项目 | 值 |
| --- | --- |
| 电机 | ZDT X57S 第二代闭环步进电机 |
| 固件协议 | `FW_Emm` |
| 电机地址 | `1`、`2`、`3`、`4` |
| 串口映射 | `CAN1_MAP` |
| CAN 波特率 | `500K` |
| 校验方式 | 固定 `0x6B` |
| Response | `Receive` 或 `Both` |
| CAN 帧 | 普通 CAN 2.0 帧，不使用 CAN-FD/BRS |

电机动力电源必须独立正确供电，CAN-H、CAN-L 和信号地应正确连接。机器人总线两端各放
一个 120 Ω 终端时，断电测量 CAN-H 与 CAN-L 应接近 60 Ω。

## ROS 2 接口

### 话题

| 名称 | 类型 | 节点行为 | 含义 |
| --- | --- | --- | --- |
| `/zdt_motors/target_rpm` | `std_msgs/msg/Int32MultiArray` | 订阅 | 四台电机目标 RPM |
| `/zdt_motors/actual_rpm` | `std_msgs/msg/Int32MultiArray` | 发布 | 四台电机实时反馈 RPM |
| `/zdt_motors/enabled` | `std_msgs/msg/Bool` | 发布 | 驱动的软件使能状态 |
| `/zdt_motors/connected` | `std_msgs/msg/Bool` | 发布 | 总线已打开、成功回读且无锁存故障 |
| `/zdt_motors/simulated` | `std_msgs/msg/Bool` | 发布 | 当前是否使用 Fake Backend |

四个数组元素按下面的逻辑轮位排列：

```text
[FL, FR, RL, RR]
```

默认对应电机地址：

```text
[1, 2, 3, 4]
```

### 服务

| 名称 | 类型 | 用途 |
| --- | --- | --- |
| `/zdt_motors/enable` | `std_srvs/srv/SetBool` | 使能或安全停止并失能全部电机 |
| `/zdt_motors/stop` | `std_srvs/srv/Trigger` | 立即请求全部停车并失能 |

当前没有定义 Action。RPM 是需要持续刷新的短周期控制目标，不是带反馈、取消和最终结果的
长任务；使能与停车是一次请求一次结果的操作，所以使用 Service。

## 节点参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `backend` | `fake` | `fake` 不访问硬件，`can` 使用真实 CAN |
| `motor_ids` | `[1,2,3,4]` | 四个逻辑轮位对应的电机地址 |
| `direction_signs` | `[1,1,1,1]` | 每轮方向，元素只能是 `1` 或 `-1` |
| `maximum_rpm` | `60` | ROS 2 命令允许的绝对值上限 |
| `command_timeout_s` | `0.5` | 没有新速度命令时的停车超时 |
| `acceleration` | `10` | Emm 加减速档位，范围 0～255 |

`backend` 默认是 `fake`，这样直接执行 `ros2 run` 不会误操作真实电机。实机测试必须显式
传入 `-p backend:=can`。

## 完整源码目录

文章左侧已经收录 App、Brick、离线 wheel、测试脚本和 ROS 2 包：

```text
ros2-app-motor-demo/
├── app/
│   ├── app.yaml
│   ├── python/main.py
│   ├── sketch/
│   ├── bricks/zdt_motor/
│   │   ├── backends/
│   │   ├── commands/
│   │   ├── protocols/
│   │   ├── vendor/
│   │   └── ...
│   ├── scripts/
│   └── tests/
└── ros2/
    └── zdt_motor_ros2/
```

`.whl` 是 App 离线安装依赖使用的二进制包。源码浏览器会显示“无法阅读”，但仍可下载，
而且 GitHub 中保留的是完整文件。

## 一个 Bus，四个电机对象

真实 Backend 只创建一个共享 CAN Bus：

```python
endpoint = SocketCanEndpoint(
    interface="can0",
    expected_bitrate=500_000,
    physical_port="VENTUNO Q FDCAN1 via CANnectivity",
)

bus = ZDTCanBus(
    name="chassis_motor_can",
    endpoint=endpoint,
    checksum="fixed_6b",
    default_timeout_s=0.5,
)
```

然后在同一条 Bus 上创建四个独立对象：

```python
motors = [
    ZDTMotor(bus=bus, model="X57S", motor_id=motor_id, firmware="emm")
    for motor_id in (1, 2, 3, 4)
]
```

这样每个对象只表示一台电机，Bus 负责共享 SocketCAN、请求应答匹配和总线资源管理。将来只
控制一台或两台同型号电机时，不需要重写 Brick，只需创建相应数量的 `ZDTMotor`。

四条速度会先以 `synchronized=True` 写入各电机缓存，最后发送一次广播同步启动：

```python
for motor, rpm in zip(motors, physical_rpms):
    motor.set_speed(rpm, acceleration=10, synchronized=True)

bus.start_synchronized()
```

## 准备源码与构建

把配套源码保存到：

```text
/home/arduino/ArduinoApps/zdt-motor-demo
/home/arduino/ros2_ws/codex/src/zdt_motor_ros2
```

构建 ROS 2 包：

```bash
cd /home/arduino/ros2_ws/codex
source /opt/ros/jazzy/setup.bash
colcon build --packages-select zdt_motor_ros2 --symlink-install
source install/setup.bash
```

## 第一步：使用 Fake Backend

Fake Backend 不访问 CAN，也不会让真实电机运动：

```bash
export ROS_DOMAIN_ID=45
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
source /opt/ros/jazzy/setup.bash
source /home/arduino/ros2_ws/codex/install/setup.bash
ros2 run zdt_motor_ros2 four_motor_driver
```

另开终端查看：

```bash
export ROS_DOMAIN_ID=45
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
source /opt/ros/jazzy/setup.bash
source /home/arduino/ros2_ws/codex/install/setup.bash
ros2 topic echo /zdt_motors/simulated --once
```

应该得到：

```text
data: true
```

先用 Fake Backend 熟悉话题和 Service，再进行真实电机测试。

## 第二步：启动 App 和 can0

真实 CAN 测试前，确保四个轮子架空、周围没有线缆和人员，并准备可以立即断开电机动力的
急停手段。

启动 App：

```bash
arduino-app-cli app list
arduino-app-cli app start /home/arduino/ArduinoApps/zdt-motor-demo
```

App 切换后 `can0` 可能重新枚举为 DOWN，因此要在 App 启动完成后配置接口：

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000
sudo ip link set can0 up
ip -details -statistics link show can0
```

正常状态至少应包含：

```text
<NOARP,UP,LOWER_UP,ECHO>
can state ERROR-ACTIVE
bitrate 500000
```

`expected_bitrate=500_000` 只是 Brick 的接口说明，不会替你执行 `ip link`。

## 第三步：启动真实驱动

```bash
export ROS_DOMAIN_ID=45
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
source /opt/ros/jazzy/setup.bash
source /home/arduino/ros2_ws/codex/install/setup.bash

/home/arduino/ArduinoApps/zdt-motor-demo/scripts/run_host_python.sh \
  /home/arduino/ros2_ws/codex/install/zdt_motor_ros2/lib/zdt_motor_ros2/four_motor_driver \
  --ros-args -p backend:=can
```

启动只会打开 Bus 并周期读取反馈，不会自动使能或发送非零速度。

## 第四步：检查状态

另开终端：

```bash
export ROS_DOMAIN_ID=45
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
source /opt/ros/jazzy/setup.bash
source /home/arduino/ros2_ws/codex/install/setup.bash
```

检查 Backend：

```bash
ros2 topic echo /zdt_motors/simulated --once
ros2 topic echo /zdt_motors/connected --once
ros2 topic echo /zdt_motors/actual_rpm --once
```

真实模式应看到 `simulated=false`。成功回读后 `connected=true`，停止状态的 RPM 应接近：

```text
data: [0, 0, 0, 0]
```

## 第五步：低速运动测试

只有状态读取正常且轮子已经架空时才继续。先使能：

```bash
ros2 service call /zdt_motors/enable \
  std_srvs/srv/SetBool \
  "{data: true}"
```

确认返回 `success: true` 后，以 10 Hz 持续发送四个 `10 RPM`：

```bash
ros2 topic pub -r 10 \
  /zdt_motors/target_rpm \
  std_msgs/msg/Int32MultiArray \
  "{data: [10, 10, 10, 10]}"
```

另开终端读取反馈：

```bash
ros2 topic echo /zdt_motors/actual_rpm
```

目标是 10 RPM 时，反馈在 9 和 10 之间变化属于驱动器整数 RPM 反馈的正常量化现象。这个值
来自驱动器内部闭环，不等同于独立的轮端机械测量。

## 停车

先在速度发布终端按 `Ctrl+C`，再显式调用停车 Service：

```bash
ros2 service call /zdt_motors/stop \
  std_srvs/srv/Trigger \
  "{}"
```

最后确认：

```bash
ros2 topic echo /zdt_motors/actual_rpm --once
ros2 topic echo /zdt_motors/enabled --once
```

结果应为接近零转速且 `enabled=false`。

## 安全机制

- 非零命令超过 `maximum_rpm` 会被拒绝；
- 数组不是四个整数时会被拒绝；
- 没有成功使能时不能发送非零目标；
- 合法速度流中断超过 0.5 秒会请求停车；
- 通信或反馈异常会锁存故障，并尝试停车、失能；
- 恢复通信后不会自行恢复运动，必须重新成功使能；
- 节点退出时会尝试全部停车、失能并关闭 Bus。

软件看门狗不是硬实时急停。CAN 物理断开、Linux 掉电或进程被强制终止时，它无法保证命令
一定送达电机，因此机器人仍需要独立的硬件急停和驱动器侧安全配置。
