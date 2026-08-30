---
title: "ros-gateway-loopback：用 Custom Brick 打通 App Lab 与 ROS 2"
description: "在 VENTUNO Q 上实现 WebSocket Custom Brick，并用原生 ROS 2 节点收发 cmd_vel 与底盘状态。"
section: "app-lab"
appId: "ros-gateway-loopback"
order: 1
status: "verified"
pubDate: "2026-08-30"
updatedDate: "2026-08-30"
verifiedDate: "2026-08-30"
environment:
  - "Arduino VENTUNO Q"
  - "Ubuntu 24.04 / aarch64"
  - "ROS 2 Jazzy"
  - "Arduino App CLI 0.12.1"
  - "App runtime 0.11.0"
  - "websockets 17.1"
capabilities:
  - "Custom Brick"
  - "WebSocket"
  - "ROS 2"
---

本教程实现一个不依赖电机硬件的通信网关：App Lab 容器中的 Custom Brick 提供
WebSocket 服务，VENTUNO Q 宿主系统中的原生 ROS 2 节点通过该服务收发底盘命令与状态。

这个 App 不访问 CAN、不调用 MCU Bridge，也不会使能电机，适合先验证 App Lab 与
ROS 2 之间的通信链路。

## 实现结果

完成后可以获得以下接口：

| 接口 | 类型 | 方向 | 用途 |
| --- | --- | --- | --- |
| `/cmd_vel` | `geometry_msgs/msg/Twist` | ROS 2 → App | 发送底盘速度 |
| `/ventuno/connection` | `std_msgs/msg/Bool` | App → ROS 2 | WebSocket 连接状态 |
| `/ventuno/base_state` | `std_msgs/msg/String` | App → ROS 2 | 原始底盘状态 JSON |
| `ws://127.0.0.1:8765/ros` | WebSocket/JSON | 双向 | ROS 2 与 Custom Brick 通道 |

网关同时实现：

- 单客户端控制权
- 协议版本和消息类型检查
- 严格递增的消息序号
- 时间戳、字段类型和速度范围检查
- 300 ms 速度命令看门狗
- 3 秒应用层心跳超时
- 有界消息队列
- 断线自动进入安全停车回调
- ROS 2 客户端每 2 秒自动重连

## 数据流

```text
/cmd_vel
   ↓
ventuno_app_bridge_node（宿主 ROS 2）
   ↓ WebSocket JSON
ws://127.0.0.1:8765/ros
   ↓
ros_gateway Custom Brick（App Lab 容器）
   ↓
ros-gateway-loopback App 回调
```

