# ROS Gateway Custom Brick

`ros_gateway` 是一个运行在 Arduino App Lab 主容器中的 Python Custom Brick。它提供
WebSocket 服务、JSON 报文校验、单客户端控制权、心跳与运动命令看门狗，让 App 可以和
容器外的客户端交换控制命令与状态。

这个 Brick **不是 ROS 2 节点**：它不导入 `rclpy`，也不创建 ROS 2 话题、服务、参数或
动作。项目中的原生 `ventuno_app_bridge` 包才负责把 ROS 2 图中的接口转换为本 Brick 的
WebSocket 报文。

本目录是 `ros-gateway-loopback` 使用的基础协议版本，只包含底盘速度、模式和通用状态。
单电机报文是综合 App 中另一份扩展实现，不能直接假定本目录已提供。

## 组件边界

```text
ROS 2 topics / services / parameters / actions
  ↓ 由独立原生 ROS 2 节点负责映射
WebSocket 客户端
  ⇅ ws://127.0.0.1:8765/ros
ros_gateway Brick（App Lab 容器）
  ⇅ Python 回调与发布方法
App 的 python/main.py
```

| 层 | 本组件是否负责 |
| --- | --- |
| WebSocket 监听、连接和 JSON 协议 | 是 |
| 字段、范围、序号、时间戳校验 | 是 |
| 断线和命令超时回调 | 是 |
| ROS 2 话题、服务、参数、动作 | 否，由原生桥接节点负责 |
| CAN、电机、IMU 等硬件访问 | 否，由其他 Brick 或 App 回调负责 |

## 目录

```text
bricks/ros_gateway/
├── __init__.py
├── gateway.py
├── protocol.py
├── brick_config.yaml
├── requirements.txt
└── README.md
```

## 在 App 中引用

`app.yaml` 引用目录名与 `brick_config.yaml` 中 `id` 同为 `ros_gateway`：

```yaml
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
```

`@brick` 会把实例纳入 App Lab 生命周期。创建对象、注册回调后调用
`App.run(user_loop=...)`；App 启动时调用 Brick 的 `start()`，停止时调用 `stop()`。
业务循环不能阻塞 WebSocket 后台线程。

```python
from arduino.app_utils import App
from ros_gateway import RosGateway


gateway = RosGateway()


def handle_cmd_vel(command):
    print(command)


def handle_safe_stop(reason):
    # 正式机器人必须在这里执行真实硬件停车。
    print("SAFE_STOP", reason)


gateway.on_cmd_vel(handle_cmd_vel)
gateway.on_stop(handle_safe_stop)
App.run(user_loop=lambda: None)
```

## Python API

| API | 语义 |
| --- | --- |
| `on_cmd_vel(callback)` | 注册已通过协议校验的 `vx/vy/wz` 命令回调 |
| `on_mode_change(callback)` | 注册模式切换回调；显式返回 `False` 表示拒绝 |
| `on_stop(callback)` | 注册断线、心跳超时、运动命令超时及 App 停止时的统一安全回调 |
| `publish_base_state(state)` | 校验并排队发送底盘状态 |
| `publish_imu(imu)` | 校验并排队发送 IMU 状态；当前协议未冻结坐标系和单位 |
| `publish_diagnostics(data)` | 排队发送可 JSON 序列化的诊断字典 |
| `is_ros_connected()` | 是否存在完成 `role=ros2` 握手的 WebSocket 客户端 |
| `get_status()` | 返回连接、模式、队列、丢包数和服务错误快照 |

`is_ros_connected()` 的名字来自项目约定。它只说明指定角色的 WebSocket 会话已建立，
不代表 ROS 2 图发现正常，也不检查某个话题、服务或节点是否存在。

发布方法返回 `True` 表示消息进入出站队列；没有活动客户端时返回 `False`。队列已满时
会丢弃最旧消息并增加 `dropped_messages`，不会无限积压状态。

## 默认配置

