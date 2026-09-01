---
title: "websocket_server Brick：可复用的 WebSocket 传输层"
description: "在 Arduino App Lab 中封装与业务协议无关的 WebSocket 服务端，并用回环 App 验证文本、二进制、多客户端和连接限制。"
section: "bricks"
order: 3
status: "verified"
pubDate: "2026-08-31"
updatedDate: "2026-08-31"
verifiedDate: "2026-08-31"
environment:
  - "Arduino VENTUNO Q"
  - "Arduino App CLI 0.12.1"
  - "Python 3.13"
  - "websockets 17.1"
capabilities:
  - "Custom Brick"
  - "WebSocket"
  - "文本与二进制帧"
  - "多客户端"
sourceDir: "websocket-server-brick"
---

`websocket_server` 是一个与业务内容无关的 App Lab Custom Brick。它只负责建立
WebSocket 连接、接收原始消息和向客户端发送原始消息，不解析 JSON，也不知道客户端
是不是 ROS 2 节点。

这样可以把系统拆成两个可复用组件：

```text
websocket_server Brick
  负责端口、路径、连接、文本帧、二进制帧和客户端管理
        ↓ client_id + str/bytes
上层协议 Brick（后续单独实现）
  负责 JSON、版本、消息类型、序号、时间戳和 ROS 2/App 语义
```

本文只实现并验证第一层。

## 实现结果

测试 App 提供以下端点：

```text
ws://<VENTUNO-Q-IP>:8765/ws
```

客户端发来文本帧时，App 返回内容相同的文本帧；发来二进制帧时，App 返回内容相同的
二进制帧。回环是测试 App 的行为，不是 Brick 强制规定的协议。

Brick 本身提供：

- 精确路径检查；
- 文本帧和二进制帧透传；
- 多客户端连接和独立 `client_id`；
- 单播、广播和主动断开；
- 最大消息大小和最大客户端数限制；
- WebSocket 协议层 ping/pong；
- 跟随 App Lab 启停并释放端口。

它不提供 JSON 编解码、应用层握手、业务时间戳、ROS 2 接口、电机控制或安全停车。

## 配套源码

文章左侧“配套源码”可以逐个打开本文使用的完整文件：

```text
app/
├── app.yaml
├── README.md
├── python/
│   └── main.py
├── tests/
│   ├── run.sh
│   └── websocket_test.py
└── bricks/
    └── websocket_server/
        ├── __init__.py
        ├── server.py
        ├── brick_config.yaml
        ├── requirements.txt
        └── README.md
```

其中 `bricks/websocket_server/` 是可复制到其他 App 的组件；`python/main.py`、
`tests/run.sh` 和 `tests/websocket_test.py` 用于证明组件能够正常工作。

## Brick 配置

`brick_config.yaml` 声明 Brick ID、端口和可配置变量：

```yaml
id: websocket_server
name: WebSocket Server
description: A reusable protocol-neutral WebSocket server for Arduino App Lab applications.
category: communication
supported_boards:
  - ventunoq
ports:
  - 8765
variables:
  - name: WEBSOCKET_SERVER_HOST
    default_value: "0.0.0.0"
    hidden: true
  - name: WEBSOCKET_SERVER_PORT
    default_value: "8765"
    hidden: true
  - name: WEBSOCKET_SERVER_PATH
    default_value: "/ws"
  - name: WEBSOCKET_SERVER_MAX_MESSAGE_BYTES
    default_value: "16384"
  - name: WEBSOCKET_SERVER_MAX_CLIENTS
    default_value: "4"
  - name: WEBSOCKET_SERVER_PING_INTERVAL_S
    default_value: "10"
  - name: WEBSOCKET_SERVER_PING_TIMEOUT_S
    default_value: "10"
```

`requirements.txt` 固定已经验证的依赖版本：

```text
websockets==17.1
```

## 在 App 中加载 Brick

将完整 `websocket_server` 文件夹放入 App 的 `bricks/`，然后在 `app.yaml` 中引用：

```yaml
name: WebSocket Brick Loopback
ports: []
bricks:
  - websocket_server:
      variables:
        WEBSOCKET_SERVER_HOST: "0.0.0.0"
        WEBSOCKET_SERVER_PORT: "8765"
        WEBSOCKET_SERVER_PATH: "/ws"
        WEBSOCKET_SERVER_MAX_MESSAGE_BYTES: "16384"
        WEBSOCKET_SERVER_MAX_CLIENTS: "4"
        WEBSOCKET_SERVER_PING_INTERVAL_S: "10"
        WEBSOCKET_SERVER_PING_TIMEOUT_S: "10"
icon: 🔌
```

端口已经由 Brick 声明，所以 App 顶层保持 `ports: []`。目录名、`brick_config.yaml` 中的
`id` 和 `app.yaml` 中的引用名必须都是 `websocket_server`。

## 最小回环 App

下面的 App 注册消息回调，并把 payload 原样发回来源客户端：

```python
import time

from arduino.app_utils import App
from websocket_server import WebSocketServer


server = WebSocketServer()


def handle_message(client_id, payload):
    """
    @description         : 将收到的文本帧或二进制帧原样发回来源客户端
    @param client_id     : Brick 为当前连接分配的客户端标识
    @param payload       : 未解析的 str 或 bytes 消息
    @return              : 无返回值
    """
    server.send(client_id, payload)


def loop():
    """
    @description         : 让出 CPU 并保持 App Lab 主循环运行
    @param               : 无参数
    @return              : 无返回值
    """
    time.sleep(0.05)


server.on_message(handle_message)
App.run(user_loop=loop)
```

