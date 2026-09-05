# Generic CAN0 Lab

这是一个独立的 Arduino App Lab 教学 App，用于在 VENTUNO Q 上收发通用 CAN 报文。它不依赖 ZDT Motor App，也不导入 `zdt_motor` Brick。

V1 使用以下链路：

```text
VENTUNO Q CAN 螺钉座
        ↓
FDCAN1 → 系统 CANnectivity → gs_usb
        ↓
Linux SocketCAN can0
        ↓
Generic CAN Brick
```

Brick 只处理 CAN 帧以及用户定义的字节编解码，不包含任何电机、传感器或行业协议。示例中的 ID 和 DATA 都是教学占位值，不可直接当作真实设备协议使用。

## 1. 文件在哪里

```text
generic-can0-lab/
├── app.yaml                         # Arduino App Lab 元数据
├── README.md                        # 本教程
├── bricks/
│   └── generic_can/
│       ├── __init__.py              # 稳定公开API
│       ├── bus.py                   # CanBus、接收线程和有界队列
│       ├── frame.py                 # CanFrame
│       ├── definition.py            # MessageDefinition
│       ├── config.py                # 参数校验
│       ├── errors.py                # 统一异常
│       ├── compat.py                # App Lab/普通Python兼容层
│       ├── brick_config.yaml        # Brick元数据
│       ├── requirements.txt         # 离线依赖安装清单
│       ├── README.md                # Brick API参考
│       ├── backends/
│       │   ├── base.py              # CanBackend最小契约
│       │   └── socketcan.py         # 唯一使用python-can的模块
│       └── vendor/                  # App自己的离线wheel
├── python/
│   ├── can_messages.py              # 用户主要修改此文件
│   └── main.py                      # 默认只监听，不自动发送
├── sketch/
│   ├── sketch.ino                   # 只启动RouterBridge/CANnectivity
│   └── sketch.yaml
├── scripts/                         # 与真实SocketCAN接口交互的脚本
└── tests/                           # 不需要硬件的FakeBackend单元测试
```

普通用户主要阅读并修改：

```text
python/can_messages.py
```

## 2. 使用前提

Brick 不会运行 `sudo`，不会创建 `can0`，不会设置 bitrate，也不会执行 `ip link`。系统必须先存在一个已经配置且处于 UP 状态的 SocketCAN 接口。

以 500 kbit/s Classical CAN 为例，系统管理员可执行：

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000
sudo ip link set can0 up
ip -details -statistics link show can0
```

正常状态应包含 `UP`、`LOWER_UP` 和 `ERROR-ACTIVE`。实际位速率必须以设备手册为准。

`CanBus(interface="can1")`、`CanBus(interface="vcan0")` 等接口名也可以使用；V1 在 VENTUNO Q 上的正式目标和默认值仍是 `can0`。

## 3. 两种使用方式

### 原始 CAN 帧

原始接口适合学习、监视总线和调试未知协议：

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
        print(frame.arbitration_id, frame.data, frame.timestamp)
```

`receive_frame()` 返回完整 `CanFrame`；超时返回 `None`。`timeout_s=0` 表示立即检查，完全不阻塞。

### 命名报文

业务代码不用反复填写 ID 和字节规则：

```python
from can_messages import MESSAGES
from generic_can import CanBus

with CanBus(interface="can0", messages=MESSAGES) as bus:
    bus.send("enable")
    bus.send("set_speed", rpm=120)
    status = bus.receive("status", timeout_s=1.0)
    print(status)
```

命名接收超时会抛出 `CANTimeoutError`，便于业务代码区分“暂时没有原始帧”和“等待指定反馈失败”。

## 4. 只修改 can_messages.py 定义协议

固定 DATA 报文不需要编码函数：

```python
"enable": MessageDefinition(
    arbitration_id=0x201,
    direction="tx",
    fixed_data=b"\x01\x01",
)
```

调用 `bus.send("enable")` 后发送：

```text
ID   = 0x201
DATA = 01 01
```

动态报文用 `encode()` 把工程值变成字节：

```python
def encode_motor_speed(rpm):
    value = int(round(rpm * 10))
    return value.to_bytes(2, byteorder="big", signed=True)
```

发送 120 RPM 的过程为：

```text
bus.send("set_speed", rpm=120)
        ↓
encode_motor_speed(120)
        ↓
120 × 10 = 1200
        ↓
1200 = 0x04B0
        ↓
CanFrame(ID=0x202, DATA=04 B0)
        ↓
SocketCANBackend → python-can → can0
```

接收报文用 `decode()` 把字节还原为工程值。示例 DATA 为 `03 04 AF`：

```text
03      → bit0=1：enabled=True
          bit1=1：fault=True
04 AF   → 有符号大端整数1199
1199÷10 → 119.9 RPM
```

最终得到：

```python
{
    "enabled": True,
    "fault": True,
    "speed_rpm": 119.9,
}
```

这同时展示了三类常见规则：

- 大端：高位字节在前，例如 `04 AF`。
- 有符号数：`signed=True`，负数使用补码；无符号字段使用 `signed=False`。
- 状态位：用 `value & (1 << bit_number)` 读取指定 bit。

## 5. Standard、Extended、Classical CAN 和 CAN FD

标准帧使用 11 位 ID：