| 环境变量 | 默认值 | 含义 |
| --- | --- | --- |
| `ROS_GATEWAY_HOST` | `0.0.0.0` | App 容器内监听地址 |
| `ROS_GATEWAY_PORT` | `8765` | WebSocket 端口 |
| `ROS_GATEWAY_PATH` | `/ros` | 请求路径 |
| `ROS_GATEWAY_MAX_VX` | `0.8` | `vx` 绝对值上限，m/s |
| `ROS_GATEWAY_MAX_VY` | `0.8` | `vy` 绝对值上限，m/s |
| `ROS_GATEWAY_MAX_WZ` | `1.5` | `wz` 绝对值上限，rad/s |
| `ROS_GATEWAY_COMMAND_TIMEOUT_MS` | `300` | `cmd_vel` 时效和执行看门狗 |
| `ROS_GATEWAY_HEARTBEAT_TIMEOUT_MS` | `3000` | 有效客户端消息接收超时 |

端口由 `brick_config.yaml` 声明并映射到宿主。当前默认宿主端点为：

```text
ws://127.0.0.1:8765/ros
```

## WebSocket 协议

协议版本为 `1`，每个 WebSocket 消息都是 UTF-8 JSON 对象。最大消息为 16 KiB，压缩
关闭，同时只允许一个活动控制客户端。

第一条消息必须在 2 秒内完成握手：

```json
{"version":1,"type":"hello","role":"ros2","node":"ventuno_app_bridge_node"}
```

除 `hello` 外，客户端报文都必须包含严格递增的非负整数 `seq` 和 Unix 毫秒
`timestamp_ms`。客户端时间不能比服务端超前超过 2000 ms；`cmd_vel` 还必须在默认
300 ms 时效内。

| `type` | 方向 | 用途 |
| --- | --- | --- |
| `hello` | WebSocket 双向 | 建立应用层会话 |
| `heartbeat` | WebSocket 双向 | 检测通信失联 |
| `mode_change` | 客户端 → Brick | 请求 `IDLE`、`ROS_TELEOP` 或 `ESTOP` |
| `cmd_vel` | 客户端 → Brick | 提交 `vx`、`vy`、`wz` |
| `ack`、`error` | Brick → 客户端 | 返回命令结果或结构化错误 |
| `base_state`、`imu`、`diagnostics` | Brick → 客户端 | 发送 App 状态 |

非零 `cmd_vel` 只允许在 `ROS_TELEOP` 模式下执行。合法速度超过
`ROS_GATEWAY_COMMAND_TIMEOUT_MS` 未刷新时会调用一次 `on_stop("cmd_vel_timeout")`；
WebSocket 断线、心跳超时或 App 停止也会调用 `on_stop`。Brick 只能触发回调，真正停车
必须由 App 在回调中实现。

## 与 ROS 2 的关系

当前 `ventuno_app_bridge` 示例节点提供以下 **ROS 2 公共 API**：

| ROS 2 类别 | 名称 | 类型 |
| --- | --- | --- |
| 话题订阅 | `/cmd_vel` | `geometry_msgs/msg/Twist` 或 `TwistStamped` |
| 话题发布 | `/ventuno/connection` | `std_msgs/msg/Bool` |
| 话题发布 | `/ventuno/base_state` | `std_msgs/msg/String` |
| 参数 | `websocket_url` 等 5 项 | 节点参数 |
| 服务 | 无业务服务 | 当前示例未定义 |
| 动作 | 无 | 当前示例未定义 |

上述接口属于独立 ROS 2 包，不属于 Brick。ROS 2 中 `.msg`、`.srv`、`.action` 是接口定义；
参数是节点持有的配置，并通过 ROS 2 参数服务和事件机制访问。

## 版本兼容

基础回环 App 与综合电机 App 中的 `ros_gateway` 源码不是同一版本：综合 App 增加了
`motor_enable`、`motor_set_speed`、`motor_stop`、`motor_state` 和相应 Python API。
复制 Brick 时应复制完整目录并以本目录 README 为准，不能只复制同名文件后混用两版
`gateway.py` 与 `protocol.py`。

