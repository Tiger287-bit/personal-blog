"""BNO086 snapshot adapter: App Lab RPC -> WebSocket -> ros_ws_bridge.

The MCU owns sampling and the BNO086 driver.  This file only reads the
read-only ``imu_get_sample`` RPC, validates one complete snapshot, and sends
standard ROS message envelopes to the WebSocket Brick.
"""

import json
import math
import threading
import time

try:  # App Lab supplies these modules; the fallback keeps host tests importable.
    from arduino.app_utils import App, Bridge
except ImportError:  # pragma: no cover - exercised only outside App Lab
    App = None
    Bridge = None

try:
    from websocket_server import WebSocketServer
except ImportError:  # pragma: no cover - exercised only outside App Lab
    WebSocketServer = None

try:
    from bno086_imu import Bno086Imu
except ImportError:  # pragma: no cover - exercised only outside App Lab
    Bno086Imu = None


IMU_TOPIC = "/imu/data"
STATUS_TOPIC = "/imu/status"
IMU_TYPE = "sensor_msgs/msg/Imu"
STATUS_TYPE = "std_msgs/msg/String"
FRAME_ID = "imu_link"
SAMPLE_PERIOD_S = 0.019  # 52.6 Hz target leaves margin for a 50 Hz ROS stream.
RPC_TIMEOUT_S = 0.05
STATUS_PERIOD_S = 1.0
SNAPSHOT_RATE_HZ = 1.0 / SAMPLE_PERIOD_S
# The MCU marks a report stale after 200 ms.  This slightly larger host-side
# limit catches a stalled marker stream even if a stale flag is delayed, while
# allowing normal scheduling jitter in the 50 Hz RPC loop.
MARKER_NO_PROGRESS_TIMEOUT_S = 0.25
MARKER_NO_PROGRESS_TIMEOUT_NS = int(MARKER_NO_PROGRESS_TIMEOUT_S * 1_000_000_000)
# A 100 Hz marker should normally advance by about 10 ms (or 20 ms between
# 50 Hz RPC snapshots).  A 250 ms jump is an explicit sensor-time interruption
# threshold, not a raw SH-2 sequence-gap gate.
MARKER_SENSOR_TIME_MAX_GAP_US = 250_000
# The vendored ``sh2_SensorValue_t.timestamp`` is uint64_t and the MCU JSON
# writer preserves it in a uint64_t field.  Keep this width explicit so a
# future protocol proven to expose uint32 timestamps can opt into the
# wrap-safe extension without treating a relative counter as Unix time.
SENSOR_TIME_BITS = 64
STREAMS = (
    "accelerometer",
    "linear_acceleration",
    "gyroscope",
    "orientation",
)
UPDATE_MARKER_STREAMS = ("linear_acceleration", "orientation")
REPORT_FIELDS = (
    "valid",
    "stale",
    "accuracy",
    "quality",
    "finite",
    "seq",
    "sample_seq",
    "sensor_seq",
    "sensor_time_us",
    "count",
    "sequence_gap_count",
    "unit",
)


class SampleRejected(ValueError):
    """A snapshot must not be published when this validation fails."""


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _nonnegative_integer(value):
    return _integer(value) and value >= 0