```python
CanFrame(0x123, b"\x01", is_extended=False)
```

合法范围是 `0x000`～`0x7FF`。

扩展帧使用 29 位 ID：

```python
CanFrame(0x123456, b"\xA5", is_extended=True)
```

合法范围是 `0x00000000`～`0x1FFFFFFF`。

Classical CAN 默认最多 8 字节。CAN FD 数据结构最多 64 字节：

```python
CanFrame(
    arbitration_id=0x420,
    data=bytes(range(16)),
    is_fd=True,
    bitrate_switch=True,
)
```

`bitrate_switch=True` 只有在 `is_fd=True` 时合法。这里支持的是 CAN FD 报文字段；Brick 不会把 Linux 接口自动切换成 FD 模式。接口和总线未正确配置时，发送会得到 `CANBackendError`。

## 6. direction 规则

`MessageDefinition.direction` 有三种值：

| 值 | 含义 |
| --- | --- |
| `tx` | 只能通过 `send()` 发送 |
| `rx` | 只能通过 `receive()` 接收 |
| `both` | 同一报文定义允许发送和接收 |

V1 采用严格规则：

- `fixed_data` 与 `encode` 不能同时配置。
- `rx` 不允许配置 `fixed_data` 或 `encode`。
- `tx` 不允许配置 `decode`，并且必须有 `fixed_data` 或 `encode`。
- `both` 必须有 `fixed_data` 或 `encode`，可按需配置 `decode`。

接收匹配同时检查 `(arbitration_id, is_extended, is_fd)`，避免相同数字 ID 的不同帧格式被混在一起。

## 7. 接收线程和队列

每个 `CanBus` 只有一个接收线程会调用 backend：

```text
SocketCANBackend
        ↓
唯一 Receiver Thread
        ├── raw queue → receive_frame()
        └── named queues → receive("name")
```

同一帧会进入原始队列，也会进入所有匹配的命名队列，因此两个 API 不会直接争抢 backend。

默认原始队列最多保存 256 帧，每个命名队列最多保存 64 帧。队列满时丢弃最旧帧、保留最新帧，并由以下统计值记录：

```python
report = bus.describe()
print(report["dropped_raw_frames"])
print(report["dropped_message_frames"])
print(report["dropped_message_frames_by_name"])
```

## 8. 错误处理

```python
from generic_can import CANError, CANTimeoutError

try:
    status = bus.receive("status", timeout_s=1.0)
except CANTimeoutError:
    print("没有在1秒内收到status")
except CANError as error:
    print(f"CAN操作失败: {error}")
```

公开异常如下：

| 异常 | 含义 |
| --- | --- |
| `CANConfigurationError` | ID、DATA长度、timeout或定义不合法 |
| `CANBackendError` | SocketCAN、python-can或硬件访问失败 |
| `CANTimeoutError` | 命名报文等待超时 |
| `CANMessageError` | 名称、方向或用户编解码失败 |
| `CANUnsupportedFeatureError` | 调用了V1未支持的能力 |

它们都继承 `CANError`。用户 `encode()` 或 `decode()` 的原始异常会保留在 traceback 中，同时包装为带报文名称的 `CANMessageError`。

## 9. 测试

纯单元测试使用 `FakeBackend`，不需要 VENTUNO Q、`can0` 或 `python-can`：

```bash
cd /home/arduino/ArduinoApps/generic-can0-lab
bash tests/run.sh
```

只读监视真实接口不会发送报文：

```bash
cd /home/arduino/ArduinoApps/generic-can0-lab
bash scripts/run_host_python.sh scripts/can_monitor.py --interface can0
```

发帧脚本要求输入明确确认词，防止复制命令后意外发送：

```bash
bash scripts/run_host_python.sh scripts/send_test_frame.py \
  --interface can0 \
  --id 0x123 \
  --data 01 02 03 \
  --confirm SEND_GENERIC_CAN_FRAME
```

命名报文脚本：

```bash
bash scripts/run_host_python.sh scripts/named_message_test.py \
  --interface can0 \
  send set_speed \
  --values '{"rpm": 120}' \
  --confirm SEND_NAMED_CAN_MESSAGE
```

本机回环脚本默认使用 `vcan0`，它也只使用已有接口，不负责创建：

```bash
bash scripts/run_host_python.sh scripts/loopback_test.py \
  --interface vcan0 \
  --confirm SEND_SOCKETCAN_LOOPBACK_FRAME
```

## 10. V1 边界

V1 正式实现：SocketCAN 数据帧、标准/扩展 ID、Classical CAN、基础 CAN FD/BRS 字段、原始和命名收发、编解码、超时、验证、统一错误、单接收线程和有界队列。

V1 不实现：UART、TTL、RS485、Bridge UART/CAN、CANopen、J1939、Modbus、DBC、ARXML、UDS、ISO-TP、自动扫描、自动配置 bitrate、自动执行 `ip link`、过滤器、订阅回调、周期发送、request-response、各种 Factory。

需要“发送 A 后等待 B”时，在业务层明确写两步：

```python
bus.send("request_status")
status = bus.receive("status", timeout_s=1.0)
```

Generic CAN 层不知道设备地址、功能码、ACK 或事务 ID，因此不提供容易造成错误关联的通用 `request()`。

