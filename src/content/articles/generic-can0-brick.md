---
title: "generic_can Brick：在 VENTUNO Q 上自定义 CAN 报文"
description: "用协议无关的 CanFrame、MessageDefinition 和 CanBus 封装 Linux SocketCAN，让用户只修改 can_messages.py 就能定义自己的 CAN 报文。"
section: "bricks"
order: 5
status: "in-progress"
pubDate: "2026-09-05"
updatedDate: "2026-09-05"
environment:
  - "Arduino VENTUNO Q"
  - "Arduino App CLI 0.12.1"
  - "Linux SocketCAN can0"
  - "python-can 4.6.1"
capabilities:
  - "Custom Brick"
  - "原始 CAN 收发"
  - "命名报文"
  - "Standard / Extended CAN"
  - "Classical CAN / CAN FD 数据结构"
  - "自定义 encode / decode"
  - "单接收线程"
  - "有界接收队列"
sourceDir: "generic-can0-brick"
---

`generic_can` 是一个与设备协议无关的 Arduino App Lab Custom Brick。它只负责表示、发送、
接收和分发 CAN 数据帧，不知道总线上连接的是电机、传感器还是其他控制器。

用户不需要在业务代码中直接 `import can`，也不需要反复创建 `can.Message`。一般只修改
`python/can_messages.py`，把设备手册中的 CAN ID、DATA 字节和工程值换算规则写进去。

## 这个 Brick 解决什么问题

直接使用 `python-can` 时，业务代码通常会混合四类内容：

- Linux SocketCAN 接口操作；
- 标准帧、扩展帧和 CAN FD 字段；
- CAN ID 与 DATA 字节；
- 转速、温度、位置和状态位等工程含义。

`generic_can` 把它们分成清楚的层次：

```text
用户业务代码
    ↓
CanBus
    ↓
MessageDefinition
    ↓
CanFrame
    ↓
SocketCANBackend
    ↓
python-can
    ↓
Linux can0
```

`python-can` 只会出现在 `backends/socketcan.py`。`CanFrame`、报文定义和业务代码都不依赖
它的内部对象。

## 当前 V1 边界

V1 提供：

- Standard 和 Extended CAN ID；
- Classical CAN 数据帧；
- CAN FD 与 BRS 基础字段；
- 原始帧发送和接收；
- 按名称发送和接收；
- 固定 DATA；
- 用户自定义 `encode()` 和 `decode()`；
- timeout、参数检查和统一异常；
- 一个接收线程与有界队列；
- App Lab 和普通 Python 测试环境兼容层。

V1 不提供 UART、RS485、Bridge CAN、CANopen、J1939、DBC、UDS、ISO-TP、自动扫描、
自动设置位速率、周期发送、回调订阅或通用 `request()`。

Brick 不会执行 `sudo`，不会创建或启用 `can0`，也不会修改 Linux 的 CAN 位速率。

## 配套源码

文章左侧“配套源码”保存了完整 App：

```text
app/
├── app.yaml
├── README.md
├── python/
│   ├── can_messages.py
│   └── main.py
├── sketch/
│   ├── sketch.ino
│   └── sketch.yaml
├── bricks/
│   └── generic_can/
│       ├── __init__.py
│       ├── bus.py
│       ├── frame.py
│       ├── definition.py
│       ├── config.py
│       ├── errors.py
│       ├── compat.py
│       ├── backends/
│       └── vendor/
├── scripts/
└── tests/
```

左侧目录可以展开和收起。Python、C++、YAML、Shell 和 Markdown 文件可以直接阅读；
`.whl` 是二进制离线安装包，网页会显示“无法阅读”，但仍可下载完整原文件。

## 三个核心对象

| 对象 | 作用 |
| --- | --- |
| `CanFrame` | 保存一帧经过校验的 CAN 数据 |
| `MessageDefinition` | 声明报文名称、方向、CAN ID 和编解码方法 |
| `CanBus` | 管理 Backend、发送锁、接收线程和报文队列 |

公开导入方式：

```python
from generic_can import CanBus, CanFrame, MessageDefinition
```

`CanBus` 的稳定方法包括：

