---
title: "ROS 2 与 App 通讯 01：用四组 LED 跑通双向链路"
description: "从 ROS 2 话题出发，经 ros_ws_bridge、WebSocket、Arduino App 和 RouterBridge 控制 VENTUNO Q 的四组 LED，并回读真实状态。"
section: "ros2-app"
appId: "my-ros2-02-led-demo"
order: 1
status: "verified"
pubDate: "2026-09-05"
updatedDate: "2026-09-05"
environment:
  - "Arduino VENTUNO Q"
  - "ROS 2 Jazzy"
  - "Arduino App Lab"
  - "Arduino RouterBridge"
capabilities:
  - "ROS 2 Topic"
  - "WebSocket"
  - "RouterBridge RPC"
  - "LED"
sourceDir: "ros2-app-led-demo"
---

这个示例用 VENTUNO Q 上的四组 LED 验证一条完整的双向链路。ROS 2 发布四个开关值，
Arduino App 收到后调用 MCU，MCU 设置 LED；随后 App 再读取 MCU 保存的状态并发回 ROS 2。

## 完成后得到什么

运行成功后，可以使用一条普通 ROS 2 命令控制四组 LED：

```bash
ros2 topic pub --once \
  /my_ros2_02/led_command \
  std_msgs/msg/UInt8MultiArray \
  "{data: [1, 0, 1, 0]}"
```

四个数字依次对应 `LED1`、`LED2`、`LED3`、`LED4`：

| 数值 | 含义 |
| --- | --- |
| `0` | 熄灭 |
| `1` | 点亮 |

命令执行后，`LED1` 和 `LED3` 点亮，另外两组熄灭。实际状态从下面的话题返回：

```bash
ros2 topic echo /my_ros2_02/led_state
```

## 通信链路

```text
/my_ros2_02/led_command
          ↓
ros_ws_bridge（原生 ROS 2 节点）
          ↓ WebSocket JSON
websocket_server（App 内的通用 Brick）
          ↓ Python 业务适配
set_leds / get_leds（RouterBridge RPC）
          ↓
VENTUNO Q MCU → 四组板载 LED
          ↓
/my_ros2_02/led_state
```

这条链路有三种不同接口，不能混为一谈：

| 所在层 | 接口 | 作用 |
| --- | --- | --- |
| ROS 2 | Topic | ROS 2 节点之间传递 LED 命令和状态 |
| App 与 ROS 2 | WebSocket + JSON | 穿过 App 容器边界传输 ROS 消息数据 |
| App 与 MCU | RouterBridge RPC | 调用 MCU 的 `set_leds()` 和 `get_leds()` |

`set_leds` 和 `get_leds` 是 RouterBridge RPC，不是 ROS 2 Service。这个示例的 ROS 2 一侧
只使用 Topic。

## ROS 2 接口

| 名称 | 消息类型 | 方向 | 用途 |
| --- | --- | --- | --- |
| `/my_ros2_02/led_command` | `std_msgs/msg/UInt8MultiArray` | ROS 2 → App | 四个 LED 目标值 |
| `/my_ros2_02/led_state` | `std_msgs/msg/UInt8MultiArray` | App → ROS 2 | MCU 回读状态 |
| `/my_ros2_02/error` | `std_msgs/msg/String` | App → ROS 2 | 非法消息或 MCU 调用错误 |

## 完整源码目录

文章左侧“配套源码”已经收录这个示例运行所需的全部源文件：

```text
ros2-app-led-demo/
├── app/
│   ├── app.yaml
│   ├── python/main.py
│   ├── sketch/
│   │   ├── sketch.ino
│   │   └── sketch.yaml
│   └── bricks/websocket_server/
└── ros2/
    ├── my_ros2_02_led_bridge/
    └── ros_ws_bridge/
```

其中：

- `app/` 是完整 Arduino App；
- `my_ros2_02_led_bridge/` 是入门用的命令发布者和订阅者；
- `ros_ws_bridge/` 是真正连接 WebSocket 与 ROS 2 Topic 的通用桥接包；
- 测试、包清单、许可证和资源索引文件也保留在源码树中。

## MCU 怎样控制 LED

Sketch 启动 RouterBridge，并注册两个函数：

```cpp
const bool bridgeReady = Bridge.begin();

if (bridgeReady) {
  Bridge.provide("set_leds", set_leds);
  Bridge.provide("get_leds", get_leds);
}
```

VENTUNO Q 的板载 LED 是低电平点亮。ROS 2 和 App 始终使用正常语义，也就是 `true` 表示
点亮，只有 `writeLedGroup()` 在真正写引脚时进行一次电平反转。

`get_leds()` 使用一个字节保存四组状态：bit 0～3 分别表示 LED1～LED4。App 将这个位掩码
转换回四个 `0/1`，再发布到 `/my_ros2_02/led_state`。

## WebSocket 消息格式

桥接器发送给 App 的命令如下：

