# ZDT Motor Custom Brick

`zdt_motor` is a reusable, single-motor object API for ZDT second-generation
closed-loop stepper motors. V1 implements Classical CAN through Linux
SocketCAN and keeps motor commands independent from the transport.

## VENTUNO Q CAN 使用边界

```text
VENTUNO Q 螺钉式 CAN 接口
  -> FDCAN1
  -> 系统 CANnectivity
  -> gs_usb
  -> Linux SocketCAN
  -> can0
  -> SocketCANBackend
  -> ZDTCanBus
  -> ZDTMotor
```

这是当前 V1 唯一正式支持并经过实机验证的通信路径。VENTUNO Q 系统固件已经通过
CANnectivity 占用 FDCAN1，并把它作为 `gs_usb` 设备提供给 Linux `can0`。

因此，同一个 App 的 Sketch 不得再次调用 `CAN.begin()`、`CAN.write()`、
`CAN.available()` 或 `CAN.read()` 操作 FDCAN1。在当前 ArduinoCore-zephyr / loader
环境中，电机返回帧会进入 CANnectivity 到 Linux `can0` 的路径，但不会同时进入
Sketch 的 Arduino CAN 轮询接收队列。

The Brick never runs `sudo ip link`, changes bitrate, or brings an interface
up. System CAN setup stays outside the library.

## Layers

```text
ZDTMotor / RawMotorAPI
  commands/common.py, commands/emm.py, commands/x.py
  messages.py: LogicalCommand / ZDTResponse
  ZDTCanBus
  protocols/can.py: ZDTCanProtocol
  CanBackend
  SocketCANBackend
```

`ZDTMotor` does not import or call `python-can`. Only
`backends/socketcan.py` knows how SocketCAN is implemented.

## V1 Public API

以下名称属于 CAN V1 稳定公共 API，V1 冻结后不会因为内部重构轻易改名或删除：

```text
ZDTMotor
ZDTCanBus
ZDTBus
ZDTMotorBus
SocketCanEndpoint
BusKind
BusTrace
EndpointOwner

ChecksumType
Firmware
Direction
MotionMode
HomeMode
MotorConfig

ZDTError
ZDTBackendError
ZDTBusBusyError
ZDTCommandError
ZDTConfigurationError
ZDTFormatError
ZDTParameterError
ZDTProtocolError
ZDTTimeoutError
ZDTUnsupportedFeatureError
```

普通用户可以稳定使用 `motor.enable()`、`disable()`、`stop()`、`set_speed()`、
`move_relative()`、`move_absolute()`、`get_speed()`、`get_position()`、`get_status()`、
`home()`，以及 `bus.next_event()` 和 `bus.start_synchronized()`。

以下名称属于高级或内部实现 API：

```text
CanBackend
CanFrame
SocketCANBackend
LogicalCommand
ZDTResponse
ZDTCanProtocol
commands/*
protocols/*
backends/*
```

内部实现可以继续修正缺陷，但不能破坏上面的稳定公共 API。

### 请求超时与轮询等待时间

请求超时用于已经发送命令、正在等待电机应答的场景，必须是有限且大于零的数值：

```text
ZDTCanBus(default_timeout_s=...)
MotorConfig(timeout_s=...)
bus.request(..., timeout_s=...)
```

轮询等待时间允许填写 `0`，表示只检查当前队列并立即返回，不阻塞线程：

```text
SocketCANBackend.receive(timeout_s)
bus.next_event(timeout_s)
```

两类参数都拒绝布尔值、字符串、`NaN` 和正负无穷。请求超时还会拒绝 `0`；轮询等待
时间只拒绝负数。所有这些非法数值统一抛出 `ZDTConfigurationError`。

### response_address 契约

`ZDTMotorBus.request()` 的正式签名是：

```python
request(
    address,
    command,
    *,
    timeout_s=None,
    response_address=None,
)
```

`response_address` 决定当前请求接受哪些电机地址的应答：

