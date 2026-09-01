# WebSocket Brick Loopback

这个 App 只验证 `websocket_server` Custom Brick 的传输能力，不定义任何 ROS 2、JSON、
电机或机器人业务协议。

## 目录

```text
websocket-brick-loopback/
├── app.yaml
├── README.md
├── bricks/
│   └── websocket_server/
│       ├── __init__.py
│       ├── server.py
│       ├── brick_config.yaml
│       ├── requirements.txt
│       └── README.md
├── python/
│   └── main.py
└── tests/
    ├── run.sh
    └── websocket_test.py
```

## 功能边界

- Brick 监听 `ws://<开发板地址>:8765/ws`。
- App 收到文本帧或二进制帧后，按原类型、原内容发回同一个客户端。
- Brick 不解析消息内容，也不添加版本、序号、时间戳、角色或心跳字段。
- ROS 2 与 App 的业务协议将在另一个 Brick 中实现。

## 启动

```bash
cd /home/arduino/ArduinoApps/websocket-brick-loopback
arduino-app-cli app start .
```

查看日志：

```bash
arduino-app-cli app logs . --tail 100
```

## 自动回环测试

App 启动后，在开发板上执行：

```bash
cd /home/arduino/ArduinoApps/websocket-brick-loopback
sh tests/run.sh
```

`run.sh` 会读取当前 App 由 App CLI 生成的 `.cache/app-compose.yaml`，然后在正在运行的
`main` 容器中调用 App 虚拟环境。它不依赖固定的 Python 次版本、容器名称或
`site-packages` 路径，也不需要手动设置 `PYTHONPATH`。测试脚本会自动读取 Brick 当前
配置的端口、路径和最大客户端数。

脚本依次验证文本帧、二进制帧、两个客户端同时通信、错误路径拒绝和最大客户端数限制。
全部通过时输出 `ALL TESTS PASSED`。

测试其他地址或需要覆盖自动检测值时可以传入参数：

```bash
sh tests/run.sh --url ws://192.168.1.50:8765/ws --max-clients 4
```