```json
{
  "direction": "ros_to_ws",
  "topic": "/my_ros2_02/led_command",
  "ros_type": "std_msgs/msg/UInt8MultiArray",
  "seq": 1,
  "timestamp": 1788566400000,
  "data": {
    "layout": {"dim": [], "data_offset": 0},
    "data": [1, 0, 1, 0]
  }
}
```

| 字段 | 含义 |
| --- | --- |
| `direction` | 数据方向，命令固定为 `ros_to_ws` |
| `topic` | ROS 2 话题名 |
| `ros_type` | ROS 2 消息类型 |
| `seq` | 非负消息序号 |
| `timestamp` | Linux 生成的 Unix Epoch 毫秒时间戳 |
| `data` | ROS 2 消息转换后的字段对象 |

App 会验证方向、话题、类型、序号、时间戳和数组内容。只有四个值且每个值都是 `0` 或 `1`
时，命令才会送入 MCU。

## 准备源码

把配套源码下载到开发板后，按下面的目标目录保存：

```text
/home/arduino/ArduinoApps/my-ros2-02-led-demo
/home/arduino/ros2_ws/self_ros2_ws/src/my_ros2_02_led_bridge
/home/arduino/ros2_ws/codex/src/ros_ws_bridge
```

不要复制 `.cache`、`.venv`、`build`、`install`、`log` 或 `__pycache__`。这些是运行或构建时
重新生成的文件，不属于源码。

## 构建 ROS 2 包

先构建入门包：

```bash
cd /home/arduino/ros2_ws/self_ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --packages-select my_ros2_02_led_bridge --symlink-install
```

再构建通用桥接包：

```bash
cd /home/arduino/ros2_ws/codex
source /opt/ros/jazzy/setup.bash
colcon build --packages-select ros_ws_bridge --symlink-install
```

## 先做纯 ROS 2 测试

纯 ROS 2 测试不启动 App，也不操作硬件。终端 1：

```bash
export ROS_DOMAIN_ID=44
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
source /opt/ros/jazzy/setup.bash
source /home/arduino/ros2_ws/self_ros2_ws/install/setup.bash
ros2 run my_ros2_02_led_bridge led_command_subscriber
```

终端 2：

```bash
export ROS_DOMAIN_ID=44
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
source /opt/ros/jazzy/setup.bash
source /home/arduino/ros2_ws/self_ros2_ws/install/setup.bash
ros2 run my_ros2_02_led_bridge led_command_publisher
```

发布者每两秒循环发送：

```text
[0, 0, 0, 0]
[1, 0, 1, 0]
[0, 1, 0, 1]
[1, 1, 1, 1]
```

订阅者能够按相同顺序打印数据，就说明 ROS 2 包本身正常。

## 启动真实 App 链路

同一时间只运行一个使用 8765 端口的 Arduino App：

```bash
arduino-app-cli app list
arduino-app-cli app start /home/arduino/ArduinoApps/my-ros2-02-led-demo
```

App 启动会编译或刷写 Sketch。启动完成后，在 ROS 2 终端运行：

```bash
export ROS_DOMAIN_ID=44
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
source /opt/ros/jazzy/setup.bash
source /home/arduino/ros2_ws/codex/install/setup.bash

ros2 run ros_ws_bridge bridge_node \
  --ros-args \
  -p config_file:=/home/arduino/ros2_ws/codex/install/ros_ws_bridge/share/ros_ws_bridge/config/led.yaml
```

## 验证真实 LED

另开终端并加载相同 ROS 2 环境：

```bash
export ROS_DOMAIN_ID=44
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
source /opt/ros/jazzy/setup.bash
source /home/arduino/ros2_ws/codex/install/setup.bash
```

先监听回读状态：

```bash
ros2 topic echo /my_ros2_02/led_state
```

再发布一条命令：

```bash
ros2 topic pub --once \
  /my_ros2_02/led_command \
  std_msgs/msg/UInt8MultiArray \
  "{data: [1, 0, 1, 0]}"
```

正确结果需要同时满足：

1. LED1、LED3 点亮，LED2、LED4 熄灭；
2. `/my_ros2_02/led_state` 返回 `[1, 0, 1, 0]`；
3. `/my_ros2_02/error` 没有错误消息。

停止 ROS 2 桥接节点后，WebSocket 断开回调会尝试把四组 LED 全部熄灭。

## 常见问题

### 8765 端口已经被占用

```bash
arduino-app-cli app list
ss -ltnH | awk '$4 ~ /:8765$/ {print}'
```

先确认占用者，再停止正确的旧 App。不要同时启动两个监听 8765 端口的 App。

### 话题存在但 LED 不变化

依次检查：

1. `ros_ws_bridge` 使用的是 `led.yaml`；
2. App 日志中 WebSocket 客户端数量为 1；
3. App 能成功调用 `set_leds` 和 `get_leds`；
4. 数组必须恰好包含四个 `0/1`。

### LED 状态和引脚电平相反

这是板载 LED 的 active-low 电路特性。业务层的 `1` 仍然表示点亮，不要在 ROS 2 或 App
中再次反转。