def _finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SampleRejected(f"{label} is not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise SampleRejected(f"{label} is not finite")
    return number


def _ready_report(name, report):
    if not isinstance(report, dict):
        raise SampleRejected(f"{name} report is missing")
    if report.get("valid") is not True:
        raise SampleRejected(f"{name} valid=false")
    if report.get("stale") is not False:
        raise SampleRejected(f"{name} stale=true")
    quality = report.get("accuracy", report.get("quality"))
    if not _integer(quality) or not 1 <= quality <= 3:
        raise SampleRejected(f"{name} quality is outside 1..3")


def _vector(report, name, field):
    values = report.get(field)
    if not isinstance(values, dict):
        raise SampleRejected(f"{name}.{field} is missing")
    return {
        axis: _finite_number(values.get(axis), f"{name}.{field}.{axis}")
        for axis in ("x", "y", "z")
    }


def _quaternion(report):
    values = report.get("quaternion")
    if not isinstance(values, dict):
        raise SampleRejected("orientation.quaternion is missing")
    result = {
        axis: _finite_number(values.get(axis), f"orientation.quaternion.{axis}")
        for axis in ("x", "y", "z", "w")
    }
    norm = math.sqrt(sum(value * value for value in result.values()))
    if not math.isfinite(norm) or abs(norm - 1.0) > 0.05:
        raise SampleRejected("orientation quaternion norm is invalid")
    return result


def _sample_data(sample, receive_time_ns):
    """Validate a complete sample and build ``sensor_msgs/msg/Imu.data``.

    The BNO086 sketch already supplies SI units and a normalized quaternion.
    We deliberately read ``raw`` (not the display-only ``filtered`` values).
    ``receive_time_ns`` is the mapped ROS stamp.  The caller derives it from
    the relative sensor clock and uses Linux wall time only for the first
    epoch anchor; it is not based on RPC arrival intervals.
    """
    if not isinstance(sample, dict):
        raise SampleRejected("RPC result is not an object")
    if not _nonnegative_integer(sample.get("reset_count")):
        raise SampleRejected("reset_count is missing or invalid")

    accelerometer = sample.get("accelerometer")
    linear_acceleration = sample.get("linear_acceleration")
    gyroscope = sample.get("gyroscope")
    orientation = sample.get("orientation")
    for name, report in (
        ("accelerometer", accelerometer),
        ("linear_acceleration", linear_acceleration),
        ("gyroscope", gyroscope),
        ("orientation", orientation),
    ):
        _ready_report(name, report)

    # Keep validating the legacy accelerometer for compatibility, but never
    # use it as motion input because it contains gravity.
    if accelerometer.get("unit") != "m/s^2":
        raise SampleRejected("accelerometer unit is not m/s^2")
    if linear_acceleration.get("unit") != "m/s^2":
        raise SampleRejected("linear_acceleration unit is not m/s^2")
    if gyroscope.get("unit") != "rad/s":
        raise SampleRejected("gyroscope unit is not rad/s")
    if orientation.get("mode") != "game_rotation_vector":
        raise SampleRejected("orientation mode is not game_rotation_vector")
    _vector(accelerometer, "accelerometer", "raw")
    linear_accel = _vector(
        linear_acceleration,
        "linear_acceleration",
        "raw",
    )
    gyro = _vector(gyroscope, "gyroscope", "raw")
    quaternion = _quaternion(orientation)
    seconds, nanoseconds = divmod(int(receive_time_ns), 1_000_000_000)

    return {
        "header": {
            "stamp": {"sec": seconds, "nanosec": nanoseconds},
            "frame_id": FRAME_ID,
        },
        "orientation": quaternion,
        "orientation_covariance": [0.0] * 9,  # unknown, not measured
        "angular_velocity": gyro,
        "angular_velocity_covariance": [0.0] * 9,  # unknown, not measured
        "linear_acceleration": linear_accel,
        "linear_acceleration_covariance": [0.0] * 9,  # unknown, not measured
    }


class SensorClockMapper:
    """Map the linear-acceleration sensor clock into ROS Unix nanoseconds.

    BNO086/SH-2 timestamps are relative microseconds, not Unix time.  The
    first accepted linear-acceleration sample establishes an anchor using the
    Linux wall clock captured after the RPC returns.  Later stamps use only
    the extended sensor delta, so WebSocket batching cannot create dt=0 or a
    large arrival-time dt in downstream odometry.

    The current vendored ``sh2_SensorValue_t.timestamp`` is uint64_t.  The
    ``sensor_time_bits`` argument remains explicit because some older sensor
    protocols expose a uint32 counter; when set to 32, one decreasing raw
    value is accepted as a wrap only when the backwards distance exceeds the
    half-range.  A normal 64-bit decrease is rejected as a rollback.
    """

    def __init__(self, max_gap_us=MARKER_SENSOR_TIME_MAX_GAP_US,
                 sensor_time_bits=SENSOR_TIME_BITS):
        if sensor_time_bits not in (32, 64):
            raise ValueError("sensor_time_bits must be 32 or 64")
        self.max_gap_us = int(max_gap_us)
        self.sensor_time_bits = int(sensor_time_bits)
        self.modulus = 1 << self.sensor_time_bits
        self.half_range = self.modulus // 2
        self.reset_count = None
        self.epoch = 0
        self.raw_previous = None
        self.extended_previous = None
        self.anchor_sensor_us = None
        self.anchor_ros_ns = None
        self.last_mapped_ns = None
        self.mapping_state = "unanchored"

    @staticmethod
    def _integer(value, label):
        if not _nonnegative_integer(value):
            raise SampleRejected(f"{label} is missing or invalid")
        return int(value)

    def _start_epoch(self, raw_sensor_us, reset_count, receive_time_ns,
                     reason):
        self.epoch += 1
        self.reset_count = reset_count
        self.raw_previous = raw_sensor_us
        self.extended_previous = raw_sensor_us
        self.anchor_sensor_us = raw_sensor_us
        self.anchor_ros_ns = receive_time_ns
        self.last_mapped_ns = receive_time_ns
        self.mapping_state = reason
        return receive_time_ns

    def observe(self, raw_sensor_us, reset_count, receive_time_ns):
        """Return a mapped ROS stamp for one new linear sample."""
        raw_sensor_us = self._integer(raw_sensor_us, "sensor_time_us")
        reset_count = self._integer(reset_count, "reset_count")
        receive_time_ns = self._integer(receive_time_ns, "receive_time_ns")
        if raw_sensor_us >= self.modulus:
            raise SampleRejected("sensor_time_us exceeds configured counter width")

        if self.reset_count is None:
            return self._start_epoch(
                raw_sensor_us, reset_count, receive_time_ns, "anchored")

        # A reset starts a fresh relative clock epoch.  Do not subtract the
        # old sensor counter from the new one, even if the raw values repeat.
        # The ROS odometry node observes the reset in /imu/status and enters
        # FAULT until the learner recalibrates.
        if reset_count != self.reset_count:
            return self._start_epoch(
                raw_sensor_us, reset_count, receive_time_ns,
                "reanchored_reset")

        if raw_sensor_us < self.raw_previous:
            backwards = self.raw_previous - raw_sensor_us
            if self.sensor_time_bits != 32 or backwards <= self.half_range:
                raise SampleRejected("sensor_time_us moved backwards")
            # Only the explicitly configured uint32 protocol uses wrap.  The
            # modulo extension keeps the mapped time monotonically increasing.
            extended = raw_sensor_us + (self.epoch + 1) * self.modulus
            self.epoch += 1
            self.mapping_state = "wrapped_uint32"
        else:
            delta = raw_sensor_us - self.raw_previous
            if delta <= 0:
                raise SampleRejected("sensor_time_us did not advance")
            if delta > self.max_gap_us:
                raise SampleRejected(
                    f"sensor_time_us gap {delta}us exceeds {self.max_gap_us}us")
            extended = self.epoch * self.modulus + raw_sensor_us

        if (
            self.extended_previous is not None
            and extended - self.extended_previous > self.max_gap_us
        ):
            raise SampleRejected(
                "sensor_time_us extended gap exceeds "
                f"{self.max_gap_us}us"
            )
        mapped_ns = self.anchor_ros_ns + (
            extended - self.anchor_sensor_us
        ) * 1_000
        if self.last_mapped_ns is not None and mapped_ns <= self.last_mapped_ns:
            raise SampleRejected("mapped ROS timestamp did not advance")
        self.raw_previous = raw_sensor_us
        self.extended_previous = extended
        self.last_mapped_ns = mapped_ns
        if self.mapping_state != "wrapped_uint32":
            self.mapping_state = "anchored"
        return mapped_ns

    def status(self):
        """Return JSON-safe diagnostics for /imu/status."""
        return {
            "timestamp_source": "linear_acceleration_sensor_time_mapped",
            "mapping_state": self.mapping_state,
            "sensor_time_bits": self.sensor_time_bits,
            "epoch": self.epoch,
            "reset_count": self.reset_count,
            "anchor_sensor_time_us": self.anchor_sensor_us,
            "anchor_ros_time_ns": self.anchor_ros_ns,
            "last_sensor_time_us": self.raw_previous,
            "last_mapped_ros_time_ns": self.last_mapped_ns,
            "max_sensor_time_gap_us": self.max_gap_us,
        }


def _identity(report, name):
    """Return per-stream sample progress markers for a stream.

    ``sensor_seq`` is retained in the report for diagnostics, but is not a
    per-stream counter.  The MCU's ``sample_seq``/``count`` pair is the only
    progress marker used to reject duplicate snapshots.
    """
    if not isinstance(report, dict):
        raise SampleRejected(f"{name} report is missing")
    result = {}
    for field in ("sample_seq", "count", "sensor_time_us", "sequence_gap_count"):
        value = report.get(field)
        if value is not None:
            if not _nonnegative_integer(value):
                raise SampleRejected(f"{name}.{field} is invalid")
            result[field] = value
    # ``sequence_gap_count`` is an independent diagnostic/gate counter, not
    # a fourth progress marker.  The current MCU includes it in every report,
    # so require the canonical markers without rejecting that extra field.
    if not {"sample_seq", "count", "sensor_time_us"}.issubset(result):
        raise SampleRejected(f"{name} is missing an MCU progress marker")
    return result


class SampleTracker:
    """Track snapshot progress without treating raw sequence gaps as faults."""

    def __init__(self):
        self.reset_count = None
        self.identities = {}
        self.marker_sensor_times = {}
        self.last_marker_progress_ns = None

    def accept(self, sample, progress_time_ns=None):
        """Validate markers and return whether the linear stream advanced.

        ``sample_seq`` and ``count`` are MCU-owned canonical progress markers.
        The raw SH-2 ``sensor_seq`` and its gap counters remain diagnostics and
        are intentionally never used as a publish gate.  A duplicate or
        orientation-only snapshot is valid to read but returns ``False`` so
        callers do not republish without a new linear sample.
        """
        reset_count = sample.get("reset_count") if isinstance(sample, dict) else None
        if not _nonnegative_integer(reset_count):
            raise SampleRejected("reset_count is missing or invalid")
        # The top-level field is an aggregate diagnostic (the MCU sums the
        # independent per-stream counters).  Validate its shape when present,
        # but never use its value as a cross-report continuity gate.
        source_gap_count = sample.get("source_sequence_gap_count")
        if not _nonnegative_integer(source_gap_count):
            raise SampleRejected("source_sequence_gap_count is missing or invalid")
        identities = {name: _identity(sample.get(name), name) for name in STREAMS}
        if progress_time_ns is None:
            progress_time_ns = time.monotonic_ns()
        if not _integer(progress_time_ns) or progress_time_ns < 0:
            raise SampleRejected("host progress time is invalid")
        if (
            self.last_marker_progress_ns is not None
            and progress_time_ns < self.last_marker_progress_ns
        ):
            raise SampleRejected("host progress time moved backwards")
        if self.reset_count is not None:
            if reset_count != self.reset_count:
                # A reset starts a new sensor epoch.  Clear marker baselines
                # so the first complete post-reset snapshot can be published;
                # the ROS odometry node observes the status change and asks
                # the learner to recalibrate before integrating again.
                self.reset_count = reset_count
                self.identities = identities
                self.marker_sensor_times = {
                    name: identities[name]["sensor_time_us"]
                    for name in UPDATE_MARKER_STREAMS
                }
                self.last_marker_progress_ns = progress_time_ns
                return True

            linear_updated = False
            for name in STREAMS:
                old = self.identities[name]
                new = identities[name]
                if new["sample_seq"] < old["sample_seq"]:
                    raise SampleRejected(f"{name}.sample_seq moved backwards")
                for field in ("count", "sensor_time_us"):
                    if new[field] < old[field]:
                        raise SampleRejected(f"{name}.{field} moved backwards")
                if name not in UPDATE_MARKER_STREAMS:
                    continue
                marker_changed = (
                    new["sample_seq"] != old["sample_seq"]
                    or new["count"] != old["count"]
                )
                if not marker_changed:
                    continue
                if name == "linear_acceleration":
                    linear_updated = True
                previous_sensor_time = self.marker_sensor_times[name]
                sensor_time_gap = new["sensor_time_us"] - previous_sensor_time
                if sensor_time_gap > MARKER_SENSOR_TIME_MAX_GAP_US:
                    raise SampleRejected(
                        f"{name} sensor time gap {sensor_time_gap}us exceeds "
                        f"{MARKER_SENSOR_TIME_MAX_GAP_US}us"
                    )

            if not linear_updated:
                if (
                    self.last_marker_progress_ns is not None
                    and progress_time_ns - self.last_marker_progress_ns
                    > MARKER_NO_PROGRESS_TIMEOUT_NS
                ):
                    elapsed_s = (
                        progress_time_ns - self.last_marker_progress_ns
                    ) / 1_000_000_000
                    raise SampleRejected(
                        "linear_acceleration/orientation made no progress for "
                        f"{elapsed_s:.3f}s"
                    )
                # A duplicate or a snapshot where only compatibility streams
                # changed is readable for diagnostics, but must not be sent as
                # a new /imu/data message.
                self.identities = identities
                return False

        self.reset_count = reset_count
        # Record the latest sensor clock only when that marker really advanced;
        # otherwise a repeated RPC snapshot must not hide a later time jump.
        for name in UPDATE_MARKER_STREAMS:
            if (
                name not in self.marker_sensor_times
                or identities[name]["sample_seq"]
                != self.identities.get(name, {}).get("sample_seq")
                or identities[name]["count"]
                != self.identities.get(name, {}).get("count")
            ):
                self.marker_sensor_times[name] = identities[name]["sensor_time_us"]
        self.identities = identities
        self.last_marker_progress_ns = progress_time_ns
        return True


def _report_metadata(sample):
    """Keep report time/status/count/reset fields without copying NaN values."""
    reset_count = sample.get("reset_count")
    metadata = {
        "reset_count": reset_count if _nonnegative_integer(reset_count) else None,
        "source_sequence_gap_count": (
            sample.get("source_sequence_gap_count")
            if _nonnegative_integer(sample.get("source_sequence_gap_count"))
            else None
        ),
    }
    for name in STREAMS:
        report = sample.get(name)
        if not isinstance(report, dict):
            metadata[name] = {"status": "missing"}
            continue
        item = {}
        for field in REPORT_FIELDS:
            if field in report and field != "finite":
                value = report[field]
                if isinstance(value, (str, bool, int)) or (
                    isinstance(value, float) and math.isfinite(value)
                ):
                    item[field] = value
        raw = report.get("raw")
        if isinstance(raw, dict):
            item["finite"] = all(
                isinstance(raw.get(axis), (int, float))
                and not isinstance(raw.get(axis), bool)
                and math.isfinite(float(raw.get(axis)))
                for axis in ("x", "y", "z")
            )
        if name == "orientation":
            quaternion = report.get("quaternion")
            if isinstance(quaternion, dict):
                item["finite"] = all(
                    isinstance(quaternion.get(axis), (int, float))
                    and not isinstance(quaternion.get(axis), bool)
                    and math.isfinite(float(quaternion.get(axis)))
                    for axis in ("x", "y", "z", "w")
                )
        metadata[name] = item
    return metadata


def make_envelope(topic, ros_type, sequence, data, timestamp_ms):
    """Build the six-field envelope consumed by ``ros_ws_bridge``."""
    return {
        "topic": topic,
        "ros_type": ros_type,
        "direction": "ws_to_ros",
        "seq": int(sequence),
        "timestamp": int(timestamp_ms),
        "data": data,
    }


class ImuAdapter:
    """Small App Lab loop with no write/control RPCs."""

    def __init__(self, bridge, server, clock_ns=time.time_ns, monotonic=time.monotonic):
        self.bridge = bridge
        self.server = server
        if Bno086Imu is None:
            raise RuntimeError("bno086_imu Brick is unavailable")
        self.imu = Bno086Imu(bridge=bridge, timeout_s=RPC_TIMEOUT_S)
        self.clock_ns = clock_ns
        self.monotonic = monotonic
        self.clients = set()
        self.clients_lock = threading.Lock()
        self.tracker = SampleTracker()
        self.clock_mapper = SensorClockMapper()
        self.sequence = 0
        self.next_sample = 0.0
        self.next_status = 0.0
        self.last_receive_ns = None
        self.last_valid_snapshot_ns = None
        self.last_rpc_ok = False
        self.last_rpc_error = "not_started"
        self.last_fault = "not_started"
        self.fault_count = 0
        self.last_report = {"reset_count": None}
        self.network_error_count = 0
        self.last_network_error = None
        self.next_network_log = 0.0
        self._install_callbacks()

    @staticmethod
    def _client_id(info):
        if isinstance(info, dict):
            return info.get("client_id", info.get("id"))
        return getattr(info, "client_id", getattr(info, "id", None))

    def _install_callbacks(self):
        self.server.on_connect(self._on_connect)
        self.server.on_disconnect(self._on_disconnect)
        # This lesson is uplink-only.  No on_message callback means no input
        # can become a control/RPC path accidentally.

    def _on_connect(self, info):
        client_id = self._client_id(info)
        if client_id is not None:
            with self.clients_lock:
                self.clients.add(client_id)

    def _on_disconnect(self, info, code, reason):
        del code, reason
        client_id = self._client_id(info)
        if client_id is not None:
            with self.clients_lock:
                self.clients.discard(client_id)

    def _log_fault(self, reason):
        reason = str(reason)
        self.last_fault = reason
        self.fault_count += 1
        if reason != getattr(self, "last_logged_fault", None):
            print(f"[BNO086] {reason}", flush=True)
            self.last_logged_fault = reason

    def _log_network_error(self, error):
        self.network_error_count += 1
        self.last_network_error = f"{type(error).__name__}: {error}"
        now = self.monotonic()
        if now >= self.next_network_log:
            print(f"[BNO086] WebSocket send error: {self.last_network_error}", flush=True)
            self.next_network_log = now + 1.0

    def _send_envelope(self, envelope):
        payload = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        with self.clients_lock:
            client_ids = tuple(self.clients)
        for client_id in client_ids:
            try:
                result = self.server.send(client_id, payload)
                if result is False:
                    raise RuntimeError(f"server.send returned False for {client_id}")
            except Exception as error:  # the disconnect callback removes stale clients
                self._log_network_error(error)

    def _publish(self, topic, ros_type, data, timestamp_ms):
        self.sequence += 1
        envelope = make_envelope(topic, ros_type, self.sequence, data, timestamp_ms)
        self._send_envelope(envelope)

    @staticmethod
    def _decode_rpc(value):
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise SampleRejected("RPC result is not an object")
        return value

    def poll_sample(self):
        """Read one snapshot and publish only after all gates pass."""
        self.last_rpc_ok = False
        self.last_rpc_error = None
        try:
            value = self.imu.get_sample()
            self.last_rpc_ok = True
            # Take the explicit host receive timestamp immediately after the
            # RPC returns, before parsing/building the ROS message.
            receive_ns = int(self.clock_ns())
            if self.last_receive_ns is not None and receive_ns < self.last_receive_ns:
                self._log_fault(
                    "Linux receive time moved backwards; sample not published"
                )
                return
            self.last_receive_ns = receive_ns
            sample = self._decode_rpc(value)
            self.last_report = _report_metadata(sample)
            marker_updated = self.tracker.accept(
                sample,
                progress_time_ns=int(self.monotonic() * 1_000_000_000),
            )
            if not marker_updated:
                return
            linear_report = sample["linear_acceleration"]
            mapped_stamp_ns = self.clock_mapper.observe(
                linear_report["sensor_time_us"],
                sample["reset_count"],
                receive_ns,
            )
            data = _sample_data(sample, mapped_stamp_ns)
            self._publish(
                IMU_TOPIC,
                IMU_TYPE,
                data,
                mapped_stamp_ns // 1_000_000,
            )
            self.last_valid_snapshot_ns = receive_ns
            self.last_fault = "none"
        except Exception as error:
            if not self.last_rpc_ok:
                self.last_rpc_error = f"{type(error).__name__}: {error}"
            self._log_fault(f"sample rejected: {type(error).__name__}: {error}")

    def _status_data(self):
        try:
            websocket = self.server.get_status()
        except Exception as error:
            websocket = {"status_error": f"{type(error).__name__}: {error}"}
        return {
            "frame_id": FRAME_ID,
            "imu_topic": IMU_TOPIC,
            "status_topic": STATUS_TOPIC,
            "last_rpc_ok": self.last_rpc_ok,
            "last_rpc_error": self.last_rpc_error,
            "last_fault": self.last_fault,
            "fault_count": self.fault_count,
            "last_receive_time_ns": self.last_receive_ns,
            "last_valid_snapshot_time_ns": self.last_valid_snapshot_ns,
            "timestamp_source": "linear_acceleration_sensor_time_mapped",
            "timestamp_mapping": self.clock_mapper.status(),
            "source_sequence_gap_count": self.last_report.get(
                "source_sequence_gap_count"
            ),
            "snapshot_rate_hz": SNAPSHOT_RATE_HZ,
            "sample_period_s": SAMPLE_PERIOD_S,
            "rpc_timeout_s": RPC_TIMEOUT_S,
            "marker_no_progress_timeout_s": MARKER_NO_PROGRESS_TIMEOUT_S,
            "marker_sensor_time_max_gap_us": MARKER_SENSOR_TIME_MAX_GAP_US,
            "update_marker_streams": UPDATE_MARKER_STREAMS,
            "next_seq": self.sequence + 1,
            "websocket": websocket,
            "network_error_count": self.network_error_count,
            "last_network_error": self.last_network_error,
            "report": self.last_report,
            "orientation_mode": "game_rotation_vector (non-magnetic north)",
            "tf_note": "No TF is fabricated by this adapter.",
        }

    def publish_status(self):
        """Publish a 1 Hz String heartbeat even when sample RPCs fail."""
        now_ns = int(self.clock_ns())
        status = self._status_data()
        websocket = status.get("websocket", {})
        clients = websocket.get("client_count", len(self.clients))
        print(
            f"[BNO086 ROS] clients={clients} rpc_ok={self.last_rpc_ok} "
            f"fault={self.last_fault}",
            flush=True,
        )
        status_string = json.dumps(
            status, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        self._publish(
            STATUS_TOPIC,
            STATUS_TYPE,
            {"data": status_string},
            now_ns // 1_000_000,
        )

    def _advance_deadline(self, deadline, period, now):
        """Advance one absolute deadline without replaying missed periods."""
        next_deadline = deadline + period
        if next_deadline <= now:
            return now + period
        return next_deadline

    def loop(self):
        now = self.monotonic()
        if now >= self.next_sample:
            self.poll_sample()
            self.next_sample = self._advance_deadline(
                self.next_sample,
                SAMPLE_PERIOD_S,
                self.monotonic(),
            )

        now = self.monotonic()
        if now >= self.next_status:
            try:
                self.publish_status()
            except Exception as error:
                self._log_network_error(error)
            self.next_status = self._advance_deadline(
                self.next_status,
                STATUS_PERIOD_S,
                self.monotonic(),
            )
        time.sleep(0.001)


def run_app():
    if App is None or Bridge is None or WebSocketServer is None or Bno086Imu is None:
        raise RuntimeError("run_app must be executed inside Arduino App Lab")
    adapter = ImuAdapter(Bridge, WebSocketServer())
    App.run(user_loop=adapter.loop)


if __name__ == "__main__":
    run_app()
