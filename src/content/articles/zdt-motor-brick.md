---
title: "zdt_motor Brick：用 Python 控制一台 ZDT 电机"
description: "从一个电机对象开始，学习如何通过 VENTUNO Q 的 can0 读取和控制 ZDT X57S，并可靠扩展到多台电机。"
section: "bricks"
order: 4
status: "verified"
pubDate: "2026-09-01"
updatedDate: "2026-09-01"
verifiedDate: "2026-09-01"
environment:
  - "Arduino VENTUNO Q"
  - "Arduino App CLI 0.12.1"
  - "Python 3.13"
  - "python-can 4.6.1"
  - "ZDT X57S 第二代"
capabilities:
  - "Custom Brick"
  - "单电机对象"
  - "显式 CAN 总线端点"
  - "多电机共用 CAN"
  - "Emm / X 固件"
  - "异步完成事件"
  - "多电机同步启动"
sourceDir: "zdt-motor-brick"
---

`zdt_motor` 是一个用于控制 ZDT 第二代闭环步进电机的 Custom Brick。

它把难懂的 CAN 报文转换成容易理解的 Python 方法。例如，读取转速时只需要调用
`motor.get_speed()`，不需要自己拼接字节或计算校验码。

这个 Brick 的设计重点是：**一个 `ZDTMotor` 对象只表示一台电机**。需要几台电机，就创建几个对象；Brick 本身不用修改。

当前 V1 只正式支持 VENTUNO Q 上已经验证的 Linux SocketCAN `can0`。程序会先创建一个
明确的 `ZDTCanBus`，再创建一个 `SocketCanEndpoint` 描述它连接的 Linux CAN 接口。
电机对象不需要知道 `can0`、SocketCAN、CAN ID 或分包规则，这些都由 CAN 层负责。

## 先认识八个名字

| 名称 | 简单理解 |
| --- | --- |
| Brick | 可以复制到其他 App 中重复使用的一组代码 |
| `ZDTMotor` | 一台具体的 ZDT 电机对象 |
| `ZDTCanBus` | 一条共享的 ZDT CAN 通信总线 |
| `SocketCanEndpoint` | 记录总线使用哪个 Linux CAN 接口 |
| `LogicalCommand` | 尚未转换成 CAN 报文的 ZDT 逻辑命令 |
| `ZDTCanProtocol` | 把逻辑命令转换成 CAN ID 和 CAN 帧 |
| `can0` | Linux 给当前 CAN 接口起的名字 |
| `python-can` | 帮助 Python 通过 `can0` 收发 CAN 报文的库 |

这个 Brick 需要 `python-can 4.6.1`。依赖安装包已经放进 App，启动 App 时会自动安装。因此开发板不需要访问 PyPI，也不需要手动执行 `pip install`。

> PyPI 是 Python 软件包的下载网站。wheel 是已经准备好的安装包。初次使用时不需要操作它们。

## 使用前需要确认

开始前请确认以下信息：

1. 电机已经正确供电。
2. CAN-H、CAN-L 和信号地接线正确。
3. 电机 CAN 波特率是 `500000` bit/s。
4. 代码中的 `motor_id` 与电机实际地址一致。
5. 代码中的 `firmware` 与电机菜单里的 `FWType` 一致。
6. 代码中的 `checksum` 与电机菜单里的 `Checksum` 一致。
7. 代码中的 `microstep` 与电机菜单里的 `MStep` 一致。
8. `step_angle_degrees` 与电机菜单里的 `MotType` 一致，只能填写实际使用的 `0.9` 或 `1.8`。
9. 电机菜单里的 `Response` 使用 `Receive`，或者在需要完成事件时使用 `Both`。

当前项目使用的 X57S 电机地址为 `1、2、3、4`，固件类型为 `FW_Emm`，所以代码中使用 `firmware="emm"`。

### Response 应答方式

`Response` 只影响控制动作命令。当前 Brick 的高层控制方法会先等待即时确认，因此不同设置不能混用：

