# ros_ws_bridge 使用说明

`ros_ws_bridge` 是一个可复用的 ROS 2 ↔ WebSocket bridge。它按 YAML 路由 ROS topic，
动态加载 ROS 消息类型，并在 ROS 2 与 App Lab 之间双向传输 JSON 文本帧。

App Lab 侧使用协议无关的 `websocket_server` Brick；Brick 只负责 WebSocket 连接，
不解析 ROS 或 JSON。四灯 App 的业务适配由 App `main.py` 完成，MCU 通过高层
`set_leds/get_leds` Bridge RPC 工作。

## JSON 信封

每条消息包含以下字段：

| 字段 | 说明 |
| --- | --- |
| `topic` | 绝对 ROS topic 名 |
| `ros_type` | ROS 类型，例如 `std_msgs/msg/String` |
| `direction` | `ros_to_ws` 或 `ws_to_ros` |
| `seq` | 非负整数序号 |
| `timestamp` | Unix epoch 毫秒时间戳 |
| `data` | ROS 消息字段对象 |

例如 String 的 `data` 为 `{"data": "hello"}`。`timestamp` 的字段名是
`timestamp`，不是旧协议中的 `timestamp_ms`；不需要额外添加 `version`、`hello` 或
`heartbeat` 字段。

## 已验证类型

动态类型加载已验证：

- `std_msgs/msg/String`
- `std_msgs/msg/Bool`
- `std_msgs/msg/Int32`
- `std_msgs/msg/Float32`
- `std_msgs/msg/UInt8MultiArray`
- `std_msgs/msg/Int32MultiArray`
- `std_msgs/msg/Float32MultiArray`
- `geometry_msgs/msg/Twist`（仅类型加载验证）

## 配置文件

配置位于源码包的 `config/` 目录，安装后位于：

```text
install/ros_ws_bridge/share/ros_ws_bridge/config/
```

- `bridge.yaml`：通用 demo 路由，包含 String 和 UInt8MultiArray 示例。
- `led.yaml`：四灯 profile，连接 `ws://127.0.0.1:8765/ros`，使用：
  - `/my_ros2_02/led_command`：`UInt8MultiArray`，`ros_to_ws`
  - `/my_ros2_02/led_state`：`UInt8MultiArray`，`ws_to_ros`
  - `/my_ros2_02/error`：`String`，`ws_to_ros`

## 构建与启动

在机器人端执行：

```bash
cd ~/ros2_ws/codex
source /opt/ros/jazzy/setup.bash
colcon build --packages-select ros_ws_bridge --symlink-install
source install/setup.bash
```

使用四灯 profile 启动：

```bash
ros2 run ros_ws_bridge bridge_node \
  --ros-args \
  -p config_file:=/home/arduino/ros2_ws/codex/install/ros_ws_bridge/share/ros_ws_bridge/config/led.yaml
```

启动后可检查：

```bash
ros2 node info /ros_ws_bridge
ros2 topic info /my_ros2_02/led_command -v
ros2 topic echo /my_ros2_02/led_state
```

四灯 `/my_ros2_02` ROS 2 → WebSocket → App Lab → MCU → 状态回传链路已由用户确认
打通。四个 LED 值必须是按 LED1 到 LED4 排列的四个 `0/1` 值；App 通过
`set_leds` 设置后再用 `get_leds` 回读实际状态。

## `/cmd_vel` 安全边界

`geometry_msgs/msg/Twist` 目前只完成动态类型加载验证；`/cmd_vel` 的 App、MCU、
运动学和实车链路均未验证。禁止发送非零运动命令。

未来若要做 transport-only 验证，应先使用全零 Twist，并确保不调用真实运动 API。
任何非零验证都必须先获得明确授权，确认急停有效、车轮悬空或测试区域清空，并验证
MCU watchdog、通信中断停车和故障状态机。App 只能调用高层 `set_twist`，不能生成
底层 CAN 帧、PWM 或电机电信号。

## App Lab 端口提醒

四灯 App 使用 8765 端口和 `/ros` 路径；同一时刻只能有一个 App 占用该端口。切换
App 前先检查：

```bash
arduino-app-cli app list
ss -ltnH | awk '$4 ~ /:8765$/ {print}'
```

App Lab 的 Run/部署流程可能编译并烧录 MCU Sketch；四灯 App 启动时还会初始化 LED
为全灭。涉及真实 App 启动、停止或切换时，先确认目标和硬件影响并取得授权。

