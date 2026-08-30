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
sourceDir: "ros-gateway-loopback"
---

本教程实现一个不依赖电机硬件的通信网关：App Lab 容器中的 Custom Brick 提供
WebSocket 服务，VENTUNO Q 宿主系统中的原生 ROS 2 节点通过该服务收发底盘命令与状态。

这个 App 不访问 CAN、不调用 MCU Bridge，也不会使能电机，适合先验证 App Lab 与
ROS 2 之间的通信链路。

## 实现结果

完成后会得到两层不同的 API。原生 ROS 2 节点公开以下话题：

| ROS 2 话题 | 消息类型 | 节点行为 | 用途 |
| --- | --- | --- | --- |
| `/cmd_vel` | `geometry_msgs/msg/Twist` | 订阅 | 接收底盘速度 |
| `/ventuno/connection` | `std_msgs/msg/Bool` | 发布 | 发布 WebSocket 连接状态 |
| `/ventuno/base_state` | `std_msgs/msg/String` | 发布 | 发布原始底盘状态 JSON |

Custom Brick 另外提供 `ws://127.0.0.1:8765/ros` WebSocket/JSON 端点。它是
App Lab 与原生客户端之间的传输协议，不是 ROS 2 话题、服务、参数或动作。

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

## WebSocket/JSON 通信协议

本节记录的是当前 `ros_gateway` Brick 和 `ventuno_app_bridge` ROS 2 包实际执行的
协议版本，不是后续电机控制协议的设想。当前协议版本固定为 `1`。

### 传输层约定

| 项目 | 当前约定 |
| --- | --- |
| 传输协议 | WebSocket |
| 默认地址 | `ws://127.0.0.1:8765/ros` |
| App 容器监听地址 | `0.0.0.0:8765` |
| 消息编码 | UTF-8 JSON |
| JSON 根节点 | 对象 |
| 最大 WebSocket 消息 | 16 KiB |
| WebSocket 压缩 | 关闭 |
| WebSocket Ping | 间隔 1 秒，超时 1 秒 |
| 应用层心跳 | 默认间隔 1 秒，接收超时 3 秒 |
| 同时控制客户端 | 1 个 |

请求路径必须为 `/ros`，查询字符串不参与路径比较。其他路径会以 WebSocket 关闭码
`1008` 拒绝。已有客户端占用网关时，第二个客户端会收到关闭码 `1013`，不能抢占控制权。

### 通用消息信封

除客户端第一条 `hello` 外，客户端发送的消息都使用以下基础字段：

```json
{
  "version": 1,
  "type": "heartbeat",
  "seq": 1,
  "timestamp_ms": 1788025000000
}
```

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `version` | 整数 | 必须等于 `1`，布尔值不算整数 |
| `type` | 字符串 | 必须是非空字符串 |
| `seq` | 非负整数 | 同一客户端连接内严格递增；`hello` 不携带 |
| `timestamp_ms` | 正整数 | Unix Epoch 毫秒时间戳；`hello` 不携带 |

所有带时间戳的客户端消息都不能比服务端时间超前超过 2000 ms。当前 `heartbeat` 和
`mode_change` 只检查时间戳有效性及未来偏差，不限制消息年龄；`cmd_vel` 还额外执行默认
300 ms 的过期检查。

客户端命令的 `seq` 是独立序列。握手完成后服务端把最近接收序号初始化为 `-1`，因此首条
命令可以从 `0` 或 `1` 开始；官方 ROS 2 客户端从 `1` 开始。只有通过校验的消息才会推进
服务端记录的客户端序号。

服务端发送的 `heartbeat`、`base_state`、`imu` 和 `diagnostics` 使用服务端自己的事件序号。
`ack.seq` 和带 `seq` 的 `error.seq` 则回显客户端请求序号，用于请求关联。因此客户端不能把
所有服务端消息的 `seq` 混在一起执行全局递增校验。

### 连接状态机

```text
WebSocket 已建立
      ↓ 2 秒内必须发送 hello
等待握手
      ↓ hello 校验通过
IDLE
      ↓ mode_change: ROS_TELEOP
ROS_TELEOP ── cmd_vel ──→ App 速度回调
      ↓ 300 ms 没有新 cmd_vel
安全停车回调（连接保持，模式仍为 ROS_TELEOP）

任意已握手状态
      ├── mode_change: IDLE / ESTOP / ROS_TELEOP
      ├── 3 秒没有收到有效客户端消息 → 关闭连接
      └── WebSocket 断开 → 模式恢复 IDLE，并调用安全停车回调
```