| 设置 | 当前 Brick 中的行为 |
| --- | --- |
| `Receive` | 适用；控制命令立即返回确认，但不会产生动作完成 `0x9F` |
| `Both` | 推荐用于需要完成通知的场景；先返回确认，动作完成后再产生 `0x9F` |
| `Reached` | 不支持；只返回完成事件，当前 `request()` 可能超时 |
| `None` | 不支持；没有控制命令确认，当前 `request()` 会超时 |
| `Other` | 不推荐；位置命令可能已经执行，但 Python 请求仍然超时 |

Brick 不会自动查询、猜测或修改 `Response`。本项目实机测试使用 `Receive`，所以通过
`get_status()` 轮询到位状态，而不是等待 `next_event()`。

Brick 不会自动读取或猜测电机菜单参数。CAN 通信正常但参数不一致时，实际速度或位置仍可能不正确。Emm 的命令速度缩放和 X 的命令位置角度缩放应保持手册默认设置；如果修改过这些选项，需要先确认新的换算规则。

## 配套源码

文章左侧的“配套源码”可以展开文件夹并打开每个文件。第一次阅读时，建议按下面的结构阅读：

```text
app/
├── app.yaml                         # App Lab 配置
├── python/main.py                   # 最小使用示例
├── sketch/sketch.ino                # 保持 Linux can0 可用的最小 Sketch
├── bricks/zdt_motor/
    ├── README.md                    # Brick 使用说明
    ├── motor.py                     # 普通用户主要调用的电机 API
    ├── messages.py                  # LogicalCommand与ZDTResponse
    ├── bus.py                       # ZDTCanBus及多电机应答分发
    ├── bus_base.py                  # ZDTMotorBus正式公共契约
    ├── endpoints.py                 # can0等SocketCAN接口配置
    ├── commands/                    # 把转速、角度转换成命令参数
    ├── protocols/
    │   ├── can.py                   # CAN ID、分包、重组和应答校验
    │   └── checksum.py              # 0x6B、XOR与CRC8校验
    ├── backends/
    │   ├── base.py                  # CanFrame与CanBackend接口
    │   └── socketcan.py             # 唯一直接使用python-can的文件
    └── vendor/                      # 可离线安装的Python依赖
        ├── python_can-4.6.1-py3-none-any.whl
        ├── packaging-26.3-py3-none-any.whl
        ├── typing_extensions-4.16.0-py3-none-any.whl
        └── wrapt-1.17.3-...-aarch64.whl
└── tests/
    ├── test_architecture.py         # V1架构边界永久测试
    └── test_bus.py                  # 应答、事件、分包和同步启动测试
```

`tests/` 和 `scripts/` 是验证工具，不影响 Brick 的正常使用。`test_architecture.py` 防止
命令层依赖 CAN、Raw API 暴露 CAN 帧或 `python-can` 扩散到其他模块；`test_bus.py`
检查普通应答、异步 `0x9F`、多电机应答分发、错误恢复和同步启动。

左侧目录包含完整 App 文件。Python、C++、YAML 和 Markdown 等文本文件可以直接阅读；
`.whl` 是二进制安装包，点击后会显示“无法在网页中阅读”，但可以下载原文件。GitHub
仓库中保存的也是完整文件，不是占位说明。

## 第一步：在 App 中加载 Brick

把整个 `bricks/zdt_motor/` 文件夹放入 App，然后在 `app.yaml` 中加载它：

```yaml
bricks:
  - zdt_motor
```

不要只复制 `motor.py`。它还需要同目录下的总线、命令和协议模块。

## 第二步：启动 App

开发板上的示例 App 路径是：

```text
/home/arduino/ArduinoApps/zdt-motor-demo
```

启动 App：

```bash
arduino-app-cli app start \
  /home/arduino/ArduinoApps/zdt-motor-demo \
  -v
```

这条命令会准备 App、安装随附的 Python 依赖并启动程序。

查看 App 日志：

```bash
arduino-app-cli app logs \
  /home/arduino/ArduinoApps/zdt-motor-demo \
  --tail 100
```

