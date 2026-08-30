---
title: "ros-zdt-x57s-single-motor：用 ROS 2 控制一台 ZDT X57S"
description: "把 WebSocket Brick 与单电机 CAN Brick 组合成一个 App，通过 ROS 2 完成使能、速度控制、反馈读取和安全停车。"
section: "app-lab"
appId: "ros-zdt-x57s-single-motor"
order: 3
status: "verified"
pubDate: "2026-08-30"
updatedDate: "2026-08-30"
verifiedDate: "2026-08-30"
environment:
  - "Arduino VENTUNO Q"
  - "Ubuntu 24.04 / aarch64"
  - "ROS 2 Jazzy"
  - "websockets 17.1"
  - "ZDT X57S 第二代 / FW_Emm"
  - "经典 CAN 500 kbit/s"
capabilities:
  - "双 Brick 组合"
  - "ROS 2"
  - "WebSocket"
  - "单电机控制"
  - "实时速度反馈"
  - "双看门狗停车"
sourceDir: "ros-zdt-x57s-single-motor"
---

本教程把两个已经独立验证的 Custom Brick 组合成一个新 App：

- `ros_gateway` 负责 ROS 2 与 App Lab 之间的 WebSocket 通信；
- `zdt_x57s_can` 负责一台 ZDT X57S 第二代电机的 CAN 操作。

组合后可以从 ROS 2 使能电机、持续发送整数 RPM、读取实时转速并安全停车。App 默认只
创建一个地址为 `1` 的电机对象，不包含四轮运动学，也不会把 RPM 冒充成 `/cmd_vel`。

开始前应先完成 [WebSocket 与 ROS 2 通信教程](/app-lab/ros-gateway-loopback/) 和
[ZDT X57S 单电机 Brick 教程](/app-lab/zdt-x57s-can-test/)。

## 实现结果

完整链路如下：

```text
/zdt_x57s/target_rpm
  ↓
ventuno_zdt_motor_bridge（Linux 原生 ROS 2）
  ↓ WebSocket / JSON
ros_gateway Brick（App Lab 容器）
  ↓ Python 回调
ZdtX57SCan(motor_id=1)
  ↓ 带令牌的 JSON / TCP
zdt_x57s_can_gateway（Linux 原生进程）
  ↓ SocketCAN can0
ZDT X57S 地址 1
```

实机测试使用 `+10 RPM`，运行阶段收到 13 个非零反馈样本：

```text
10, 10, 9, 10, 9, 9, 9, 10, 9, 9, 9, 10, 10
```

| 项目 | 结果 |
| --- | --- |
| 目标速度 | `10 RPM` |
| 实际范围 | `9～10 RPM` |
| 平均速度 | `9.46 RPM` |
| 停车后速度 | `0 RPM` |
| 停车后使能状态 | `false` |
| CAN 状态 | `ERROR-ACTIVE` |
| CAN 收发错误 | `0` |
| bus-off | `0` |

## 文件目录

Arduino App：

```text
/home/arduino/ArduinoApps/ros-zdt-x57s-single-motor/
├── app.yaml
├── python/
│   └── main.py
├── sketch/
│   ├── sketch.ino
│   └── sketch.yaml
├── bricks/
│   ├── ros_gateway/
│   │   ├── __init__.py
│   │   ├── gateway.py
│   │   ├── protocol.py
│   │   ├── brick_config.yaml
│   │   └── requirements.txt
│   └── zdt_x57s_can/
│       ├── __init__.py
│       ├── client.py
│       ├── brick_config.yaml
│       └── requirements.txt
└── tests/
    └── test_motor_protocol.py
```

原生 ROS 2 工作区：

```text
/home/arduino/work/ros_zdt_x57s_ws/
├── requirements.txt
└── src/
    └── ventuno_zdt_motor_bridge/
        ├── package.xml
        ├── setup.py
        ├── setup.cfg
        ├── config/bridge_params.yaml
        ├── launch/zdt_motor_bridge.launch.py
        ├── test/test_websocket_client.py
        └── ventuno_zdt_motor_bridge/
            ├── __init__.py
            ├── node.py
            └── websocket_client.py
```

## 原生 ROS 2 节点公开的 API

这些 API 由 `/home/arduino/work` 中的原生 `ventuno_zdt_motor_bridge` 节点创建，不是
WebSocket Brick 自己创建的 ROS 2 接口。

