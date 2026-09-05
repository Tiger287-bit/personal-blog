# BNO086 IMU read-only Brick

`bno086_imu` is a small Python wrapper for the Ventuno Q MCU's read-only
RouterBridge methods:

- `imu_get_sample` — one complete accelerometer, de-gravity linear-acceleration,
  calibrated-gyroscope and Game Rotation Vector snapshot;
- `imu_get_status` — initialization, report-rate, reset, sequence and error
  diagnostics.

It has no WebSocket server, ROS dependency, network port, write RPC, motor or
automatic background task. The App owns its polling schedule:

```python
from bno086_imu import Bno086Imu

imu = Bno086Imu(timeout_s=3.0)  # construction performs no RPC
sample = imu.get_sample()
if imu.is_valid(sample):
    print(sample["orientation"]["quaternion"])
```

`get_sample()` validates the JSON/object shape, finite numbers and numeric
types, but deliberately returns a well-formed `valid=false`, `stale=true` or
low-quality report so that students can inspect diagnostics. `is_valid()` is a
pure quality predicate: all four reports must be `valid=true`, `stale=false`,
have accuracy/quality 1–3, use the current SI units (`m/s^2` and `rad/s`), and
contain finite vectors plus a near-unit quaternion. `ProtocolError` means the
response is malformed; `RpcError` means RouterBridge itself failed. No prior
sample is returned after an error. Raw, filtered, per-stream `sample_seq`/`seq`,
raw SH2 `sensor_seq`, count, per-stream `sequence_gap_count`, aggregate
`source_sequence_gap_count` and `sensor_time_us` fields are retained as
received; the aggregate is diagnostic only and is not a cross-stream
continuity counter. This Brick does not add a timestamp or apply a filter.
`accelerometer.raw` retains gravity, while
`linear_acceleration.raw` is the de-gravity `m/s^2` input for motion processing.

## MCU prerequisite

This Python Brick is only the host-side wrapper. The target App must also
carry the companion MCU library and a sketch that registers
`imu_get_sample`/`imu_get_status` with `Bridge.provide_safe`. The current
project source is `Adafruit_BNO08x_Ventuno` (version 1.2.5, with its BSD
license and Hillcrest notice) plus the two Adafruit dependencies declared by
the sketch profile.

Copying this Python directory does **not** add the Arduino library or sketch,
and it does not flash the MCU. Add the companion files under the App's
`sketch/` tree and review the App Lab run/compile/flash action before running
the App. The wrapper assumes the MCU already owns I2C sampling and exposes
the two read-only RPCs; it does not claim to detect pins, configure report
rates or perform safety control.