## 第三步：准备 can0

Brick 只负责收发电机命令，不会使用 `sudo` 修改系统网络接口。需要先在 VENTUNO Q 的 Linux 终端中启用 `can0`：

```bash
cd /home/arduino/ArduinoApps/zdt-motor-demo
sudo scripts/configure_can0.sh can0 500000
```

查看状态：

```bash
ip -details -statistics link show can0
```

看到 `UP` 和 `ERROR-ACTIVE`，表示 CAN 接口已经启动。它只说明接口可用，不代表电机一定已经应答。

## 验证通信

先对一台电机执行不会让电机运动的只读测试：

```bash
cd /home/arduino/ArduinoApps/zdt-motor-demo

scripts/run_host_python.sh scripts/motor_read_test.py \
  --device can0 \
  --id 1 \
  --firmware emm \
  --model X57S \
  --checksum fixed_6b \
  --timeout 0.5
```

看到下面一行表示这台电机的应答和数据解析都通过：

```text
PASS: read-only motor communication and decoding succeeded
```

将 `--id 1` 依次改成 `2`、`3`、`4`，即可检查四台电机。

当前验证环境中，地址 1～4 均正确返回固件版本 `2.0.0` 和硬件类型 `57`。四个对象共用一个 `ZDTCanBus` 连续读取 10 轮，共 40 次请求全部成功；接收线程没有异常，测试后 CAN 的发送错误、接收错误、丢帧和 bus-off 均为 0。

这些结果只验证通信与只读解析，没有让电机运动。

## 架空后的低速运动验证

运动测试前必须架空底盘，保证轮子可以自由转动，清理周围线缆，并准备电源开关或物理急停。
下面的测试会让一台电机以 `10 RPM` 相对转动 `+30°`，随后停止并失能：

```bash
cd /home/arduino/ArduinoApps/zdt-motor-demo

scripts/run_host_python.sh scripts/motor_motion_test.py \
  --device can0 \
  --id 1 \
  --firmware emm \
  --model X57S \
  --checksum fixed_6b \
  --timeout 0.5 \
  --rpm 10 \
  --degrees 30 \
  --acceleration 10 \
  --wait-timeout 5 \
  --unsafe-motion
```

`--unsafe-motion` 是明确的运动确认开关。没有它时脚本会拒绝执行。脚本的固定安全顺序是：

```text
使能 → 相对运动 → 轮询到位 → 停止 → 读取最终状态 → 失能
```

测试其他电机时，只把 `--id 1` 依次改成 `2`、`3`、`4`。当前实机结果如下：

| 电机地址 | 初始位置 | 最终位置 | 位置变化 | 最终速度 | 最终状态 |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 | 0.016° | 30.372° | +30.355° | 0 RPM | 已到位、已失能 |
| 2 | 0.005° | 30.493° | +30.487° | 0 RPM | 已到位、已失能 |
| 3 | -0.071° | 30.547° | +30.619° | 0 RPM | 已到位、已失能 |
| 4 | 0.027° | 30.613° | +30.586° | 0 RPM | 已到位、已失能 |

四台电机均未触发堵转、限位、掉电、过流或过温。测试结束后 `can0` 仍为
`ERROR-ACTIVE`，发送错误、接收错误、丢帧和 bus-off 均为 0。

## 创建一台电机

下面的代码创建地址为 `1` 的 X57S 电机，并读取转速、位置和状态：

```python
from zdt_motor import SocketCanEndpoint, ZDTCanBus, ZDTMotor


can_endpoint = SocketCanEndpoint(
    interface="can0",
    expected_bitrate=500_000,
    physical_port="VENTUNO Q FDCAN1 via CANnectivity",
)

with ZDTCanBus(name="motor_can", endpoint=can_endpoint) as can_bus:
    motor = ZDTMotor(
        bus=can_bus,
        model="X57S",
        motor_id=1,
        firmware="emm",
    )

    print(motor.get_speed())
    print(motor.get_position())
    print(motor.get_status())
```