### 话题

| 名称 | 消息类型 | 节点行为 | 用途 |
| --- | --- | --- | --- |
| `/zdt_x57s/target_rpm` | `std_msgs/msg/Int32` | 订阅 | 目标整数 RPM |
| `/zdt_x57s/speed_rpm` | `std_msgs/msg/Int32` | 发布 | 电机实时 RPM |
| `/zdt_x57s/enabled` | `std_msgs/msg/Bool` | 发布 | 电机使能状态 |
| `/zdt_x57s/connected` | `std_msgs/msg/Bool` | 发布 | WebSocket 连接状态 |
| `/zdt_x57s/state` | `std_msgs/msg/String` | 发布 | 完整 JSON 状态 |

### 服务

| 名称 | 服务类型 | 用途 |
| --- | --- | --- |
| `/zdt_x57s/enable` | `std_srvs/srv/SetBool` | 使能或失能 |
| `/zdt_x57s/stop` | `std_srvs/srv/Trigger` | 停车并失能 |

### 参数

| 名称 | 默认值 | 用途 |
| --- | --- | --- |
| `websocket_url` | `ws://127.0.0.1:8765/ros` | Brick 端点 |
| `reconnect_interval` | `2.0` | 断线重连间隔，秒 |
| `heartbeat_interval` | `1.0` | 应用层心跳间隔，秒 |
| `command_timeout` | `0.3` | 速度命令时效，秒 |
| `acceleration_level` | `10` | 电机加减速档位 |
| `maximum_rpm` | `60` | ROS 2 节点允许的目标转速上限 |

### 动作

当前版本没有定义 ROS 2 Action。目标转速是持续刷新的短命令，不是带反馈、取消和最终
结果的长任务，因此这里使用话题；使能和停车是短请求，因此使用服务。

本 App 的目标速度上限为 `60 RPM`，加减速档位默认为 `10`。速度命令必须持续发送，
不是只发送一次后让电机一直运行。

## App 配置

`app.yaml` 同时引用两个 Brick。真实令牌必须由部署程序随机生成，不能使用教程中的
占位符：

```yaml
name: ROS ZDT X57S Single Motor
description: Combine the ROS WebSocket and single-motor ZDT X57S CAN Bricks.
ports: []
bricks:
  - ros_gateway:
      variables:
        ROS_GATEWAY_HOST: "0.0.0.0"
        ROS_GATEWAY_PORT: "8765"
        ROS_GATEWAY_PATH: "/ros"
        ROS_GATEWAY_NODE_NAME: "ros-zdt-x57s-single-motor"
        ROS_GATEWAY_MAX_MOTOR_RPM: "60"
        ROS_GATEWAY_COMMAND_TIMEOUT_MS: "300"
        ROS_GATEWAY_HEARTBEAT_TIMEOUT_MS: "3000"
  - zdt_x57s_can:
      variables:
        ZDT_CAN_GATEWAY_HOST: "msgpack-rpc-router"
        ZDT_CAN_GATEWAY_PORT: "8766"
        ZDT_CAN_GATEWAY_TOKEN: "<随机令牌>"
        ZDT_CAN_REQUEST_TIMEOUT_S: "1.5"
        ZDT_MOTOR_ID: "1"
icon: 🔗
```

`ZDT_MOTOR_ID` 决定这个 App 控制哪一台电机。改成 `2` 就绑定地址 2，但仍然只创建一个
电机对象。需要四台电机时，应由综合 App 创建四个对象，而不是修改单电机 Brick。

## 组合两个 Brick

`python/main.py` 创建一个网关和一个电机对象，再把网关事件绑定到电机方法：