当前 `ESTOP` 只是协议模式。这个回环 App 没有真实电机，也没有实现硬件急停锁存。

### 消息类型总表

| `type` | 方向 | 是否需要 `seq` | 用途 |
| --- | --- | --- | --- |
| `hello` | 双向 | 否 | 建立应用层会话 |
| `heartbeat` | 双向 | 客户端需要；服务端事件自带 | 保持连接并检测失联 |
| `mode_change` | WebSocket 客户端 → Brick | 是 | 请求 `IDLE`、`ROS_TELEOP` 或 `ESTOP` |
| `cmd_vel` | WebSocket 客户端 → Brick | 是 | 提交底盘纵向、横向和旋转速度 |
| `ack` | Brick → WebSocket 客户端 | 回显请求 `seq` | 返回模式切换结果 |
| `error` | Brick → WebSocket 客户端 | 能识别请求序号时回显 | 返回结构化协议错误 |
| `base_state` | Brick → WebSocket 客户端 | 服务端事件序号 | 发布底盘状态 |
| `imu` | Brick → WebSocket 客户端 | 服务端事件序号 | 预留的 IMU 状态消息 |
| `diagnostics` | Brick → WebSocket 客户端 | 服务端事件序号 | 预留的诊断消息 |

### 1. 客户端握手 `hello`

客户端连接 `/ros` 后，必须在 2 秒内把 `hello` 作为第一条消息：

```json
{
  "version": 1,
  "type": "hello",
  "role": "ros2",
  "node": "ventuno_app_bridge_node"
}
```

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `role` | 字符串 | 必须严格等于 `ros2` |
| `node` | 字符串 | 去除首尾空格后长度为 1～128 个字符 |

握手消息不携带 `seq` 和 `timestamp_ms`。校验通过后，App 返回：

```json
{
  "version": 1,
  "type": "hello",
  "timestamp_ms": 1788025000000,
  "role": "app",
  "node": "ros-gateway-loopback"
}
```

首条消息不是 `hello`、角色错误或节点名称非法时，服务端先发送 `error`，再以关闭码
`1008` 结束连接。连接中再次发送 `hello` 会返回 `duplicate_hello`，但不会主动关闭连接。

### 2. 应用层心跳 `heartbeat`

ROS 2 客户端默认每秒发送一次：

```json
{
  "version": 1,
  "type": "heartbeat",
  "seq": 1,
  "timestamp_ms": 1788025000000
}
```

服务端也默认每秒发送一次：

```json
{
  "version": 1,
  "type": "heartbeat",
  "seq": 27,
  "timestamp_ms": 1788025000012
}
```

客户端的 `heartbeat`、`mode_change` 或 `cmd_vel` 只要通过校验，都会刷新服务端的最后接收
时间。连续 3 秒没有任何有效客户端消息时，服务端发送 `heartbeat_timeout` 错误，调用安全
停车回调，并以关闭码 `1008` 结束连接。

### 3. 模式切换 `mode_change`

允许的模式只有：

| 模式 | 含义 |
| --- | --- |
| `IDLE` | 空闲；只允许零速度命令 |
| `ROS_TELEOP` | ROS 2 控制；允许范围内的非零速度命令 |
| `ESTOP` | 协议急停状态；只允许零速度命令 |

请求示例：

```json
{
  "version": 1,
  "type": "mode_change",
  "seq": 2,
  "timestamp_ms": 1788025000100,
  "mode": "ROS_TELEOP"
}
```

接受请求时返回：

```json
{
  "version": 1,
  "type": "ack",
  "timestamp_ms": 1788025000110,
  "seq": 2,
  "command": "mode_change",
  "accepted": true,
  "mode": "ROS_TELEOP"
}
```

如果 App 的模式回调拒绝切换，`accepted` 为 `false`，`mode` 返回未改变的当前模式。当前
回环 App 的模式回调始终返回 `true`。每次 ROS 2 客户端重新连接后，都会自动请求初始模式
`ROS_TELEOP`。