各参数的含义：

| 参数 | 含义 |
| --- | --- |
| `name="motor_can"` | 这条总线在日志和诊断信息中的名称 |
| `interface="can0"` | 使用 Linux 的 `can0` 接口 |
| `expected_bitrate=500_000` | 记录这条总线预期使用 500 kbit/s |
| `physical_port=...` | 可选的人类可读物理接口说明 |
| `model="X57S"` | 电机型号 |
| `motor_id=1` | 电机的 CAN 地址 |
| `firmware="emm"` | 电机菜单中的固件类型是 `FW_Emm` |

`motor_id` 不是电机数量，而是这一台电机的地址。`expected_bitrate` 是用于显示和检查的
配置记录，不会自动修改 Linux 接口，也不会在 Brick 内执行 `sudo ip link`。

## 创建四台电机

四台电机连接在同一条 CAN 总线上，所以只创建一个 `ZDTCanBus`。然后为每个地址创建一个 `ZDTMotor`：

```python
from zdt_motor import SocketCanEndpoint, ZDTCanBus, ZDTMotor


can_endpoint = SocketCanEndpoint(interface="can0", expected_bitrate=500_000)

with ZDTCanBus(name="motor_can", endpoint=can_endpoint) as can_bus:
    motors = {
        motor_id: ZDTMotor(
            bus=can_bus,
            model="X57S",
            motor_id=motor_id,
            firmware="emm",
        )
        for motor_id in (1, 2, 3, 4)
    }

    for motor_id, motor in motors.items():
        print(motor_id, motor.get_speed())
```

所有对象共用同一个 `can_bus`。`ZDTCanBus` 会根据电机地址，把收到的应答交给正确的 `ZDTMotor` 对象。

如果以后只使用两台电机，只需要把地址改成 `(1, 2)`，不需要修改 Brick。

## 查看总线和接口信息

`ZDTCanBus` 的类名已经说明它是一条 CAN 总线，`endpoint` 则说明它连接到哪个系统接口：

```python
print(can_bus.kind.value)             # can
print(can_bus.endpoint.interface)     # can0
print(can_bus.endpoint.owner.value)   # linux
print(can_bus.describe())
```

默认端点是 `can0 / 500000 bit/s`。代码允许显式填写另一个已经存在的 SocketCAN 接口：

```python
endpoint = SocketCanEndpoint(interface="can1", expected_bitrate=500_000)
```

Brick 不会自动发现或创建 `can1`。VENTUNO Q V1 正式验证的仍然只有系统 CANnectivity
提供的 `can0`；填写其他接口名不代表该硬件路径已经验证。

一个物理 CAN 总线只创建一个 `ZDTCanBus`，连接在这条线上的电机共用它。旧代码中的
`ZDTBus(device="can0")` 仍然可以运行，但新代码推荐使用含义更清楚的类名和端点对象。

## 常用方法

| 想做的事 | 方法 | 说明 |
| --- | --- | --- |
| 读取实时转速 | `get_speed()` | 返回电机驱动器报告的 RPM |
| 读取位置 | `get_position()` | 返回解析后的位置 |
| 读取状态 | `get_status()` | 返回使能、到位和故障等状态 |
| 使能 | `enable()` | 让电机进入可控制状态 |
| 失能 | `disable()` | 取消电机使能 |
| 停止 | `stop()` | 请求电机停止 |
| 安全停止并失能 | `safe_stop_and_disable()` | 先停止，再尝试失能 |
| 设置速度 | `set_speed(...)` | 设置方向、RPM 和加速度 |
| 相对移动 | `move_relative(...)` | 从当前位置移动指定角度 |
| 绝对移动 | `move_absolute(...)` | 移动到指定位置 |
| 读取异步事件 | `can_bus.next_event(...)` | 读取电机主动返回的完成事件 |
| 同步启动 | `can_bus.start_synchronized()` | 同时触发已经缓存的多电机命令 |
| 发送原始逻辑命令 | `motor.raw.request(...)` | 不需要自己处理CAN帧 |
| 查看CAN编码 | `can_bus.encode_frames(...)` | 只编码，不发送 |