```python
import os

from ros_gateway import RosGateway
from zdt_x57s_can import ZdtX57SCan


MOTION_CONFIRMATION = "RUN_ZDT_X57S_V1_0"
MOTOR_ID = int(os.getenv("ZDT_MOTOR_ID", "1"))

gateway = RosGateway()
motor = ZdtX57SCan(MOTOR_ID)
motor_enabled = False


def handle_motor_enable(command):
    """
    @description         : 执行ROS 2请求的单电机使能或安全失能
    @param command       : 已完成WebSocket协议校验的使能命令
    @return              : 电机命令成功返回True
    """
    global motor_enabled

    if command["enabled"]:
        motor.enable(MOTION_CONFIRMATION)
        motor_enabled = True
    else:
        motor.stop()
        motor_enabled = False
    return True


def handle_motor_set_speed(command):
    """
    @description         : 将ROS 2整数RPM目标写入当前单电机对象
    @param command       : 包含rpm和acceleration_level的已校验命令
    @return              : 已执行返回True，未使能的非零命令返回False
    """
    if command["rpm"] != 0 and not motor_enabled:
        return False

    if command["rpm"] == 0 and not motor_enabled:
        motor.stop()
    else:
        motor.set_speed(
            command["rpm"],
            command["acceleration_level"],
            MOTION_CONFIRMATION,
        )
    return True


def handle_motor_stop(command):
    """
    @description         : 执行ROS 2主动停车并清除本地使能状态
    @param command       : 已完成WebSocket协议校验的停车命令
    @return              : 停车成功返回True
    """
    global motor_enabled

    motor.stop()
    motor_enabled = False
    return True


gateway.on_motor_enable(handle_motor_enable)
gateway.on_motor_set_speed(handle_motor_set_speed)
gateway.on_motor_stop(handle_motor_stop)
```

实际 `main.py` 还使用线程锁保护状态，每 200 ms 调用一次 `motor.read_speed()`，并通过
`gateway.publish_motor_state()` 发布以下内容：

```json
{
  "motor_id": 1,
  "speed_rpm": 0,
  "enabled": false,
  "communication_ok": true,
  "error": ""
}
```

## WebSocket 电机报文

所有客户端报文都包含版本、严格递增序号和 Unix 毫秒时间戳。

使能：

```json
{
  "version": 1,
  "type": "motor_enable",
  "seq": 2,
  "timestamp_ms": 1788077937000,
  "enabled": true
}
```

设置速度：

```json
{
  "version": 1,
  "type": "motor_set_speed",
  "seq": 3,
  "timestamp_ms": 1788077966000,
  "rpm": 10,
  "acceleration_level": 10
}
```

停车：

```json
{
  "version": 1,
  "type": "motor_stop",
  "seq": 4,
  "timestamp_ms": 1788077998000
}
```

网关只在 `ROS_TELEOP` 模式接受使能和非零 RPM；拒绝布尔值冒充数字、浮点 RPM、
过期消息、超过 60 RPM 的目标值和不递增的序号。

## 最小 Sketch

Sketch 只负责启动 RouterBridge/CANnectivity，让 Linux 获得 `can0`。不能再调用
`CAN.begin()`：

```cpp
#include <Arduino_RouterBridge.h>

/*
 * @description         : 初始化RouterBridge并让系统CANnectivity向Linux提供FDCAN1
 * @param               : 无
 * @return              : 无
 */
void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  const bool bridgeReady = Bridge.begin();
  digitalWrite(LED_BUILTIN, bridgeReady ? LOW : HIGH);
}

/*
 * @description         : 保持MCU任务调度运行且不占用FDCAN1
 * @param               : 无
 * @return              : 无
 */
void loop() {
  delay(10);
}
```

## 构建 ROS 2 包

ROS 2 Jazzy 使用系统 Python 3.12。虚拟环境必须带 `--system-site-packages`，否则节点
找不到 `rclpy`：

```bash
cd /home/arduino/work/ros_zdt_x57s_ws

python3 -m venv --system-site-packages .venv
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python -m pip install -r requirements.txt

python -m colcon --log-base log_venv build \
  --symlink-install \
  --build-base build_venv \
  --install-base install_venv
```

必须使用 `python -m colcon`，这样生成的节点入口才会使用当前虚拟环境中的 Python 和
`websockets 17.1`。

## 启动 App 和 CAN

Ventuno Q 同一时间只能运行一个 App。切换 App 前必须先停车并确认 `speed_rpm=0`，再执行：

```bash
arduino-app-cli app list
arduino-app-cli app stop /home/arduino/ArduinoApps/<当前运行的App>
arduino-app-cli app start /home/arduino/ArduinoApps/ros-zdt-x57s-single-motor
```

