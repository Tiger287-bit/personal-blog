# ZDT Motor Custom Brick

`zdt_motor` is a reusable, single-motor object API for ZDT second-generation
closed-loop stepper motors. V1 implements Classical CAN through Linux
SocketCAN and keeps motor commands independent from the transport.

## VENTUNO Q CAN path

```text
Python ZDTMotor
  -> Command Layer
  -> ZDT Protocol Layer
  -> SocketCANBackend (python-can)
  -> Linux can0
  -> gs_usb / CANnectivity
  -> FDCAN1
  -> ZDT motor
```

The Sketch must not call `CAN.begin()`, `CAN.write()`, `CAN.available()`, or
`CAN.read()`. On the current VENTUNO Q firmware, CANnectivity owns FDCAN1 and
exposes it to Linux as `can0`.

The Brick never runs `sudo ip link`, changes bitrate, or brings an interface
up. System CAN setup stays outside the library.

## Layers

```text
ZDTMotor / RawMotorAPI
  commands/common.py, commands/emm.py, commands/x.py
  protocols/zdt.py, protocols/checksum.py
  MotorBackend
  SocketCANBackend
```

`ZDTMotor` does not import or call `python-can`. Only
`backends/socketcan.py` knows how SocketCAN is implemented.

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
- Advanced diagnostics: `motor.raw.frames(...)`, `motor.raw.request(...)`

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

Brick 当前不会自动读取这些菜单参数，也不会静默猜测被修改过的配置。配置不一致时，
即使 CAN 通信正常，电机的实际速度或位置也可能与代码目标不同。

## V1 limits and future buses

V1 implements Linux SocketCAN. It defaults to `can0`, but another existing
SocketCAN interface can be selected with
`SocketCanEndpoint(interface="can1")`. TTL, Pulse, RS485, RS232, Modbus,
DMX512, and CANopen are not implemented.

`ZDTCanBus` implements the common `ZDTMotorBus` contract. A future serial
version should add a separate `ZDTSerialBus` and serial endpoint instead of
adding serial switches to `ZDTCanBus`. `ZDTMotor`, commands, and result
objects can then stay unchanged. On VENTUNO Q, MCU pins D0/D1 are not Linux
device names: direct D0/D1 support should use an MCU/RouterBridge serial
endpoint, while a Linux USB serial adapter should use a Linux serial-device
endpoint.