Custom Brick 的 `id` 必须与 `bricks/<id>` 目录名一致，自定义 Brick ID 不添加命名空间
前缀，因此这里使用 `ros_gateway`。目录和生命周期规则参见
[Arduino Custom Bricks](https://docs.arduino.cc/software/app-lab/bricks/custom-bricks/)
和 [Bricks Reference](https://docs.arduino.cc/software/app-lab/bricks/bricks-reference/)。

## 目录结构

App Lab App：

```text
/home/arduino/ArduinoApps/ros-gateway-loopback/
├── app.yaml
├── python/
│   └── main.py
├── bricks/
│   └── ros_gateway/
│       ├── __init__.py
│       ├── gateway.py
│       ├── protocol.py
│       ├── brick_config.yaml
│       ├── requirements.txt
│       └── README.md
└── tests/
    ├── test_protocol.py
    ├── loopback_client.py
    └── runtime_edge_cases.py
```

原生 ROS 2 工作区：

```text
/home/arduino/work/ventuno_ros2_ws/
├── .venv/
├── src/
│   └── ventuno_app_bridge/
│       ├── package.xml
│       ├── setup.py
│       ├── setup.cfg
│       ├── config/bridge_params.yaml
│       ├── launch/ros_gateway.launch.py
│       ├── ventuno_app_bridge/
│       │   ├── __init__.py
│       │   ├── node.py
│       │   └── websocket_client.py
│       └── test/test_websocket_client.py
├── build/
├── install/
└── log/
```

## 配置 Custom Brick

`bricks/ros_gateway/brick_config.yaml` 声明 Brick、宿主映射端口和安全参数：

```yaml
id: ros_gateway
name: ROS Gateway
description: A reusable WebSocket gateway between App Lab and native ROS 2.
category: miscellaneous
supported_boards:
  - ventunoq
ports:
  - 8765
variables:
  - name: ROS_GATEWAY_HOST
    default_value: "0.0.0.0"
    hidden: true
  - name: ROS_GATEWAY_PORT
    default_value: "8765"
    hidden: true
  - name: ROS_GATEWAY_PATH
    default_value: "/ros"
    hidden: true
  - name: ROS_GATEWAY_MAX_VX
    default_value: "0.8"
  - name: ROS_GATEWAY_MAX_VY
    default_value: "0.8"
  - name: ROS_GATEWAY_MAX_WZ
    default_value: "1.5"
  - name: ROS_GATEWAY_COMMAND_TIMEOUT_MS
    default_value: "300"
  - name: ROS_GATEWAY_HEARTBEAT_TIMEOUT_MS
    default_value: "3000"
```

`bricks/ros_gateway/requirements.txt` 固定 WebSocket 依赖版本：

```text
websockets==17.1
```

`app.yaml` 加载本地 Brick。端口只在 Brick 中声明，App 顶层不重复声明：

```yaml
name: ROS Gateway Loopback
description: Verify Custom Brick lifecycle, port mapping, and WebSocket protocol.
ports: []
bricks:
  - ros_gateway:
      variables:
        ROS_GATEWAY_HOST: "0.0.0.0"
        ROS_GATEWAY_PORT: "8765"
        ROS_GATEWAY_PATH: "/ros"
        ROS_GATEWAY_MAX_VX: "0.8"
        ROS_GATEWAY_MAX_VY: "0.8"
        ROS_GATEWAY_MAX_WZ: "1.5"
        ROS_GATEWAY_COMMAND_TIMEOUT_MS: "300"
        ROS_GATEWAY_HEARTBEAT_TIMEOUT_MS: "3000"
icon: 🔁
```

## WebSocket 协议

客户端连接 `/ros` 后，第一条消息必须是握手：

```json
{
  "version": 1,
  "type": "hello",
  "role": "ros2",
  "node": "ventuno_app_bridge_node"
}
```

发送非零速度前，先切换到 `ROS_TELEOP`：

```json
{
  "version": 1,
  "type": "mode_change",
  "seq": 1,
  "timestamp_ms": 1788025000000,
  "mode": "ROS_TELEOP"
}
```

速度消息使用 m/s 和 rad/s：

```json
{
  "version": 1,
  "type": "cmd_vel",
  "seq": 2,
  "timestamp_ms": 1788025000100,
  "vx": 0.2,
  "vy": -0.1,
  "wz": 0.3
}
```

`seq` 在一个连接内必须严格递增。时间戳用于拒绝过期命令，本地单调时钟负责执行看门狗，
从而避免系统时间调整影响停车超时。

## 核心代码展示

下面展示当前实现的关键部分。函数注释沿用项目统一的中文注释格式。

### 1. 校验速度命令

`bricks/ros_gateway/protocol.py`：

```python
def validate_cmd_vel(message, mode, limits, command_timeout_ms, current_timestamp_ms=None):
    """
    @description             : 校验速度指令字段、模式、范围和时效性
    @param message           : 已解析的 cmd_vel 消息
    @param mode              : 当前底盘模式
    @param limits            : vx、vy、wz 的绝对值上限
    @param command_timeout_ms : 允许的最大指令年龄
    @param current_timestamp_ms : 测试时可注入的当前 Unix 毫秒时间戳
    @return                  : 规范化后的速度指令字典
    """
    if message["type"] != "cmd_vel":
        raise ProtocolError("invalid_type", "message type must be cmd_vel")

    timestamp = validate_timestamp(message, command_timeout_ms, current_timestamp_ms)
    values = {}
    for field_name in ("vx", "vy", "wz"):
        field_value = message.get(field_name)
        if isinstance(field_value, bool) or not isinstance(field_value, (int, float)):
            raise ProtocolError(
                "invalid_field",
                f"{field_name} must be a finite number",
                message.get("seq"),
            )
        field_value = float(field_value)
        if not math.isfinite(field_value):
            raise ProtocolError(
                "invalid_field",
                f"{field_name} must be a finite number",
                message.get("seq"),
            )
        if abs(field_value) > limits[field_name]:
            raise ProtocolError(
                "out_of_range",
                f"abs({field_name}) must be <= {limits[field_name]}",
                message.get("seq"),
            )
        values[field_name] = field_value

    if mode != "ROS_TELEOP" and any(value != 0.0 for value in values.values()):
        raise ProtocolError(
            "mode_denied",
            "non-zero cmd_vel requires ROS_TELEOP mode",
            message.get("seq"),
        )

    return {
        "seq": message["seq"],
        "timestamp_ms": timestamp,
        **values,
    }
```

### 2. WebSocket 看门狗

`bricks/ros_gateway/gateway.py` 使用 `@brick` 交给 App Lab 管理生命周期。连接和速度超时
共用统一的 `on_stop` 回调：

```python
@brick
class RosGateway:
    """App Lab 与原生 ROS 2 之间的 WebSocket 网关。"""

    def on_cmd_vel(self, callback):
        """
        @description         : 注册已通过安全校验的 cmd_vel 回调
        @param callback      : 接收规范化速度字典的函数
        @return              : 当前 RosGateway 实例
        """
        self._cmd_vel_callback = callback
        return self

    def on_stop(self, callback):
        """
        @description         : 注册通信异常或命令超时的统一安全停车回调
        @param callback      : 接收停车原因字符串的函数
        @return              : 当前 RosGateway 实例
        """
        self._stop_callback = callback
        return self

    def _service_timers(self, websocket):
        """
        @description         : 发送服务端心跳并执行连接与速度命令看门狗
        @param websocket     : 当前活动 WebSocket 连接
        @return              : 无返回值
        """
        current = time.monotonic()
        with self._state_lock:
            last_rx = self._last_rx_monotonic
            last_cmd = self._last_cmd_monotonic
            watchdog_triggered = self._watchdog_triggered
            last_heartbeat = self._last_server_heartbeat

        if current - last_rx > self._heartbeat_timeout_ms / 1000.0:
            raise ProtocolError("heartbeat_timeout", "client heartbeat timed out")

        if last_cmd > 0.0 and not watchdog_triggered:
            if current - last_cmd > self._command_timeout_ms / 1000.0:
                with self._state_lock:
                    self._watchdog_triggered = True
                self._invoke_stop("cmd_vel_timeout")

        if current - last_heartbeat >= 1.0:
            self._send_json(websocket, self._next_message("heartbeat"))
            with self._state_lock:
                self._last_server_heartbeat = current
```

### 3. App 注册回调

`python/main.py` 只组织 Brick API 和模拟状态。本教程阶段的安全停车只写日志：

```python
from arduino.app_utils import App
from ros_gateway import RosGateway


gateway = RosGateway()


def handle_cmd_vel(command):
    """
    @description         : 记录经过协议校验的速度指令，本阶段不控制真实电机
    @param command       : 包含 vx、vy、wz、seq 和 timestamp_ms 的速度指令
    @return              : 无返回值
    """
    print(
        "[loopback] cmd_vel accepted: "
        f"seq={command['seq']} vx={command['vx']:.3f} "
        f"vy={command['vy']:.3f} wz={command['wz']:.3f}",
        flush=True,
    )


def handle_safe_stop(reason):
    """
    @description         : 记录通信超时或断线产生的安全停车事件
    @param reason        : 触发安全停车的原因
    @return              : 无返回值
    """
    print(f"[loopback] SAFE_STOP: {reason}; no CAN command sent", flush=True)


gateway.on_cmd_vel(handle_cmd_vel)
gateway.on_stop(handle_safe_stop)

App.run(user_loop=loop)
```

### 4. ROS 2 节点转换 `/cmd_vel`

`ventuno_app_bridge/node.py`：

```python
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, String


class VentunoAppBridgeNode(Node):
    """把标准 ROS 2 速度话题转换为 App Lab WebSocket 协议。"""

    def __init__(self):
        """
        @description         : 声明参数、创建 ROS 接口并启动 WebSocket 客户端
        @param               : 无参数
        @return              : 无返回值
        """
        super().__init__("ventuno_app_bridge_node")
        self.declare_parameter("websocket_url", "ws://127.0.0.1:8765/ros")
        self.declare_parameter("reconnect_interval", 2.0)
        self.declare_parameter("heartbeat_interval", 1.0)
        self.declare_parameter("command_timeout", 0.3)

        connection_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._connection_publisher = self.create_publisher(
            Bool,
            "/ventuno/connection",
            connection_qos,
        )
        self._base_state_publisher = self.create_publisher(
            String,
            "/ventuno/base_state",
            10,
        )
        self._cmd_vel_subscription = self.create_subscription(
            Twist,
            "/cmd_vel",
            self._handle_twist,
            10,
        )

    def _handle_twist(self, message):
        """
        @description         : 将 Twist 速度消息提交到只保留最新值的发送队列
        @param message       : geometry_msgs/msg/Twist 消息
        @return              : 无返回值
        """
        self._client.send_cmd_vel(
            message.linear.x,
            message.linear.y,
            message.angular.z,
        )
```

实际 `__init__()` 还会创建 `WebSocketBridgeClient`、连接事件队列和 50 ms ROS 定时器。
WebSocket 后台线程只向有界队列写入数据，ROS 发布操作仍在 ROS 主线程执行。

### 5. 只保留最新速度

`ventuno_app_bridge/websocket_client.py` 使用长度为 1 的速度队列，避免 ROS 发布速度高于
WebSocket 发送速度时积累旧命令：

```python
def send_cmd_vel(self, vx, vy, wz):
    """
    @description         : 用最新速度覆盖尚未发送的旧速度，避免控制队列增长
    @param vx            : 纵向速度，单位 m/s
    @param vy            : 横向速度，单位 m/s
    @param wz            : 偏航角速度，单位 rad/s
    @return              : 已进入本地队列返回 True
    """
    command = {
        "timestamp_ms": self._now_ms(),
        "vx": float(vx),
        "vy": float(vy),
        "wz": float(wz),
    }
    self._replace_queue_item(self._latest_command, command)
    return True


def _send_latest_command(self, websocket):
    """
    @description         : 发送最新且未过期的速度命令
    @param websocket     : 当前 WebSocket 连接
    @return              : 无返回值
    """
    try:
        command = self._latest_command.get_nowait()
    except queue.Empty:
        return

    age_seconds = (self._now_ms() - command["timestamp_ms"]) / 1000.0
    if age_seconds > self._command_timeout:
        self._log("warning", f"dropping stale local cmd_vel: age={age_seconds:.3f}s")
        return
    self._send_json(websocket, self._next_message("cmd_vel", **command))
```

## 启动 App

```bash
arduino-app-cli app start user:ros-gateway-loopback
arduino-app-cli app logs user:ros-gateway-loopback --follow
```

确认宿主端口：

```bash
ss -ltn 'sport = :8765'
```

应看到 `0.0.0.0:8765` 和 `[::]:8765`。App 停止后端口应消失：

```bash
arduino-app-cli app stop user:ros-gateway-loopback
```

## 构建原生 ROS 2 包

桥接包使用带系统站点包的虚拟环境，以复用 VENTUNO Q 已安装的 ROS 2 Jazzy Python 包：

```bash
cd /home/arduino/work/ventuno_ros2_ws
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install websockets==17.1

source /opt/ros/jazzy/setup.bash
.venv/bin/python /usr/bin/colcon build --symlink-install
.venv/bin/python /usr/bin/colcon test --packages-select ventuno_app_bridge
.venv/bin/python /usr/bin/colcon test-result --verbose
```

`package.xml` 中必须声明 `ament_python`，维护者邮箱也必须是合法邮箱格式，否则 colcon
不会把目录识别为 `ros.ament_python` 包：

```xml
<buildtool_depend>ament_python</buildtool_depend>

<export>
  <build_type>ament_python</build_type>
</export>
```

## 运行 ROS 2 节点

先启动 App，再启动原生节点：

```bash
arduino-app-cli app start user:ros-gateway-loopback

source /opt/ros/jazzy/setup.bash
source /home/arduino/work/ventuno_ros2_ws/install/setup.bash
ros2 run ventuno_app_bridge ventuno_app_bridge_node
```

也可以通过 launch 文件启动：

```bash
ros2 launch ventuno_app_bridge ros_gateway.launch.py
```

默认参数位于 `config/bridge_params.yaml`：

```yaml
ventuno_app_bridge_node:
  ros__parameters:
    websocket_url: ws://127.0.0.1:8765/ros
    reconnect_interval: 2.0
    heartbeat_interval: 1.0
    command_timeout: 0.3
    use_twist_stamped: false
```

## 验证 ROS 2 通信

另开终端：

```bash
source /opt/ros/jazzy/setup.bash
source /home/arduino/work/ventuno_ros2_ws/install/setup.bash

ros2 topic echo --once /ventuno/connection
ros2 topic echo --once /ventuno/base_state
```

连接成功时 `/ventuno/connection` 返回：

```yaml
data: true
```

发送一次回环速度：

```bash
ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.2, y: -0.1, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.3}}"
```

App 日志应出现：

```text
[loopback] cmd_vel accepted: seq=... vx=0.200 vy=-0.100 wz=0.300
[loopback] SAFE_STOP: cmd_vel_timeout; no CAN command sent
```

第二行表示 300 ms 内没有收到新速度，网关已经调用统一安全停车回调。当前回调不会控制
硬件，只用于确认安全链路正确执行。

## 运行测试

App 协议与 WebSocket 测试：

```bash
cd /home/arduino/ArduinoApps/ros-gateway-loopback
python3 -B -m unittest tests/test_protocol.py

PYTHONPATH=.cache/.venv/lib/python3.13/site-packages \
  python3 -B tests/loopback_client.py

PYTHONPATH=.cache/.venv/lib/python3.13/site-packages \
  python3 -B tests/runtime_edge_cases.py
```

不要在宿主直接执行 `.cache/.venv/bin/python`。它由 App 容器创建，符号链接目标位于容器
内部；宿主测试应使用系统 `python3` 并通过 `PYTHONPATH` 加载 App 安装的依赖。

测试覆盖结果：

| 测试 | 结果 | 覆盖内容 |
| --- | --- | --- |
| 协议单元测试 | 8/8 | 版本、序号、时间戳、模式、速度范围 |
| 基本回环测试 | 7/7 | 握手、状态、心跳、合法与非法命令 |
| 边界测试 | 4/4 | 错误路径、单客户端、心跳超时、重连 |
| ROS 2 客户端测试 | 5/5 | 最新速度队列、过期丢弃、连接状态、队列上限 |

## 当前功能边界

- `/ventuno/base_state` 当前是模拟状态 JSON，不是电机反馈。
- `SAFE_STOP` 当前只写日志，不发送电机停止命令。
- 当前不发布 `/odom`、`/joint_states`、`/imu/data` 或 `/battery_state`。
- 当前 App 不发送 CAN 帧，也不刷写 MCU。