| 方法 | 用途 |
| --- | --- |
| `open()` | 打开已有 SocketCAN 接口并启动接收线程 |
| `close()` | 停止接收线程并释放 Backend |
| `send_frame(frame)` | 发送一帧原始 CAN 数据 |
| `receive_frame(timeout_s)` | 读取下一帧原始数据，超时返回 `None` |
| `send(name, **values)` | 编码并发送一条命名报文 |
| `receive(name, timeout_s)` | 从命名FIFO队列读取下一条待消费报文并解码 |
| `describe()` | 查看配置、线程、队列和丢帧统计 |

## CanFrame 参数规则

一帧标准 Classical CAN 数据可以这样表示：

```python
frame = CanFrame(
    arbitration_id=0x123,
    data=b"\x01\x02\x03",
    is_extended=False,
    is_fd=False,
    bitrate_switch=False,
)
```

参数边界如下：

| 帧类型 | ID 范围 | DATA 长度 |
| --- | --- | --- |
| Standard Classical CAN | `0x000`～`0x7FF` | 0～8 字节 |
| Extended Classical CAN | `0x00000000`～`0x1FFFFFFF` | 0～8 字节 |
| CAN FD | 根据 Standard/Extended 选择 | `0～8、12、16、20、24、32、48、64` 字节 |

`bitrate_switch=True` 只允许用于 CAN FD。字符串和整数不能直接作为 DATA，避免整数 `2`
被 Python 意外转换成两个零字节；需要先明确构造 `bytes`。

CAN FD 长度必须能够直接对应 DLC。协议只有 9 个有意义字节时，应按照该协议规定的填充值
和位置显式补齐到 12 字节，不能让 Backend 隐式处理。

## 在 can_messages.py 中定义报文

用户主要编辑下面这个文件：

```text
python/can_messages.py
```

示例 ID 和 DATA 只用于解释写法，连接真实设备前必须按照该设备手册替换。

### 固定 DATA

不包含动态参数的命令可以直接填写 `fixed_data`：

```python
"enable": MessageDefinition(
    arbitration_id=0x201,
    direction="tx",
    fixed_data=b"\x01\x01",
)
```

发送时只写报文名称：

```python
bus.send("enable")
```

最终发送的是：

```text
CAN ID = 0x201
DATA   = 01 01
```

### 把工程值编码成 DATA

动态报文用 `encode()` 把 RPM 等工程值转换成字节：

```python
def encode_motor_speed(rpm):
    value = int(round(rpm * 10.0))
    return value.to_bytes(
        2,
        byteorder="big",
        signed=True,
    )


"set_speed": MessageDefinition(
    arbitration_id=0x202,
    direction="tx",
    encode=encode_motor_speed,
)
```

调用：

```python
bus.send("set_speed", rpm=120)
```

数据转换过程：

```text
120 RPM
  ↓ 乘以10
1200
  ↓ 转换成16位有符号大端整数
0x04B0
  ↓
CAN ID 0x202，DATA 04 B0
```

这里的“乘以 10”和大端顺序只是示例协议规则。真实项目必须以设备手册为准。

### 把 DATA 解码成工程值

接收报文可以定义 `decode()`：

```python
def decode_motor_status(data):
    if len(data) < 3:
        raise ValueError("motor status requires at least 3 bytes")

    flags = data[0]
    speed = int.from_bytes(
        data[1:3],
        byteorder="big",
        signed=True,
    )

    return {
        "enabled": bool(flags & 0x01),
        "fault": bool(flags & 0x02),
        "speed_rpm": speed / 10.0,
    }
```

收到 `03 04 AF` 时：

```text
03      → bit0=1，enabled=True
          bit1=1，fault=True
04 AF   → 大端整数1199
1199÷10 → 119.9 RPM
```

返回结果：

```python
{
    "enabled": True,
    "fault": True,
    "speed_rpm": 119.9,
}
```

如果接收定义没有 `decode`，`bus.receive()` 会返回完整 `CanFrame`，不会丢失 CAN ID、
时间戳和帧类型。

## direction 的规则

| 值 | 含义 |
| --- | --- |
| `tx` | 只能发送 |
| `rx` | 只能接收 |
| `both` | 可以发送，也可以接收 |

V1 使用严格配置：

