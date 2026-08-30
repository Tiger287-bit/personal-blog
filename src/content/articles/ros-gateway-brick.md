---
title: "ros_gateway Brick：在 App Lab 中建立可靠的 WebSocket 通道"
description: "说明 ros_gateway 的组件边界、Python API、WebSocket 协议，以及如何由独立原生节点映射到 ROS 2。"
section: "bricks"
order: 1
pubDate: "2026-08-30"
updatedDate: "2026-08-30"
environment:
  - "Arduino VENTUNO Q"
  - "Arduino App Lab"
  - "Python 3.13"
  - "websockets 17.1"
capabilities:
  - "Custom Brick"
  - "WebSocket"
  - "JSON 协议"
  - "安全看门狗"
sourceDir: "ros-gateway-loopback"
---

`ros_gateway` 是一个 App 本地 Python Custom Brick。它在 App Lab 主容器中提供
WebSocket 服务，把经过校验的 JSON 命令交给 App 回调，并把 App 状态排队发送给客户端。

它不是 ROS 2 节点。`rclpy` 节点、话题、服务、参数和动作属于容器外的原生桥接包。
保持这个边界后，同一个 Brick 也可以被测试客户端或其他中间件使用。

## 组件在系统中的位置

```text
ROS 2 图
  ↓ 原生 ventuno_app_bridge 节点
WebSocket 客户端
  ⇅ ws://127.0.0.1:8765/ros
ros_gateway Brick
  ⇅ Python 回调和 publish_* 方法
App 的 python/main.py
```

| 能力 | 负责人 |
| --- | --- |
| 连接、握手、JSON 校验、队列、心跳 | `ros_gateway` Brick |
| ROS 2 话题、服务、参数、动作 | 原生 ROS 2 桥接节点 |
| 电机、IMU、串口等硬件行为 | App 与对应硬件 Brick |
| 断线后的真实停车 | App 注册的 `on_stop` 回调 |

## 源码目录

本文左侧“配套源码”可阅读每个完整文件。Brick 本体位于：

```text
app/bricks/ros_gateway/
├── __init__.py
├── gateway.py
├── protocol.py
├── brick_config.yaml
├── requirements.txt
└── README.md
```

同一源码树还包含最小回环 App、协议测试和原生 ROS 2 包，便于验证整个通道。

## 放入一个新 App

把完整 `ros_gateway` 目录复制到新 App 的 `bricks/` 下，不能只复制 `gateway.py`。
目录名、`brick_config.yaml` 的 `id` 和 `app.yaml` 中的引用名必须都是
`ros_gateway`。

`app.yaml`：

```yaml
name: My Gateway App
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
```

端口 `8765` 已在 Brick 的 `brick_config.yaml` 中声明，App 顶层 `ports` 不重复填写。

## 最小 Python 用法

```python
import time

from arduino.app_utils import App
from ros_gateway import RosGateway


gateway = RosGateway()


def handle_cmd_vel(command):
    print(
        f"vx={command['vx']} vy={command['vy']} wz={command['wz']}",
        flush=True,
    )


def safe_stop(reason):
    print(f"SAFE_STOP: {reason}", flush=True)


def loop():
    time.sleep(0.05)


gateway.on_cmd_vel(handle_cmd_vel)
gateway.on_stop(safe_stop)
App.run(user_loop=loop)
```

`@brick` 会把实例纳入 App 生命周期，因此不需要手动调用 `gateway.start()`。主循环应
短时返回，不能用长时间阻塞任务占住 App。

## Python API

| 方法 | 用途 |
| --- | --- |
| `on_cmd_vel(callback)` | 接收已校验的 `vx/vy/wz` 命令 |
| `on_mode_change(callback)` | 接收模式请求；返回 `False` 可拒绝 |
| `on_stop(callback)` | 统一处理命令超时、失联和 App 停止 |
| `publish_base_state(state)` | 发布底盘状态 |
| `publish_imu(imu)` | 发布 IMU 数组；正式使用前还需冻结坐标系和单位 |
| `publish_diagnostics(data)` | 发布诊断字典 |
| `is_ros_connected()` | 查询 `role=ros2` 的 WebSocket 会话是否完成握手 |
| `get_status()` | 读取连接、模式、队列和服务错误快照 |

`is_ros_connected()` 不执行 ROS 2 图发现，所以不能用它判断某个节点、话题或服务是否
存在。没有活动客户端时，三个 `publish_*` 方法返回 `False`。

## WebSocket 报文

默认端点是 `ws://127.0.0.1:8765/ros`，协议版本固定为 `1`。连接后第一条消息必须是：

```json
{
  "version": 1,
  "type": "hello",
  "role": "ros2",
  "node": "ventuno_app_bridge_node"
}
```

握手后的客户端报文必须带严格递增的 `seq` 和 Unix 毫秒 `timestamp_ms`。

| 报文 | 方向 | 含义 |
| --- | --- | --- |
| `hello`、`heartbeat` | 双向 | 会话和失联检测 |
| `mode_change`、`cmd_vel` | 客户端 → Brick | 控制命令 |
| `ack`、`error` | Brick → 客户端 | 命令结果 |
| `base_state`、`imu`、`diagnostics` | Brick → 客户端 | App 状态 |

合法的非零 `cmd_vel` 只在 `ROS_TELEOP` 模式下允许。默认 300 ms 没有刷新运动命令会
调用 `on_stop`，默认 3 秒没有任何有效客户端消息会结束连接并调用 `on_stop`。
详细字段和错误码见左侧源码中的 `README.md` 与 `protocol.py`。

## ROS 2 映射属于独立包

ROS 2 通常通过话题、服务和动作进行节点间通信；参数是节点拥有的配置。接口定义文件则
是 `.msg`、`.srv` 和 `.action`。这些概念不能和 Brick 的 Python 方法或 WebSocket
`type` 混为一张表。

本文配套 `ventuno_app_bridge` 示例目前公开：

| ROS 2 类别 | 名称 | 类型/值 |
| --- | --- | --- |
| 订阅话题 | `/cmd_vel` | `geometry_msgs/msg/Twist` 或 `TwistStamped` |
| 发布话题 | `/ventuno/connection` | `std_msgs/msg/Bool` |
| 发布话题 | `/ventuno/base_state` | `std_msgs/msg/String` |
| 参数 | `websocket_url` | 默认 `ws://127.0.0.1:8765/ros` |
| 参数 | `reconnect_interval` | 默认 `2.0 s` |
| 参数 | `heartbeat_interval` | 默认 `1.0 s` |
| 参数 | `command_timeout` | 默认 `0.3 s` |
| 参数 | `use_twist_stamped` | 默认 `false` |
| 服务 | 无业务服务 | 当前版本未定义 |
| 动作 | 无 | 当前版本未定义 |

## 验证

先启动 `ros-gateway-loopback` App，再在开发板宿主运行：

```bash
cd /home/arduino/ArduinoApps/ros-gateway-loopback
python3 -B -m unittest tests/test_protocol.py

PYTHONPATH=.cache/.venv/lib/python3.13/site-packages \
  python3 -B tests/loopback_client.py
```

测试通过应覆盖握手、心跳、模式、合法和非法速度、超时停车与状态回传。完整 App 与 ROS 2
联调方法见 [ros-gateway-loopback 教程](/app-lab/ros-gateway-loopback/)。

## 版本选择

基础回环 App 的 Brick 不包含电机报文；综合单电机 App 中的同名 Brick 是扩展版本，增加
`motor_enable`、`motor_set_speed`、`motor_stop` 和 `motor_state`。应整体复制目标版本，
不要混用两版 `gateway.py` 与 `protocol.py`。