### 4. 速度命令 `cmd_vel`

```json
{
  "version": 1,
  "type": "cmd_vel",
  "seq": 3,
  "timestamp_ms": 1788025000200,
  "vx": 0.2,
  "vy": -0.1,
  "wz": 0.3
}
```

| 字段 | 单位 | 默认范围 | ROS 2 来源 |
| --- | --- | --- | --- |
| `vx` | m/s | `-0.8 ～ 0.8` | `Twist.linear.x` |
| `vy` | m/s | `-0.8 ～ 0.8` | `Twist.linear.y` |
| `wz` | rad/s | `-1.5 ～ 1.5` | `Twist.angular.z` |

三个速度字段必须是有限数值，字符串、布尔值、`NaN` 和无穷值均非法。非零速度只有在
`ROS_TELEOP` 模式下才会被接受；零速度在三个模式下都允许。

速度消息的 `timestamp_ms` 不能比服务端当前时间早超过 300 ms，也不能超前超过 2000 ms。
这些限制分别对应 `stale_command` 和 `future_timestamp`。

合法 `cmd_vel` 不返回 `ack`。成功只能通过没有收到 `error`、App 日志中的
`cmd_vel accepted`，以及后续状态消息进行确认。收到一条合法速度后，如果 300 ms 内没有
下一条合法速度，服务端调用一次 `cmd_vel_timeout` 安全停车回调，但保持 WebSocket 连接。
下一条合法速度会重新启动看门狗。

### 5. 底盘状态 `base_state`

当前回环 App 每秒发送一次模拟状态：

```json
{
  "version": 1,
  "type": "base_state",
  "timestamp_ms": 1788025000300,
  "seq": 28,
  "mode": "ROS_TELEOP",
  "enabled": false,
  "wheel_position": [0.0, 0.0, 0.0, 0.0],
  "wheel_velocity": [0.0, 0.0, 0.0, 0.0],
  "battery_voltage": 0.0,
  "estop": false,
  "fault_code": 0
}
```

| 字段 | 当前含义 |
| --- | --- |
| `mode` | 网关当前协议模式 |
| `enabled` | 底盘驱动是否使能；当前固定为 `false` |
| `wheel_position` | 四个数值组成的位置数组；当前固定为零 |
| `wheel_velocity` | 四个数值组成的速度数组；当前固定为零 |
| `battery_voltage` | 电池电压；当前固定为 `0.0` |
| `estop` | 急停状态；当前固定为 `false` |
| `fault_code` | 综合故障码；当前固定为 `0` |

当前实现只校验两个四轮数组包含四个数值，尚未冻结四个下标对应的轮位顺序，也没有在协议
中固定位置和轮速单位。接入真实麦克纳姆底盘前，必须明确 `FL/FR/RL/RR` 顺序及 `rad`、
`rad/s` 等单位，不能由使用者自行猜测。

ROS 2 节点暂时不拆分这些字段，而是把整条 JSON 紧凑编码后发布为：

```text
/ventuno/base_state    std_msgs/msg/String
```

### 6. IMU 与诊断消息

Brick 已提供以下出站消息接口，但当前回环 App 没有发布它们，ROS 2 节点也没有转换它们。

`imu` 的结构为：

```json
{
  "version": 1,
  "type": "imu",
  "timestamp_ms": 1788025000400,
  "seq": 29,
  "orientation": [0.0, 0.0, 0.0, 1.0],
  "angular_velocity": [0.0, 0.0, 0.0],
  "linear_acceleration": [0.0, 0.0, 0.0]
}
```

当前代码只校验数组长度和元素为数值，尚未冻结四元数顺序、坐标系、单位、协方差和
`frame_id`，因此本消息暂时不能直接等同于 ROS 2 `sensor_msgs/msg/Imu`。

`diagnostics` 在通用信封后附加应用提供的诊断字段。诊断字段不得覆盖 `version`、`type`、
`seq` 或 `timestamp_ms` 等信封字段；后续正式协议应进一步固定诊断结构。

### 7. 错误消息 `error`

```json
{
  "version": 1,
  "type": "error",
  "timestamp_ms": 1788025000500,
  "seq": 4,
  "code": "out_of_range",
  "message": "abs(vx) must be <= 0.8"
}
```

