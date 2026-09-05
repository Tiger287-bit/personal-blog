"""A small, read-only Python wrapper around the BNO086 MCU RPC API.

The MCU owns the sensor driver, sampling loop, cache and report-quality
flags.  This module deliberately does not import ``arduino.app_utils`` at
module import time: importing the Brick is therefore safe for host tests,
and the default ``Bridge`` object is resolved only when an RPC is requested.
"""

from __future__ import annotations

import json
import math
from typing import Any, Mapping


class ProtocolError(ValueError):
    """The MCU response is not a supported JSON/sample structure."""


class RpcError(RuntimeError):
    """The RouterBridge could not execute an IMU RPC."""


_STREAMS = (
    "accelerometer",
    "linear_acceleration",
    "gyroscope",
    "orientation",
)
_VECTOR_STREAMS = ("accelerometer", "linear_acceleration", "gyroscope")
_VECTOR_AXES = ("x", "y", "z")
_QUATERNION_AXES = ("x", "y", "z", "w")
_QUATERNION_NORM_TOLERANCE = 0.05
_MAX_SEQUENCE = 255
_MAX_UINT32 = (1 << 32) - 1
_MAX_UINT64 = (1 << 64) - 1


def _reject_json_constant(token: str) -> None:
    """Reject the non-standard numeric constants accepted by json.loads."""

    raise ProtocolError(f"RPC response contains non-finite JSON constant {token}")


def _is_integer(value: Any) -> bool:
    """Return whether *value* is an integer but not a JSON boolean."""

    return isinstance(value, int) and not isinstance(value, bool)


def _is_nonnegative_integer(value: Any) -> bool:
    return _is_integer(value) and value >= 0