控制电机运动前，应先架空车轮、清理机械运动范围，并准备物理急停。

## 原始逻辑命令与 CAN 帧

`motor.raw` 表示“原始 ZDT 逻辑命令”，不是“原始 CAN 帧”。发送手册中尚未封装的
ZDT 功能码时，可以使用：

```python
response = motor.raw.request(
    0x35,
    payload=b"",
    expected_response_length=5,
)
```

`RawMotorAPI` 会构造 `LogicalCommand`，再交给当前 `ZDTMotorBus`。它不会计算 CAN ID，
也不再提供 `motor.raw.frames()`。

只有在调试 CAN 编码时，才需要从 CAN 总线对象查看帧：

```python
from zdt_motor.commands.common import build_raw

command = build_raw(0x36, expected_response_length=7)
frames = can_bus.encode_frames(motor.motor_id, command)
```

`encode_frames()` 只返回编码结果，不会把帧发送到总线。

## 同步启动多台电机

需要尽量同时启动多台电机时，先给每台电机发送带 `synchronized=True` 的缓存命令，最后调用一次总线同步启动：

```python
motors[1].set_speed(20, acceleration=10, synchronized=True)
motors[2].set_speed(20, acceleration=10, synchronized=True)
motors[3].set_speed(20, acceleration=10, synchronized=True)
motors[4].set_speed(20, acceleration=10, synchronized=True)

can_bus.start_synchronized()
```

`start_synchronized()` 发送广播扩展帧：`CAN-ID=0x0000`，数据为 `FF 66 6B`。广播命令不会等待某一台电机单独应答。

## 普通应答与异步完成事件

控制命令首先返回普通接收状态，例如 `0x02`。位置命令真正执行完成后，电机还可能主动返回 `0x9F`。

Brick 会把两者分开处理：普通状态用于完成当前请求，`0x9F` 放入异步事件队列。这样上一条命令的完成通知不会被误认为下一条同功能命令的应答。

第二代 V1.0.5 手册明确列出的 CAN 完成事件是：

| 功能码 | 完成事件 |
| --- | --- |
| `0xF5` | X 固件力矩模式夹爪夹紧完成 |
| `0xFD` | 位置运动到位 |
| `0x9A` | 回零完成 |

只有这些功能码携带单字节 `0x9F` 时才按完成事件处理。读取命令的数据恰好等于
`0x9F` 时仍然属于普通读取响应，例如 `0x3A 0x9F` 不会进入事件队列。

```python
event = can_bus.next_event(timeout_s=0.5)
if event is not None:
    print(event.address, event.function_code, event.data.hex())
```

事件队列默认最多保存 256 条，可以在创建总线时调整：

```python
can_bus = ZDTCanBus(
    endpoint=can_endpoint,
    event_queue_size=256,
)
```

队列满时会丢弃最旧事件并保留最新事件，避免机器人长期运行时无限占用内存。累计丢弃
数量可通过 `can_bus.dropped_event_count` 读取；同一个总线对象重新 `open()` 不会清零该值。

## 为什么要填写 firmware

ZDT 第二代电机可能使用 Emm 或 X 固件。两种固件的部分命令虽然功能相同，但参数顺序和单位不同。

```python
firmware="emm"  # 电机菜单显示 FW_Emm
firmware="x"    # 电机菜单显示 FW_X
```

Brick 不会自动猜测固件类型。填错后可能导致命令失败，也可能使电机按错误参数运行，因此必须以电机菜单中的 `FWType` 为准。

## Brick 内部怎样工作

普通使用只需要接触 `ZDTMotor`。如果想阅读源码，可以按照下面的顺序理解：

