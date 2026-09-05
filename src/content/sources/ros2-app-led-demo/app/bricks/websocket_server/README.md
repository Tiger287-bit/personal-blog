# WebSocket Server Custom Brick

`websocket_server` 是一个与业务协议无关的 Arduino App Lab Python Custom Brick。它负责
WebSocket 连接和原始消息传输，不负责理解消息内容。

## 组件边界

```text
任意客户端
  ⇅ WebSocket 文本帧或二进制帧
websocket_server Brick
  ⇅ Python 回调：client_id + 原始 payload
App 或上层协议 Brick
```

本 Brick 负责：

- 监听指定端口和路径；
- 管理多个客户端和稳定的 `client_id`；
- 接收、单播和广播文本帧或二进制帧；
- WebSocket 协议层 ping/pong；
- 消息大小和同时连接数限制；
- App 启停时释放连接和端口。

本 Brick 不负责：

- JSON 编解码和字段校验；
- ROS 2 话题、服务、参数或动作映射；
- 版本、角色、序号、业务时间戳和应用层心跳；
- 电机、CAN、IMU 和安全停车策略。

这些内容应由 App 或独立的上层协议 Brick 实现。

## 在 App 中引用

```yaml
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
```

## Python API

```python
from arduino.app_utils import App
from websocket_server import WebSocketServer


server = WebSocketServer()


def handle_message(client_id, payload):
    server.send(client_id, payload)


server.on_message(handle_message)
App.run(user_loop=lambda: None)
```

| API | 返回值 | 说明 |
| --- | --- | --- |
| `on_connect(callback)` | 当前实例 | 回调签名为 `callback(client_info)` |
| `on_message(callback)` | 当前实例 | 回调签名为 `callback(client_id, payload)`；payload 为 `str` 或 `bytes` |
| `on_disconnect(callback)` | 当前实例 | 回调签名为 `callback(client_info, code, reason)` |
| `send(client_id, payload)` | `bool` | 向指定客户端发送一条原始消息 |
| `broadcast(payload)` | `int` | 向所有当前客户端发送，返回成功数量 |
| `disconnect(client_id, code, reason)` | `bool` | 主动关闭指定客户端 |
| `get_clients()` | `list[dict]` | 获取客户端信息快照，不暴露底层 socket |
| `get_status()` | `dict` | 获取监听地址、连接数和服务错误状态 |

`@brick` 会让 App Lab 在应用启动和停止时分别调用 `start()` 与 `stop()`。连接回调和消息
回调运行在 WebSocket 工作线程中，应快速返回；耗时业务应交给 App 自己的队列或线程。

## 默认端点与限制

默认端点为 `ws://<开发板地址>:8765/ws`，最多 4 个客户端，单条消息最多 16 KiB。
路径必须精确匹配；查询参数不会参与路径比较。压缩默认关闭，当前 Brick 不直接提供 TLS，
需要 `wss://` 时应在受控网络中增加反向代理或单独扩展传输层。

WebSocket ping/pong 是 RFC 6455 连接保活机制，不等同于机器人协议中的应用层心跳。