切换 App 会让 MCU 和 `gs_usb` 重新枚举，因此 `can0` 会重新出现为 `DOWN`。当前验证方法
是手动配置：

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000
sudo ip link set can0 up
ip -details -statistics link show can0
```

正常输出必须包含：

```text
<NOARP,UP,LOWER_UP,ECHO>
can state ERROR-ACTIVE
bitrate 500000
berr-counter tx 0 rx 0
```

确认 Linux 原生 CAN 网关正在运行：

```bash
pgrep -af gateway.py
```

若没有输出，则另开终端启动：

```bash
cd /home/arduino/work/zdt_x57s_can_gateway
python3 -B gateway.py
```

## 启动 ROS 2 节点

另开终端执行：

```bash
cd /home/arduino/work/ros_zdt_x57s_ws

source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
source install_venv/setup.bash

ros2 launch ventuno_zdt_motor_bridge zdt_motor_bridge.launch.py
```

正常日志：

```text
connecting to ws://127.0.0.1:8765/ros
App Lab gateway connected
gateway ack: command=mode_change accepted=True mode=IDLE
```

## 手动控制电机

另开控制终端并加载同一环境：

```bash
cd /home/arduino/work/ros_zdt_x57s_ws
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
source install_venv/setup.bash
```

先读取状态：

```bash
ros2 topic echo /zdt_x57s/state --once --full-length
```

只有 `communication_ok=true` 时才继续。架空电机或车轮，确保周围没有线缆和人员，然后
使能：

```bash
ros2 service call /zdt_x57s/enable \
  std_srvs/srv/SetBool \
  "{data: true}"
```

以 10 Hz 持续发送 `+10 RPM`：

```bash
ros2 topic pub -r 10 \
  /zdt_x57s/target_rpm \
  std_msgs/msg/Int32 \
  "{data: 10}"
```

`-r 10` 表示每秒发布 10 次，`data: 10` 才表示目标为 10 RPM。反转时使用
`"{data: -10}"`。

另开终端读取反馈：

```bash
ros2 topic echo /zdt_x57s/speed_rpm
```

结束时先在发布终端按 `Ctrl+C`，再显式停车：

```bash
ros2 service call /zdt_x57s/stop \
  std_srvs/srv/Trigger \
  "{}"
```

最后确认：

```bash
ros2 topic echo /zdt_x57s/state --once --full-length
```

结果应包含：

```json
{
  "speed_rpm": 0,
  "enabled": false,
  "communication_ok": true,
  "error": ""
}
```

## 安全停车规则

本 App 有两层命令看门狗：

| 位置 | 超时 | 行为 |
| --- | --- | --- |
| WebSocket Brick | 300 ms | 调用 App 的 `safe_stop()` |
| Linux CAN 网关 | 500 ms | 发送零速、停止和失能 |

以下情况都会停车并失能：

- ROS 2 停止刷新 RPM；
- WebSocket 断开；
- 心跳超时；
- 离开 `ROS_TELEOP`；
- 调用 `/zdt_x57s/stop`。

不要在电机运行时切换或停止 Arduino App。应先调用 `/zdt_x57s/stop`，读取到
`speed_rpm=0` 和 `enabled=false` 后再操作 App CLI。

## 为什么反馈是 9 或 10 RPM

`target_rpm=10` 是目标值，`speed_rpm` 是驱动器内部闭环反馈。当前协议只返回整数 RPM，
因此实际处于约 9.x RPM 时会交替显示 9 和 10。低速下 1 RPM 已占目标值的 10%，这种
整数波动是正常的。

该反馈不能代替独立机械测量。需要确认轮轴真实转速时，应使用激光转速表、外部编码器
或高帧率视频。

## 验证测试

App 报文测试：

```bash
cd /home/arduino/ArduinoApps/ros-zdt-x57s-single-motor
python3 -B -m unittest discover -s tests -v
```

ROS 2 WebSocket 客户端测试：

```bash
cd /home/arduino/work/ros_zdt_x57s_ws
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate

PYTHONPATH=src/ventuno_zdt_motor_bridge \
  python3 -B -m unittest discover \
  -s src/ventuno_zdt_motor_bridge/test -v
```

当前实测结果为 App 测试 `6/6`、ROS 2 客户端测试 `5/5`、ROS 2 构建成功，并完成地址 1
电机的使能、10 RPM 正转、实时反馈、看门狗停车和显式停车验证。