- `fixed_data` 和 `encode` 不能同时存在；
- `rx` 不能配置 `fixed_data` 或 `encode`；
- `tx` 不能配置 `decode`，并且必须提供一种 DATA 来源；
- `both` 必须提供一种发送 DATA 来源，可以同时配置 `decode`。

错误方向会在访问真实 CAN 接口之前被拒绝。

## 原始 CAN 收发

原始接口适合 CAN Monitor、教学和未知协议调试：

```python
from generic_can import CanBus, CanFrame


with CanBus(interface="can0") as bus:
    bus.send_frame(
        CanFrame(
            arbitration_id=0x123,
            data=b"\x01\x02\x03",
        )
    )

    frame = bus.receive_frame(timeout_s=0.5)
    if frame is not None:
        print(frame.arbitration_id)
        print(frame.data)
        print(frame.timestamp)
```

`timeout_s=0` 表示立即检查且不阻塞。负数、布尔值、`NaN` 和正负无穷会抛出
`CANConfigurationError`。

## 命名报文收发

```python
from can_messages import MESSAGES
from generic_can import CanBus


with CanBus(interface="can0", messages=MESSAGES) as bus:
    bus.send("enable")
    bus.send("set_speed", rpm=120)
    status = bus.receive("status", timeout_s=1.0)
    print(status)
```

Generic CAN 没有统一的设备地址、功能码、ACK 或事务 ID，因此不实现通用 `request()`。
如果业务代码需要“发送一帧，然后读取某个命名队列中的下一帧”，可以写成两步：

```python
bus.send("request_status")
status = bus.receive("status", timeout_s=1.0)
```

这两行不是 request-response 关联。`receive("status")` 只从 `status` 的 FIFO 队列中取出
下一条尚未消费的帧；如果旧 `status` 在发送前已经进入队列，它就可能先被返回。设备协议
提供 sequence number、transaction ID、counter 或请求/响应功能码时，应由协议层或业务
代码根据这些字段完成关联。

## Standard、Extended 与 CAN FD

标准帧：

```python
CanFrame(
    arbitration_id=0x123,
    data=b"\x01",
    is_extended=False,
)
```

扩展帧：

```python
CanFrame(
    arbitration_id=0x123456,
    data=b"\xA5",
    is_extended=True,
)
```

CAN FD 与 BRS：

```python
CanFrame(
    arbitration_id=0x420,
    data=bytes(range(16)),
    is_fd=True,
    bitrate_switch=True,
)
```

Brick 支持 CAN FD 的数据结构和 `python-can` 字段映射，但不会自动把 Linux `can0`
配置成 FD 模式。当前也没有真实 CAN FD 实测结果。

## 为什么只能有一个接收线程

如果 `receive_frame()` 和多个 `receive(name)` 分别直接读取 Backend，它们会争抢同一帧。
本 Brick 由一个接收线程统一读取：

```text
SocketCANBackend
        ↓
唯一 Receiver Thread
        ├── Raw Queue → receive_frame()
        └── Named Queues → receive("name")
```

同一帧会进入原始队列，也会进入全部匹配的命名队列。命名匹配同时检查：

```python
(arbitration_id, is_extended, is_fd)
```

原始队列默认保存 256 帧，每个命名队列默认保存 64 帧。队列满时丢弃最旧帧并保留最新
帧，诊断信息可以通过 `describe()` 查看：

```python
report = bus.describe()
print(report["dropped_raw_frames"])
print(report["dropped_message_frames"])
print(report["dropped_message_frames_by_name"])
```

## 统一错误处理

```python
from generic_can import CANError, CANTimeoutError


try:
    status = bus.receive("status", timeout_s=1.0)
except CANTimeoutError:
    print("没有在1秒内收到status")
except CANError as error:
    print(f"CAN操作失败: {error}")
```

| 异常 | 含义 |
| --- | --- |
| `CANConfigurationError` | CAN ID、DATA、timeout或定义不合法 |
| `CANBackendError` | SocketCAN、python-can或系统接口失败 |
| `CANTimeoutError` | 等待命名报文超时 |
| `CANMessageError` | 名称、方向或用户编解码失败 |
| `CANUnsupportedFeatureError` | 请求了V1未实现的能力 |

