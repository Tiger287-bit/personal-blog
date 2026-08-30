# ROS Gateway Custom Brick（单电机扩展版）

本目录中的 `ros_gateway` 是 App Lab 主容器内的 WebSocket/JSON 网关。它不是 ROS 2
节点，也不直接访问电机或 CAN；独立原生 ROS 2 包负责 ROS 图接口，App 注册的回调负责
调用电机 Brick。

这一份源码是在基础 `ros-gateway-loopback` 版本上增加单电机报文的扩展版。两份源码的
`gateway.py` 和 `protocol.py` 不相同，复制时必须复制完整目录，不能交叉混用。

## 数据边界

```text
原生 ROS 2 节点
  ⇅ WebSocket JSON
ros_gateway Brick
  ⇅ 回调 / 发布方法
综合 App main.py
  ⇅ ZdtX57SCan 单电机对象
Linux 原生 CAN 网关 → can0 → 电机
```

## App 配置

```yaml
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
```

`@brick` 将实例加入 App Lab 生命周期。创建实例、注册回调后由 `App.run()` 启动和停止
服务；无需手动调用 `start()`。

## Python API

基础 API：

| API | 语义 |
| --- | --- |
| `on_cmd_vel(callback)` | 注册已校验的底盘速度回调 |
| `on_mode_change(callback)` | 注册模式切换回调 |
| `on_stop(callback)` | 注册断线、心跳超时、运动命令超时和 App 停止回调 |
| `publish_base_state(state)` | 发布底盘状态 |
| `publish_imu(imu)` | 发布 IMU 状态 |
| `publish_diagnostics(data)` | 发布诊断状态 |
| `is_ros_connected()` | 查询 `role=ros2` 的 WebSocket 会话是否已握手 |
| `get_status()` | 获取连接、模式、队列和服务错误快照 |

单电机扩展 API：

| API | 语义 |
| --- | --- |
| `on_motor_enable(callback)` | 注册使能/失能回调 |
| `on_motor_set_speed(callback)` | 注册整数 RPM 与加减速档位回调 |
| `on_motor_stop(callback)` | 注册客户端主动停车回调 |
| `publish_motor_state(state)` | 发布一台电机的地址、速度、使能和通信状态 |

回调只在报文通过版本、序号、时间戳、字段、模式与范围校验后执行。电机命令回调未注册时
返回 `accepted=false`；回调异常会转换为 `command_failed` 错误。

```python
gateway = RosGateway()
gateway.on_motor_enable(handle_motor_enable)
gateway.on_motor_set_speed(handle_motor_set_speed)
gateway.on_motor_stop(handle_motor_stop)
gateway.on_stop(safe_stop)
```

## WebSocket 报文

协议版本为 `1`。第一条消息必须是 `role=ros2` 的 `hello`；其余客户端报文必须携带严格
递增的 `seq` 和 Unix 毫秒 `timestamp_ms`。

| `type` | 方向 | 用途 |
| --- | --- | --- |
| `hello`、`heartbeat` | 双向 | 会话和失联检测 |
| `mode_change`、`cmd_vel` | 客户端 → Brick | 通用底盘命令 |
| `motor_enable` | 客户端 → Brick | 单电机使能或失能 |
| `motor_set_speed` | 客户端 → Brick | 单电机整数 RPM 与加减速档位 |
| `motor_stop` | 客户端 → Brick | 单电机主动停车 |
| `ack`、`error` | Brick → 客户端 | 命令结果或结构化错误 |
| `motor_state` | Brick → 客户端 | 单电机状态 |
| `base_state`、`imu`、`diagnostics` | Brick → 客户端 | 通用状态 |

非零速度和使能只允许在 `ROS_TELEOP` 模式。`motor_set_speed` 默认限制为
`±60 RPM`，`acceleration_level` 为整数 `0～255`。非零运动命令超过 300 ms 未刷新会
调用 `on_stop("motion_command_timeout")`。

示例速度报文：

```json
{"version":1,"type":"motor_set_speed","seq":3,"timestamp_ms":1788025000300,"rpm":20,"acceleration_level":10}
```

状态报文必须包含：

```json
{"motor_id":1,"speed_rpm":20,"enabled":true,"communication_ok":true,"error":""}
```

## 与 ROS 2 的关系

ROS 2 话题、服务、参数和动作都由独立桥接包定义，不是本 Brick 的 Python API。
当前综合示例使用话题传递目标和状态，使用服务执行使能与停车，使用参数配置 WebSocket
地址、电机 ID、转速上限和加减速档位，未定义动作。

`is_ros_connected()` 只检查 WebSocket 握手，不等价于 ROS 2 图发现或节点健康检查。