| 参数值 | 应答地址规则 |
| --- | --- |
| `None` | 只接受发送地址 `address` 返回的应答 |
| `int` | 只接受这个指定地址返回的应答 |
| `tuple/list/set/frozenset[int]` | 允许集合中的任意地址；第一个有效匹配应答完成请求 |

主要使用场景是 `set_motor_id()`：地址写入后，确认应答可能来自旧地址，也可能来自新地址。
普通电机命令不需要填写 `response_address`。

## Basic use: one motor on can0

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
    print(motor.get_position())
    print(motor.get_speed())
    print(motor.get_status())
```

`ZDTCanBus` clearly says that this object is a CAN bus. Its `endpoint`
records which Linux SocketCAN interface it uses. `expected_bitrate` is
configuration metadata for display and checking; it does not change Linux
network settings or run `sudo ip link`.

One physical CAN line should have one shared `ZDTCanBus` object. One or more
motor objects on that line reuse it:

```python
with ZDTCanBus(endpoint=SocketCanEndpoint(interface="can0")) as can_bus:
    motors = [
        ZDTMotor(bus=can_bus, model="X57S", motor_id=motor_id, firmware="emm")
        for motor_id in (1, 2, 3, 4)
    ]
```

Old code that imports `ZDTBus` or passes `device="can0"` still works. New
code should use `ZDTCanBus` and `SocketCanEndpoint` because their meanings are
clearer.

Useful diagnostic fields:

```python
print(can_bus.kind.value)             # can
print(can_bus.endpoint.interface)     # can0
print(can_bus.endpoint.owner.value)   # linux
print(can_bus.describe())
```

## User API

- Control: `enable()`, `disable()`, `stop()`, `safe_stop_and_disable()`
- Speed: `set_speed(rpm=..., direction=..., acceleration=...)`
- Position: `move_relative(degrees=...)`, `move_absolute(degrees=...)`
- Read: `get_version()`, `get_speed()`, `get_position()`,
  `get_target_position()`, `get_position_error()`, `get_status()`,
  `get_bus_voltage()`, `get_phase_current()`, `get_phase_parameters()`,
  `get_encoder_degrees()`, `get_input_pulses()`
- Homing: `home()`, `abort_home()`, `get_home_status()`
- Configuration: `set_motor_id()`, `set_microstep()`,
  `set_current_limit()`, `set_direction()`
- Capability: `supports(feature)`
- Raw logical command: `motor.raw.request(...)`
- CAN frame inspection: `can_bus.encode_frames(motor_id, command)`

`motor.raw` 只表示 ZDT 原始逻辑命令，不返回 `CanFrame`。需要检查实际 CAN 编码时，
应显式使用 `ZDTCanBus.encode_frames()`；CAN arbitration ID、分包和经典 CAN 帧都属于
CAN 层，而不是电机对象。

## Emm and X firmware

`firmware="emm"` and `firmware="x"` select different encoders for the F6 and
FD commands. Emm speed uses integer RPM plus an acceleration level from 0 to
255. X speed uses 0.1 RPM and acceleration in RPM/s. Emm position converts
degrees to pulses using motor step angle and microstep; X position sends
0.1-degree units with separate acceleration and deceleration.

Never select firmware based on guesswork. It must match the motor's `FWType`.

## X57S capabilities

The V1.0.5 manual confirms X57S in the product table and confirms common
second-generation commands. The following commands are deliberately disabled
because the manual marks them `(X42S/Y42)` rather than X57S:

- temperature and bus-current reads
- multi-motor aggregate command
- periodic-return command
- combined home/motor status and pin-level reads
- position-window, heartbeat, collision-return-angle, and broadcast-ID helpers

Calling a disabled method raises `ZDTUnsupportedFeatureError` before any CAN
frame is sent.

## CAN protocol

- Classical CAN, never CAN FD/BRS
- Extended ID: `(Addr << 8) | Packet`
- Packet numbering starts at zero
- CAN DATA omits the address
- Every continuation packet repeats the function code in byte zero
- Checksum covers the serial-form address, function code, and payload
- Supported checksum modes: fixed `0x6B`, XOR, and the exact manual CRC8 table

The response router checks address, packet sequence, function code, response
length, checksum, and status. `0x02`, `0x12`, `0x22`, `0xE2`, `0xEE`, and
`0x9F` are handled explicitly. Unmatched active returns are placed in the bus
event queue for later async APIs.

## App Lab container boundary

App Lab 0.12.1 runs `python/main.py` in a Docker network namespace. A host
network interface such as `can0` is not automatically visible in that
container. Therefore, use `arduino-app-cli app start` to build the App and its
virtual environment, then run hardware scripts on the VENTUNO Linux host with
`scripts/run_host_python.sh`. The helper reuses the Brick packages while
calling the host `python3`, whose SocketCAN namespace contains `can0`.

## 电机菜单配置前提

Brick 会按照构造 `ZDTMotor` 时提供的软件配置解释速度、角度和位置。使用前必须
确认这些值与电机菜单一致：

- `FW_Emm` 对应 `firmware="emm"`，`FW_X` 对应 `firmware="x"`。
- `checksum` 必须与电机菜单中的 `Checksum` 设置一致。
- `microstep` 必须与电机菜单中的 `MStep` 一致。
- `step_angle_degrees` 必须与电机菜单中的 `MotType` 一致，只能填写实际使用的
  `0.9` 或 `1.8` 度步距角。
- Emm 固件的命令速度缩放选项按手册默认配置解释。如果电机菜单被改成“命令速度值
  缩小 10 倍输入”，必须先恢复默认值或在确认换算规则后再使用 Brick。
- X 固件的命令位置角度缩放选项按手册默认配置解释。如果电机菜单被改成“命令位置
  角度继续缩小 10 倍输入”，必须先恢复默认值或在确认换算规则后再使用 Brick。

`Response` 决定控制动作命令怎样应答，必须与当前请求模型匹配：

- `Receive`：适用于当前 Brick。电机收到控制命令后立即返回确认，`request()` 正常
  返回；此模式不会返回动作完成 `0x9F`，所以 `bus.next_event()` 不一定能收到运动
  完成事件。
- `Both`：需要异步运动完成通知时推荐使用。电机先返回即时确认，动作真正完成后再
  返回 `0x9F`，完成事件进入 `bus.next_event()`。
- `Reached`：当前 V1 高层控制 API 不支持。电机可能只在动作完成后返回 `0x9F`，
  而 `request()` 仍在等待即时确认，最终可能抛出 `ZDTTimeoutError`。
- `None`：当前 V1 高层控制 API 不支持。电机不返回控制命令确认，`request()` 会
  超时。
- `Other`：位置命令可能只返回完成事件而不返回即时确认，与当前
  `move_relative()`/`move_absolute()` 请求模型不兼容，可能出现电机已经动作但
  Python 请求超时。

Brick 不会自动猜测、查询或修改电机的 `Response` 设置。

Brick 当前不会自动读取这些菜单参数，也不会静默猜测被修改过的配置。配置不一致时，
即使 CAN 通信正常，电机的实际速度或位置也可能与代码目标不同。

## V1 范围与未来扩展原则

V1 只正式支持 VENTUNO Q 上已经验证的 Linux SocketCAN `can0`。代码允许显式填写其他
已经存在的 SocketCAN 接口名，但不会自动发现 `can1`，也不代表其他接口已经在 VENTUNO Q
上验证。TTL、RS485、Modbus RTU、D0/D1 UART、Bridge UART、Bridge CAN 和其他 ZDT
通信协议当前都没有实现。

以后出现真实需求时，应为新的通信方式增加对应的 Bus、Protocol、Backend 和 Endpoint，
而不是把串口开关加入 `ZDTCanBus`，也不应重写 `ZDTMotor`、`commands/common.py`、
`commands/emm.py` 或 `commands/x.py`。V1 不为尚未使用的通信方式创建空类、空目录、
Factory、Registry 或 TransportManager。

当前冻结的依赖方向是：

```text
ZDTMotor
  -> LogicalCommand
  -> ZDTCanBus
  -> ZDTCanProtocol
  -> CanBackend
  -> SocketCANBackend
  -> Linux can0
```
