# ⚙️ ZDT Motor Demo V1

This Arduino App Lab App provides a reusable `zdt_motor` Custom Brick for ZDT
second-generation closed-loop stepper motors. V1 targets X57S with either Emm
or X firmware and uses Classical CAN through Linux SocketCAN `can0`.

The default App and all read tests are safe and do not move the motor. Enable,
motion, homing, and raw tests require explicit command-line confirmation.

## Why the Sketch is minimal

On this VENTUNO Q, FDCAN1 is already owned by system CANnectivity and exposed
through `gs_usb` as Linux `can0`:

```text
FDCAN1 -> CANnectivity -> gs_usb -> Linux SocketCAN -> can0
```

App CLI stops the MCU when switching Apps. A minimal Sketch calls
`Bridge.begin()` so the system CANnectivity path is active when this App runs.
Using the Arduino CAN library from that Sketch would compete for the same
FDCAN1 receive path. No file in this project calls Arduino `CAN.begin()`,
`CAN.available()`, `CAN.read()`, or `CAN.write()`.

## Project tree

```text
zdt-motor-demo/
├── app.yaml
├── README.md
├── python/
│   └── main.py
├── sketch/
│   ├── sketch.ino
│   └── sketch.yaml
├── bricks/
│   └── zdt_motor/
│       ├── __init__.py
│       ├── brick_config.yaml
│       ├── requirements.txt
│       ├── vendor/        # offline CPython 3.13/aarch64 wheels
│       ├── README.md
│       ├── motor.py
│       ├── bus.py
│       ├── config.py
│       ├── capabilities.py
│       ├── compat.py
│       ├── errors.py
│       ├── raw.py
│       ├── commands/
│       │   ├── base.py
│       │   ├── common.py
│       │   ├── emm.py
│       │   └── x.py
│       ├── protocols/
│       │   ├── checksum.py
│       │   └── zdt.py
│       └── backends/
│           ├── base.py
│           └── socketcan.py
├── tests/
│   ├── fake_backend.py
│   ├── test_checksum.py
│   ├── test_commands.py
│   ├── test_motor.py
│   └── test_protocol.py
└── scripts/
    ├── _common.py
    ├── check_can0.py
    ├── can_monitor.py
    ├── motor_read_test.py
    ├── motor_enable_test.py
    ├── motor_motion_test.py
    ├── raw_command_test.py
    ├── configure_can0.sh
    └── run_host_python.sh
```

## Build with the actual App CLI

The installed `arduino-app-cli 0.12.1` has no separate `app build` command.
`app start` performs provisioning, dependency installation, and startup:

```bash
cd /home/arduino/ArduinoApps/zdt-motor-demo
arduino-app-cli app start /home/arduino/ArduinoApps/zdt-motor-demo -v
arduino-app-cli app logs /home/arduino/ArduinoApps/zdt-motor-demo --tail 100
```

The Custom Brick uses `python-can==4.6.1`. Its CPython 3.13/aarch64 wheels
are stored under `bricks/zdt_motor/vendor/`, so App Lab can provision the
dependency without Internet access. Refresh those wheels if the App Lab
Python runtime or CPU architecture changes.

## App Lab container and host CAN

The App Lab Python process runs inside a Docker network namespace. Host
`can0` is not automatically present there. `python/main.py` is still a valid
read-only usage example and reports this boundary clearly when the interface
is unavailable.

Real CAN tests must run on the VENTUNO Linux host. The virtual environment's
`python` executable points to a container-only path, so do not execute it on
the host. `scripts/run_host_python.sh` finds its `site-packages` directory and
starts the host `python3` with the correct import path.

## Configure and check can0

The Brick never changes `can0`. Configuration is an explicit administrator
operation:

```bash
cd /home/arduino/ArduinoApps/zdt-motor-demo
sudo scripts/configure_can0.sh can0 500000
scripts/run_host_python.sh scripts/check_can0.py --device can0
```

The VENTUNO `gs_usb` driver rejects `restart-ms`; this helper intentionally
does not set it.

## Run unit tests

Unit tests use `FakeBackend` and do not require a motor or an UP CAN bus:

