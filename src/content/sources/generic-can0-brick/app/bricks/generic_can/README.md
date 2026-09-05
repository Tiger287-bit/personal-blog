# Generic CAN Brick API

`generic_can` 是协议无关的 CAN 数据帧 Brick。普通业务代码只需导入：

```python
from generic_can import CanBus, CanFrame, MessageDefinition
```

## CanFrame

```python
frame = CanFrame(
    arbitration_id=0x123,
    data=b"\x01\x02",
    is_extended=False,
    is_fd=False,
    bitrate_switch=False,
    timestamp=0.0,
)
```

- `arbitration_id`：标准帧为 `0..0x7FF`，扩展帧为 `0..0x1FFFFFFF`。
- `data`：Classical CAN 为 0～8 字节；CAN FD 只允许 `0～8、12、16、20、24、32、48、64` 字节。
- `bitrate_switch=True` 要求 `is_fd=True`。
- `timestamp`：接收时由 python-can 提供；用户构造发送帧时通常保持 `0.0`。

`CanFrame` 不导入也不依赖 python-can。

CAN FD 的 DATA 长度必须能够直接对应 DLC。如果协议只有 9 个有意义字节，应由用户按照
协议规定显式补齐到 12 字节；Brick 不会替用户选择填充值，也不会依赖 Backend 隐式补齐。

## MessageDefinition

```python
definition = MessageDefinition(
    arbitration_id=0x301,
    direction="rx",
    is_extended=False,
    is_fd=False,
    bitrate_switch=False,
    fixed_data=None,
    encode=None,
    decode=decode_status,
)
```

- `fixed_data`：固定发送字节。
- `encode(**values)`：把业务参数转换成 bytes-compatible DATA。
- `decode(data)`：把接收 DATA 转换为字典、数字或其他工程值。
- 没有 `decode` 时，`receive(name)` 返回完整 `CanFrame`。

## CanBus

```python
bus = CanBus(
    interface="can0",
    messages=MESSAGES,
    raw_queue_size=256,
    message_queue_size=64,
    receiver_poll_s=0.05,
)
```

稳定公开方法：

| 方法 | 返回值 | 行为 |
| --- | --- | --- |
| `open()` | `CanBus` | 打开后端并启动唯一接收线程；可重复调用 |
| `close()` | `None` | 停止线程并释放后端；可重复调用 |
| `send_frame(frame)` | `CanFrame` | 发送一帧原始数据 |
| `receive_frame(timeout_s)` | `CanFrame | None` | 从原始队列取帧，超时返回None |
| `send(name, **values)` | `CanFrame` | 固定或动态编码后发送命名报文 |
| `receive(name, timeout_s)` | 解码结果或`CanFrame` | 从该名称的FIFO队列取下一条待消费报文 |
| `describe()` | `dict` | 返回配置、线程、队列和丢帧统计 |

支持上下文管理器：

```python
with CanBus(interface="can0", messages=MESSAGES) as bus:
    frame = bus.receive_frame(timeout_s=1.0)
```

## Backend边界

普通用户不需要直接使用 backend。测试或扩展底层设备时可以导入：

```python
from generic_can.backends import CanBackend, SocketCANBackend
```

V1 的 `SocketCANBackend` 是唯一导入 python-can 的模块，只打开已有接口：

```python
can.Bus(interface="socketcan", channel=device, fd=True)
```

这里的 `fd=True` 让 socket 能处理 CAN FD 消息字段，不会配置 Linux 链路，也不会执行 `ip link`。所有后端错误统一转为 `CANBackendError`。

手动把 `SocketCANBackend` 传给 `CanBus` 时，`backend.device` 必须等于
`CanBus.interface`；否则构造阶段立即抛出 `CANConfigurationError`。

## App Lab与普通Python

`compat.py` 在 App Lab 中使用真正的 `arduino.app_utils.brick`；普通 Python 没有该模块时，使用不改变类的兼容装饰器。因此同一份核心源码可由 App Lab 使用，也可由 `FakeBackend` 单元测试直接导入。

## 线程模型

一个 `CanBus` 对应一个 backend 和一个接收线程。业务线程不直接调用 `backend.receive()`。接收线程把帧复制到原始队列以及所有匹配的命名队列，队列满时丢最旧帧并记录计数。

`receive(name)` 不是 request-response API。它只读取该命名 FIFO 队列中的下一条待消费帧，
不会自动判断该帧是否由上一条 `send()` 引起。队列里可能存在发送前已经收到的旧帧。
sequence number、transaction ID、counter 或请求/响应功能码等关联规则必须由具体设备协议
层或业务代码实现。

命名匹配键为：

```python
(arbitration_id, is_extended, is_fd)
```

`describe()["messages"][name]["payload_source"]` 对固定报文为 `"fixed_data"`，对动态发送
报文为 `"encode"`，对纯 RX 报文为 `None`。

V1 没有 callback、subscriber、request-response correlation 或协议对象。