用户 `encode()` 和 `decode()` 抛出的原始异常会保留在 traceback 中，同时包装成包含报文
名称的 `CANMessageError`。

## App Lab 与宿主 Linux 的边界

当前 VENTUNO Q 的 `can0` 位于 Linux 宿主系统。App Lab 的 `python/main.py` 在容器中运行，
容器默认不一定能看到宿主 `can0`。

因此这个示例采用以下分工：

- App Lab 管理最小 Sketch、Brick 和 Python 离线依赖；
- `sketch/sketch.ino` 只调用 `Bridge.begin()`，不再通过 Arduino CAN 库争用 FDCAN1；
- 真实 SocketCAN 脚本在 VENTUNO Q Linux 宿主中运行；
- `scripts/run_host_python.sh` 自动复用当前 App 已安装的依赖。

离线 wheel 已完整保存在 `bricks/generic_can/vendor/`。开发板不需要访问 PyPI，也不依赖
另一个 App 的虚拟环境。

## V1 可靠性契约

这个版本对以下行为作出明确保证：

| 场景 | V1 行为 |
| --- | --- |
| 发送过程中调用 `close()` | 等待当前发送结束，再关闭 SocketCAN Backend |
| `CanBus(interface="can0")` 配合显式 SocketCAN Backend | Backend 的 `device` 必须同样是 `can0`，否则创建对象时立即报错 |
| CAN FD DATA 长度 | 只接受能够直接对应 DLC 的长度，不依赖 Backend 隐式补齐 |
| 接收错误帧或远程帧 | 忽略这些帧，但不会因此延长调用者指定的 timeout |
| 纯接收报文的 `describe()` 结果 | `payload_source` 为 `None`，不会错误显示为 `encode` |
| 原始队列或命名队列已满 | 丢弃最旧帧，保留最新帧，并累计丢帧统计 |

V1 的公开 API 固定为：

```python
from generic_can import (
    CANBackendError,
    CANConfigurationError,
    CANError,
    CANMessageError,
    CANTimeoutError,
    CANUnsupportedFeatureError,
    CanBus,
    CanFrame,
    MessageDefinition,
)
```

`SocketCANBackend`、`CanBackend` 和内部辅助函数不是稳定公共 API。具体设备协议如果需要
请求与响应关联，应在 `generic_can` 之上另建协议 Brick，不要依赖内部实现。

## 运行不依赖硬件的测试

`FakeBackend` 单元测试不会打开 `can0`，也不会发送真实 CAN 报文：

```bash
cd /home/arduino/ArduinoApps/generic-can0-lab
bash tests/run.sh
```

当前仓库的实际测试结果：

```text
Ran 49 tests

OK
```

这些测试覆盖 ID 和 DATA 边界、严格 CAN FD DLC 长度、报文定义、编解码、timeout、
关闭与发送同步、接口一致性、并发打开、并发发送、单接收线程、Raw/Named 队列、队列
溢出、诊断字段、Public API 契约、错误传播和 SocketCAN 字段映射。

最终源码也在开发板执行了：

```bash
PYTHONPYCACHEPREFIX=/tmp/generic-can0-lab-compileall-final \
python3 -B -m compileall -q -f bricks python scripts tests
```

结果为：

```text
COMPILEALL_PASS
```

## 准备真实 can0

下面是 500 kbit/s Classical CAN 的系统配置示例。实际位速率必须以设备手册为准：

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000
sudo ip link set can0 up
ip -details -statistics link show can0
```

只读 CAN Monitor 不会主动发送报文：

```bash
cd /home/arduino/ArduinoApps/generic-can0-lab
bash scripts/run_host_python.sh scripts/can_monitor.py --interface can0
```

`send_test_frame.py` 和 `named_message_test.py` 都要求明确的确认词，避免复制命令后误发。
真实发帧前必须把示例 ID 和 DATA 替换成设备手册中的合法报文。

## 当前验证结论

当前版本已经通过 49 项 FakeBackend 单元测试和 Python `compileall`，Arduino App CLI 能够
识别 `user:generic-can0-lab`。测试时 App 尚未启动，开发板 `can0` 为 `DOWN/STOPPED`，
因此本文不把真实 CAN、真实设备通信或 CAN FD 标记为已验证。