```bash
cd /home/arduino/ArduinoApps/zdt-motor-demo
PYTHONPATH=bricks python3 -m unittest discover -s tests -v
```

Golden tests reproduce the manual's command bytes, CAN ID, packet split, and
checksum behavior.

## Safe read-only hardware test

Power the motor, make sure its CAN address and firmware match the command, and
run:

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

The script prints every raw TX/RX frame and then decoded version, position,
speed, status, homing state, voltage, phase current, phase parameters, encoder
angle, and input pulse count. It prints `PASS` only if all reads validate.

## Monitor CAN without transmitting

```bash
scripts/run_host_python.sh scripts/can_monitor.py --device can0 --duration 10
```

## Enable and disable test

This changes actuator state but does not command motion. It refuses to run
without `--yes`:

```bash
scripts/run_host_python.sh scripts/motor_enable_test.py \
  --device can0 --id 1 --firmware emm --model X57S --yes
```

## Optional guarded motion test

Lift the wheel, clear the mechanism, and keep a physical emergency stop ready.
The command defaults to 10 RPM and 30 degrees and refuses to run without
`--unsafe-motion`:

```bash
scripts/run_host_python.sh scripts/motor_motion_test.py \
  --device can0 \
  --id 1 \
  --firmware emm \
  --rpm 10 \
  --degrees 30 \
  --acceleration 10 \
  --unsafe-motion
```

The sequence is `enable -> relative move -> stop -> read status -> disable`.
Stop and disable are attempted in `finally`, including when a prior step fails.

## Advanced raw command

Raw mode accepts motor ID, function code, and payload. The Brick still
calculates checksum, Extended CAN ID, and packet boundaries. Because an
arbitrary function can move or reconfigure a motor, `--unsafe-raw` is always
required:

```bash
scripts/run_host_python.sh scripts/raw_command_test.py \
  --device can0 --id 1 --firmware emm \
  --function 0x35 --expected-length 5 --unsafe-raw
```

## Multiple motors on one bus

Do not create one SocketCAN manager per motor. Share one `ZDTBus`:

```python
from zdt_motor import ZDTBus, ZDTMotor

with ZDTBus(device="can0") as bus:
    motors = {
        motor_id: ZDTMotor(
            bus=bus,
            model="X57S",
            motor_id=motor_id,
            firmware="emm",
        )
        for motor_id in (1, 2, 3, 4)
    }
    speeds = {
        motor_id: motor.get_speed()
        for motor_id, motor in motors.items()
    }
```

The Bus has one receive path and routes responses by motor address and function
code. Unmatched active responses are retained in an event queue.

## Emm and X command differences

- Emm F6: direction, integer RPM, acceleration level, sync flag.
- X F6: direction, acceleration in RPM/s, speed in 0.1 RPM, sync flag.
- Emm FD: direction, integer RPM, acceleration level, pulse count, mode, sync.
- X FD: direction, acceleration, deceleration, 0.1 RPM maximum speed,
  0.1-degree position, mode, sync.

The two layouts live in separate command modules and cannot be selected
implicitly.

## Current X57S capability boundary

Enabled for X57S V1: basic control, Emm/X speed and position, version,
position, speed, position error, bus voltage, phase current, phase parameters,
encoder, input pulses, motor status, homing, address, microstep, current limit,
direction, and raw diagnostics.

Not exposed in V1:

- Commands explicitly marked `(X42S/Y42)`, including temperature, bus current,
  multi-motor aggregate command, periodic return, heartbeat, and pin IO read.
- Destructive maintenance commands such as calibration, factory reset, and
  full configuration-block writes.
- Emm/X PID writes, automatic-run storage, and firmware switching.
- Fast-position commands that require confirmed firmware V2.0.0 or newer.
- TTL, Pulse, RS485, RS232, Modbus RTU, DMX512, and CANopen backends.

These are omitted because capability or operating conditions are not fully
confirmed for the current X57S, or because they are outside the safe V1 API.

## Add a future TTL Backend

Add `bricks/zdt_motor/backends/mcu_uart.py` implementing `MotorBackend.open`,
`send`, `receive`, and `close`, then add one Backend selection branch in
`ZDTBus`. Command encoding, checksum logic, response parsing, and `ZDTMotor`
do not need to be rewritten.