```text
你的 Python 代码
    ↓ 调用 get_speed()、set_speed() 等方法
ZDTMotor
    ↓ 调用commands并得到LogicalCommand
commands/common.py、commands/emm.py、commands/x.py
    ↓ LogicalCommand与ZDTResponse定义在messages.py
ZDTMotorBus正式契约
    ↓ 当前V1实现
ZDTCanBus
    ↓ 多电机请求、应答、事件、线程和超时
ZDTCanProtocol
    ↓ CAN ID、校验、分包与重组
CanBackend
    ↓ 经典CanFrame搬运
SocketCANBackend
    ↓
SocketCanEndpoint → Linux can0
```

`ZDTCanBus` 实现 `ZDTMotorBus` 规定的公共接口，包括总线种类、端点、校验方式、
默认超时、打开、关闭、请求和诊断信息。`ZDTMotor` 会明确检查传入对象是否实现
`ZDTMotorBus`，不再同时维护一套手工 `hasattr()` 契约。

V1 不实现 UART、TTL、RS485、Modbus RTU、D0/D1、Bridge UART、Bridge CAN 或
`can1` 自动发现，也不为它们创建空类和 Factory。以后出现真实需求时，新增对应的
Bus、Protocol、Backend 和 Endpoint；`ZDTMotor` 与命令层原则上保持不变。

## VENTUNO Q 上的 CAN 路径

当前开发板通过下面的链路把螺钉式 CAN 接口提供给 Linux：

```text
VENTUNO Q CAN螺钉座
  → FDCAN1
  → 系统CANnectivity
  → gs_usb
  → Linux SocketCAN
  → can0
  → SocketCANBackend
  → ZDTCanBus
  → ZDTMotor
```

这是 V1 唯一正式支持并经过实机验证的路径。因此示例 Sketch 只调用 `Bridge.begin()`，
不会调用 `CAN.begin()`、`CAN.write()`、`CAN.available()` 或 `CAN.read()` 再次操作 FDCAN1。
在当前 ArduinoCore-zephyr / loader 环境中，电机返回帧会进入 CANnectivity 到 Linux
`can0` 的路径，但不会同时进入 Sketch 的 Arduino CAN 轮询队列。

## 为什么不能直接在 App 的 main.py 中看到 can0

当前 App Lab 会把 `python/main.py` 放在容器中运行，而开发板的 `can0` 位于 Linux 宿主系统。容器中默认看不到这个接口。

所以当前示例采用下面的分工：

- App Lab 负责管理 App、最小 Sketch 和 Python 依赖。
- 真正访问 `can0` 的 Python 代码在 VENTUNO Q 的 Linux 宿主系统中运行。
- `scripts/run_host_python.sh` 帮助宿主 Python 找到 App 已经安装好的 Brick 和依赖。

这是当前 App Lab 环境的边界，不是 `ZDTMotor` 对象只能控制一台电机的限制。

## python-can 依赖是怎样准备的

`python-can` 负责让 Python 使用 Linux SocketCAN。为了避免开发板联网下载安装失败，示例 App 已经随附适合当前 VENTUNO Q 环境的离线安装包。

普通用户只需要启动 App，不需要：

- 注册 PyPI 账号；
- 手动下载依赖；
- 手动解压 wheel；
- 单独执行 `pip install python-can`。

只有更换 Python 版本或处理器架构时，维护者才需要重新准备离线安装包。

## 当前范围

当前版本面向 ZDT X57S 第二代电机，正式支持 VENTUNO Q 的 Linux SocketCAN `can0`。
已经封装常用读取、使能、停止、速度、位置、回零和基础配置接口。

手册中只明确标注给其他型号的功能不会向 X57S 发送。TTL、RS485、CANopen 等其他通信方式也不在这个版本中。

配套源码保存了 59 项永久回归测试，覆盖命令、协议、Backend、正式 Bus 契约、
`0xF5/0x9A/0xFD` 完成事件、有界事件队列、溢出计数、多电机分发、错误恢复、同步启动和
`SocketCanEndpoint` 规范化。VENTUNO Q 上的地址 1、2、3、4 四台 X57S 已完成共享总线
只读测试和逐台 `10 RPM / +30°` 运动测试，测试结束后全部停止并失能，CAN 错误计数保持为 0。