`@brick` 会把 `WebSocketServer` 实例纳入 App Lab 生命周期。正常 App 中只需创建对象、
注册回调并调用 `App.run()`，不需要手动调用 `start()` 或 `stop()`。

## Python API

| API | 返回值 | 用途 |
| --- | --- | --- |
| `on_connect(callback)` | 当前实例 | 注册 `callback(client_info)` |
| `on_message(callback)` | 当前实例 | 注册 `callback(client_id, payload)` |
| `on_disconnect(callback)` | 当前实例 | 注册 `callback(client_info, code, reason)` |
| `send(client_id, payload)` | `bool` | 向指定客户端发送消息 |
| `broadcast(payload)` | `int` | 向全部当前客户端发送并返回成功数量 |
| `disconnect(client_id, code, reason)` | `bool` | 主动关闭指定客户端 |
| `get_clients()` | `list[dict]` | 获取不含底层 socket 的客户端快照 |
| `get_status()` | `dict` | 获取监听状态、连接数、限制和服务错误 |

`payload` 只有两种类型：文本帧是 `str`，二进制帧是 `bytes`。Brick 不自动把 bytes
转换为 UTF-8，也不自动调用 `json.loads()`。

`client_info` 包含：

```python
{
    "client_id": "由 Brick 分配的连接标识",
    "remote_address": "远端地址",
    "path": "/ws",
    "connected_monotonic_s": 12345.67,
}
```

`connected_monotonic_s` 用于计算本次系统启动期间的连接时长，不是 Unix 时间戳，不能
写入跨设备通信协议。

连接和消息回调运行在 WebSocket 工作线程中，应快速返回。耗时计算、磁盘操作或硬件任务
应由 App 放入自己的有界队列，再交给专用线程处理。

## WebSocket 约定

| 项目 | 默认值 |
| --- | --- |
| 监听地址 | `0.0.0.0` |
| 端口 | `8765` |
| 路径 | `/ws` |
| 最大消息 | `16384` 字节 |
| 最大同时连接 | `4` |
| 协议 ping 间隔 | `10` 秒 |
| pong 超时 | `10` 秒 |
| 压缩 | 关闭 |

请求路径必须精确匹配 `/ws`，查询参数不参与路径比较。错误路径使用关闭码 `1008`；超过
最大客户端数时，新连接使用关闭码 `1013`。

WebSocket ping/pong 只能判断传输连接是否仍然响应。机器人协议中的控制权、命令超时和
安全停车仍然需要上层协议 Brick 单独实现。

## 创建并启动测试 App

本教程在 VENTUNO Q 上使用一个不包含 MCU Sketch 的 App：

```bash
arduino-app-cli app new websocket-brick-loopback \
  --no-sketch \
  --description "Protocol-neutral reusable WebSocket Brick loopback test"
```

将配套源码中的 `app/` 内容复制到：

```text
/home/arduino/ArduinoApps/websocket-brick-loopback/
```

启动 App：

```bash
cd /home/arduino/ArduinoApps/websocket-brick-loopback
arduino-app-cli app start .
```

查看运行日志：

```bash
arduino-app-cli app logs . --tail 100
```

日志中应出现：

```text
[websocket_server] listening on ws://0.0.0.0:8765/ws
[loopback] listening=True clients=0 error=None
```

## 运行端到端测试

测试入口自动使用当前 App 的虚拟环境，不需要知道 Python 次版本，也不需要设置
`PYTHONPATH`：

```bash
cd /home/arduino/ArduinoApps/websocket-brick-loopback
sh tests/run.sh
```

`run.sh` 根据自己的位置找到 App 根目录和 App CLI 生成的 `.cache/app-compose.yaml`，
再在正在运行的 `main` 容器中调用 App 虚拟环境。它不依赖固定的 Python 次版本、容器
名称或 `site-packages` 路径。因此同一份 App 复制到另一台 VENTUNO Q 后，只要先由
App CLI 成功启动，就可以使用同一个测试命令。测试脚本还会自动读取 Brick 当前配置的
端口、路径和最大客户端数。

需要测试另一台设备的 WebSocket 地址，或者需要覆盖自动检测值时执行：

```bash
sh tests/run.sh \
  --url ws://192.168.1.50:8765/ws \
  --max-clients 4
```

测试范围：

1. 文本消息保持类型和内容原样回环；
2. 二进制消息保持类型和内容原样回环；
3. 两个客户端同时连接且消息互不串线；
4. 错误路径以 `1008` 拒绝；
5. 连接达到配置上限后，下一个连接以 `1013` 拒绝。

实测输出：

```text
PASS text and binary echo
PASS two independent clients
PASS wrong path rejected
PASS maximum client limit
ALL TESTS PASSED
```

App 通过测试后又使用 App CLI 完整重启，并再次得到相同结果，说明 Brick 能随 App
停止、释放端口并重新监听。

## 在其他 App 中复用

复用时只需要复制：

```text
bricks/websocket_server/
```

回环用的 `python/main.py`、`tests/run.sh` 和 `tests/websocket_test.py` 不是 Brick 的
组成部分。新的 App 可以注册自己的回调，或者让后续的协议 Brick 使用 `on_message()`
接收原始 payload，再完成 JSON、ROS 2/App 消息和机器人安全规则的处理。