`seq` 只在服务端能够识别原始请求序号时出现。`code` 用于程序判断，`message` 用于日志，
客户端不应根据英文 `message` 文本分支处理。

| 错误码 | 含义 |
| --- | --- |
| `invalid_encoding` | 二进制消息不是合法 UTF-8 |
| `invalid_frame` | 收到的内容不是文本或 UTF-8 字节数据 |
| `invalid_json` | JSON 无法解析 |
| `invalid_message` | JSON 根节点不是对象 |
| `unsupported_version` | `version` 不是整数 `1` |
| `invalid_type` | `type` 缺失、为空或与校验目标不符 |
| `hello_required` | 第一条消息不是 `hello` |
| `invalid_role` | 握手角色不是 `ros2` |
| `invalid_node` | 节点名称为空或超过 128 个字符 |
| `duplicate_hello` | 已握手连接再次发送 `hello` |
| `invalid_seq` | `seq` 不是非负整数 |
| `non_monotonic_seq` | `seq` 没有严格增大 |
| `invalid_timestamp` | 时间戳不是正整数 |
| `future_timestamp` | 时间戳比服务端时间超前超过 2000 ms |
| `stale_command` | `cmd_vel` 比服务端时间滞后超过命令超时 |
| `invalid_mode` | 模式不在允许集合中 |
| `invalid_field` | `vx`、`vy` 或 `wz` 不是有限数值 |
| `out_of_range` | 速度绝对值超过配置上限 |
| `mode_denied` | 非 `ROS_TELEOP` 模式发送非零速度 |
| `unknown_type` | 消息类型不在客户端消息集合中 |
| `heartbeat_timeout` | 超过心跳超时时间没有收到有效客户端消息 |

握手之后的一般消息错误只返回 `error`，连接保持，可以使用更大的新 `seq` 继续发送。握手
错误和 `heartbeat_timeout` 会在错误响应后以关闭码 `1008` 断开连接。

### 8. 正常通信时序

```text
ROS 2 客户端                              App Lab ros_gateway
     │                                            │
     ├── WebSocket connect /ros ─────────────────>│
     ├── hello(role=ros2) ───────────────────────>│
     │<──────────────────── hello(role=app) ──────┤
     ├── mode_change(seq=1, ROS_TELEOP) ─────────>│
     │<──────── ack(seq=1, accepted=true) ────────┤
     ├── heartbeat(seq=2) ───────────────────────>│
     ├── cmd_vel(seq=3) ─────────────────────────>│
     │<──────────── base_state(server seq) ───────┤
     │<──────────── heartbeat(server seq) ────────┤
     │                                            │
     │          300 ms 没有下一条 cmd_vel         │
     │                   SAFE_STOP 回调（无报文）  │
     │                                            │
     │          3 秒没有任何有效客户端消息        │
     │<──────── error(heartbeat_timeout) ─────────┤
     │<──────── WebSocket close 1008 ─────────────┤
```

注意：`cmd_vel_timeout` 当前只调用 App 内部安全停车回调，不会额外发送 WebSocket 消息；
ROS 2 端只能从后续状态或诊断消息获知真实停车结果。正式机器人协议需要补充明确的执行状态
反馈，不能把“消息通过校验”等同于“电机已经执行”。

### 9. 原生 ROS 2 节点的话题映射

| ROS 2 话题 | WebSocket 映射 | 当前行为 |
| --- | --- | --- |
| `/cmd_vel` `Twist` | `linear.x → vx`、`linear.y → vy`、`angular.z → wz` | 只保留尚未发送的最新速度 |
| `/cmd_vel` `TwistStamped` | 同上 | `use_twist_stamped=true` 时启用 |
| `/ventuno/connection` `Bool` | WebSocket 握手状态 | Reliable + Transient Local |
| `/ventuno/base_state` `String` | 完整 `base_state` JSON | 当前不拆字段 |
| ROS 日志 | `ack`、`error` | ACK 记 info，错误记 warning |

ROS 2 客户端本地速度队列长度为 `1`，新速度覆盖尚未发送的旧速度；超过本地
`command_timeout` 的速度会在发送前丢弃。连接断开后默认每 2 秒重试一次，并在每次握手成功
后重新请求 `ROS_TELEOP`。

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