def _is_finite_number(value: Any) -> bool:
    """Return whether *value* is a finite JSON number, excluding booleans."""

    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def _reject_nonfinite(value: Any, path: str = "response") -> None:
    """Reject NaN/Infinity anywhere in a decoded JSON-compatible value.

    ``json.loads`` accepts NaN and Infinity as extensions unless a
    ``parse_constant`` hook is supplied.  A caller-provided dict can also
    contain Python non-finite floats, so both paths are checked here.
    """

    if isinstance(value, float) and not math.isfinite(value):
        raise ProtocolError(f"{path} contains a non-finite number")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_nonfinite(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_nonfinite(child, f"{path}[{index}]")


def _parse_object(value: Any, method: str) -> dict[str, Any]:
    """Decode an RPC result and require a finite JSON object."""

    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError(f"{method} returned non-UTF-8 bytes") from exc

    if isinstance(value, str):
        try:
            value = json.loads(
                value,
                parse_constant=_reject_json_constant,
            )
        except ProtocolError:
            raise
        except (TypeError, json.JSONDecodeError) as exc:
            raise ProtocolError(f"{method} returned invalid JSON") from exc

    if not isinstance(value, dict):
        raise ProtocolError(f"{method} result must be a JSON object")
    _reject_nonfinite(value, method)
    return value


def _require_finite_number(value: Any, path: str) -> None:
    _require(_is_finite_number(value), f"{path} must be a finite number")


def _require_nonnegative_integer(value: Any, path: str) -> None:
    _require(_is_nonnegative_integer(value), f"{path} must be a non-negative integer")


def _require_unsigned_integer(value: Any, maximum: int, path: str) -> None:
    _require_nonnegative_integer(value, path)
    _require(value <= maximum, f"{path} is outside the MCU integer range")


def _require_boolean(value: Any, path: str) -> None:
    _require(isinstance(value, bool), f"{path} must be boolean")


def _validate_vector(values: Any, path: str) -> None:
    _require(isinstance(values, dict), f"{path} must be an object")
    for axis in _VECTOR_AXES:
        _require_finite_number(values.get(axis), f"{path}.{axis}")


def _validate_quaternion(values: Any, path: str) -> None:
    _require(isinstance(values, dict), f"{path} must be an object")
    for axis in _QUATERNION_AXES:
        _require_finite_number(values.get(axis), f"{path}.{axis}")


def _validate_report_common(report: Any, path: str) -> None:
    """Validate transport/schema fields while allowing invalid quality flags."""

    _require(isinstance(report, dict), f"{path} must be an object")
    _require_boolean(report.get("valid"), f"{path}.valid")
    _require_boolean(report.get("stale"), f"{path}.stale")

    quality = report.get("accuracy", report.get("quality"))
    _require(_is_integer(quality), f"{path}.accuracy/quality must be an integer")
    _require(0 <= quality <= 3, f"{path}.accuracy/quality must be in 0..3")

    # The MCU exposes a monotonic per-stream sample sequence for snapshot
    # de-duplication. ``sensor_seq`` remains the raw SH-2 source byte, while
    # ``sequence_gap_count`` is maintained independently for this report
    # stream. The top-level aggregate is diagnostic only and is not a
    # cross-report continuity counter.
    _require_unsigned_integer(report.get("seq"), _MAX_UINT32, f"{path}.seq")
    _require_unsigned_integer(
        report.get("sample_seq"), _MAX_UINT32, f"{path}.sample_seq"
    )
    _require_unsigned_integer(
        report.get("sensor_seq"), _MAX_SEQUENCE, f"{path}.sensor_seq"
    )
    _require_unsigned_integer(
        report.get("sensor_time_us"), _MAX_UINT64, f"{path}.sensor_time_us"
    )
    _require_unsigned_integer(report.get("count"), _MAX_UINT32, f"{path}.count")
    _require_unsigned_integer(
        report.get("sequence_gap_count"),
        _MAX_UINT32,
        f"{path}.sequence_gap_count",
    )


def _validate_sample_structure(sample: Any) -> None:
    """Validate the current MCU snapshot shape without applying quality gates."""

    _require(isinstance(sample, dict), "sample must be an object")
    _require_unsigned_integer(sample.get("reset_count"), _MAX_UINT32, "reset_count")
    _require_unsigned_integer(
        sample.get("source_sequence_gap_count"),
        _MAX_UINT32,
        "source_sequence_gap_count",
    )

    for name in _STREAMS:
        _validate_report_common(sample.get(name), name)

    accelerometer = sample["accelerometer"]
    gyroscope = sample["gyroscope"]
    orientation = sample["orientation"]

    for name, report in (
        ("accelerometer", accelerometer),
        ("linear_acceleration", sample["linear_acceleration"]),
        ("gyroscope", gyroscope),
    ):
        _require(isinstance(report.get("unit"), str), f"{name}.unit must be a string")
        _validate_vector(report.get("raw"), f"{name}.raw")
        # ``filtered`` is a diagnostic field emitted by the current sketch.
        # It is optional for older snapshots, but a present null or malformed
        # object is still a protocol error; the wrapper never manufactures it.
        if "filtered" in report:
            _validate_vector(report["filtered"], f"{name}.filtered")

    _require(isinstance(orientation.get("mode"), str), "orientation.mode must be a string")
    _validate_quaternion(orientation.get("quaternion"), "orientation.quaternion")
    if "norm_before_normalize" in orientation:
        _require_finite_number(
            orientation["norm_before_normalize"],
            "orientation.norm_before_normalize",
        )


def _validate_status_structure(status: Any) -> None:
    """Validate the MCU ``imu_get_status`` object without dropping fields.

    The status RPC is produced by the MCU library, not by the ROS adapter. All
    keys below are emitted on every call, including when the IMU is not ready;
    unknown future diagnostic keys remain allowed and are preserved by the
    caller.
    """

    _require(isinstance(status, dict), "status must be an object")

    for key in ("bridge_ready", "api_ready", "imu_ready"):
        _require_boolean(status.get(key), f"status.{key}")

    reports = status.get("reports")
    _require(isinstance(reports, dict), "status.reports must be an object")
    for key in (
        "all_ready",
        "accelerometer_ready",
        "linear_acceleration_ready",
        "gyroscope_ready",
        "orientation_ready",
    ):
        _require_boolean(reports.get(key), f"status.reports.{key}")

    _require(isinstance(status.get("bus"), str), "status.bus must be a string")
    _require(
        isinstance(status.get("address"), str),
        "status.address must be a string",
    )
    _require_unsigned_integer(
        status.get("i2c_clock_hz"),
        _MAX_UINT32,
        "status.i2c_clock_hz",
    )

    intervals = status.get("interval_us")
    _require(isinstance(intervals, dict), "status.interval_us must be an object")
    for key in (
        "accelerometer",
        "linear_acceleration",
        "gyroscope",
        "orientation",
    ):
        _require_unsigned_integer(
            intervals.get(key), _MAX_UINT32, f"status.interval_us.{key}"
        )

    _require_finite_number(
        status.get("display_filter_alpha"),
        "status.display_filter_alpha",
    )

    pins = status.get("pins")
    _require(isinstance(pins, dict), "status.pins must be an object")
    for key in ("int", "int_level", "reset", "reset_level"):
        _require_unsigned_integer(pins.get(key), _MAX_UINT32, f"status.pins.{key}")

    for key in (
        "product_entries",
        "part_number",
        "build_number",
        "reset_count",
        "source_sequence_gap_count",
    ):
        _require_unsigned_integer(status.get(key), _MAX_UINT32, f"status.{key}")
    _require(
        isinstance(status.get("software_version"), str),
        "status.software_version must be a string",
    )

    counts = status.get("counts")
    _require(isinstance(counts, dict), "status.counts must be an object")
    for key in (
        "accelerometer",
        "linear_acceleration",
        "gyroscope",
        "orientation",
        "unknown",
    ):
        _require_unsigned_integer(
            counts.get(key), _MAX_UINT32, f"status.counts.{key}"
        )

    sequence_gaps = status.get("sequence_gaps")
    _require(isinstance(sequence_gaps, dict), "status.sequence_gaps must be an object")
    for key in (
        "accelerometer",
        "linear_acceleration",
        "gyroscope",
        "orientation",
    ):
        _require_unsigned_integer(
            sequence_gaps.get(key),
            _MAX_UINT32,
            f"status.sequence_gaps.{key}",
        )

    _require(isinstance(status.get("last_error"), str), "status.last_error must be a string")


def _semantic_is_valid(sample: Mapping[str, Any]) -> bool:
    """Apply the quality/unit/finite/quaternion gate after schema validation."""

    for name in _STREAMS:
        report = sample[name]
        quality = report.get("accuracy", report.get("quality"))
        if report["valid"] is not True or report["stale"] is not False:
            return False
        if not _is_integer(quality) or not 1 <= quality <= 3:
            return False

    for name in ("accelerometer", "linear_acceleration"):
        if sample[name].get("unit") != "m/s^2":
            return False
    if sample["gyroscope"].get("unit") != "rad/s":
        return False
    if sample["orientation"].get("mode") != "game_rotation_vector":
        return False

    # Structure validation already checks finite components.  Re-check the
    # vectors here to keep this predicate self-documenting and future-proof.
    for name in _VECTOR_STREAMS:
        report = sample[name]
        if not all(_is_finite_number(report["raw"][axis]) for axis in _VECTOR_AXES):
            return False
        filtered = report.get("filtered")
        if filtered is not None and not all(
            _is_finite_number(filtered[axis]) for axis in _VECTOR_AXES
        ):
            return False

    quaternion = sample["orientation"]["quaternion"]
    if not all(_is_finite_number(quaternion[axis]) for axis in _QUATERNION_AXES):
        return False
    try:
        norm = math.hypot(*(float(quaternion[axis]) for axis in _QUATERNION_AXES))
    except (OverflowError, ValueError):
        return False
    return math.isfinite(norm) and abs(norm - 1.0) <= _QUATERNION_NORM_TOLERANCE


class Bno086Imu:
    """Read-only access to the BNO086 MCU snapshot and status RPCs.

    Construction performs no import of App Lab and no RPC.  With the default
    ``bridge=None`` the App Lab ``Bridge`` object is imported lazily on the
    first call.  Passing a Bridge-compatible object is useful for host tests.
    """

    def __init__(self, bridge: Any = None, timeout_s: float = 3.0):
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
            raise ValueError("timeout_s must be a finite positive number")
        try:
            normalized_timeout = float(timeout_s)
        except (OverflowError, ValueError):
            raise ValueError("timeout_s must be a finite positive number") from None
        if not math.isfinite(normalized_timeout) or normalized_timeout <= 0:
            raise ValueError("timeout_s must be a finite positive number")
        self._bridge = bridge
        self.timeout_s = normalized_timeout

    def _resolve_bridge(self) -> Any:
        if self._bridge is None:
            try:
                from arduino.app_utils import Bridge
            except ImportError as exc:
                raise RpcError(
                    "Arduino App Lab Bridge is unavailable; pass a bridge for host use"
                ) from exc
            self._bridge = Bridge
        return self._bridge

    def _call(self, method: str) -> Any:
        bridge = self._resolve_bridge()
        try:
            call = getattr(bridge, "call")
            return call(method, timeout=self.timeout_s)
        except Exception as exc:
            raise RpcError(f"RouterBridge call {method!r} failed: {exc}") from exc

    def get_sample(self) -> dict[str, Any]:
        """Read and structurally validate one current MCU snapshot.

        ``valid=false`` or ``stale=true`` is intentionally returned for
        diagnosis.  Use :meth:`is_valid` when a caller needs the quality gate.
        No result is cached, filtered, timestamped or otherwise synthesized.
        """

        sample = _parse_object(self._call("imu_get_sample"), "imu_get_sample")
        _validate_sample_structure(sample)
        return sample

    def get_status(self) -> dict[str, Any]:
        """Read and validate the MCU status object without changing it."""

        status = _parse_object(self._call("imu_get_status"), "imu_get_status")
        _validate_status_structure(status)
        return status

    @staticmethod
    def is_valid(sample: Mapping[str, Any]) -> bool:
        """Return the four-stream quality/unit/quaternion validity result.

        This is a pure predicate: it does not call RouterBridge, mutate the
        input or cache a sample.  A malformed structure is a protocol error;
        a well-formed but invalid/stale/low-quality sample returns ``False``.
        """

        _reject_nonfinite(sample, "sample")
        _validate_sample_structure(sample)
        return _semantic_is_valid(sample)


__all__ = ["Bno086Imu", "ProtocolError", "RpcError"]
