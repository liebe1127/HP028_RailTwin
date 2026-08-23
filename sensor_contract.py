"""ESP32-C3 WebSocket sensor contract validation and normalization."""

from __future__ import annotations

import math
import re
from typing import Any

SCHEMA_VERSION = 1
RAIL_SIDES = ("left", "right")
MAX_SAMPLES_PER_BATCH = 100
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class SensorContractError(ValueError):
    """Raised when an ESP32 sensor payload violates the versioned contract."""


def _required_int(
    value: Any,
    field: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SensorContractError(f"{field} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise SensorContractError(f"{field} is out of range")
    return value


def _optional_float(
    value: Any,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SensorContractError(f"{field} must be numeric or null")
    result = float(value)
    if not math.isfinite(result):
        raise SensorContractError(f"{field} must be finite")
    if minimum is not None and result < minimum:
        raise SensorContractError(f"{field} is below its minimum")
    if maximum is not None and result > maximum:
        raise SensorContractError(f"{field} is above its maximum")
    return result


def _axis_vector(value: Any, field: str) -> tuple[float | None, ...]:
    if not isinstance(value, list) or len(value) != 3:
        raise SensorContractError(f"{field} must contain exactly three axes")
    return tuple(
        _optional_float(axis, f"{field}[{index}]")
        for index, axis in enumerate(value)
    )


def normalize_sensor_batch(payload: object, received_at: float) -> list[dict]:
    """
    Validate one schema-v1 sensor batch and return queue items.

    Each returned item contains exactly one rail side so the existing
    left/right consumer can process samples independently.
    """
    if not isinstance(payload, dict):
        raise SensorContractError("payload must be a JSON object")
    if payload.get("type") != "sensor_batch":
        raise SensorContractError("type must be sensor_batch")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SensorContractError("unsupported schema_version")

    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not DEVICE_ID_PATTERN.fullmatch(device_id):
        raise SensorContractError("device_id has an invalid format")

    rail_side = payload.get("rail_side")
    if rail_side not in RAIL_SIDES:
        raise SensorContractError(f"rail_side must be one of {RAIL_SIDES}")

    batch_seq = _required_int(payload.get("batch_seq"), "batch_seq")
    dropped_batches = _required_int(
        payload.get("dropped_batches", 0), "dropped_batches"
    )
    firmware_version = payload.get("firmware_version")
    if firmware_version is not None and not isinstance(firmware_version, str):
        raise SensorContractError("firmware_version must be a string")

    samples = payload.get("samples")
    if not isinstance(samples, list) or not samples:
        raise SensorContractError("samples must be a non-empty array")
    if len(samples) > MAX_SAMPLES_PER_BATCH:
        raise SensorContractError(
            f"samples exceeds the limit of {MAX_SAMPLES_PER_BATCH}"
        )

    validated: list[dict] = []
    previous_seq: int | None = None
    previous_uptime: int | None = None
    for index, raw_sample in enumerate(samples):
        if not isinstance(raw_sample, dict):
            raise SensorContractError(f"samples[{index}] must be an object")

        sample_seq = _required_int(
            raw_sample.get("sample_seq"), f"samples[{index}].sample_seq"
        )
        uptime_us = _required_int(
            raw_sample.get("uptime_us"), f"samples[{index}].uptime_us"
        )
        if previous_seq is not None and sample_seq <= previous_seq:
            raise SensorContractError("sample_seq must increase within a batch")
        if previous_uptime is not None and uptime_us <= previous_uptime:
            raise SensorContractError("uptime_us must increase within a batch")
        previous_seq = sample_seq
        previous_uptime = uptime_us

        acceleration = _axis_vector(
            raw_sample.get("accel_mps2"), f"samples[{index}].accel_mps2"
        )
        gyro = _axis_vector(
            raw_sample.get("gyro_radps"), f"samples[{index}].gyro_radps"
        )

        adc_raw_value = raw_sample.get("adc_raw")
        adc_raw = (
            None
            if adc_raw_value is None
            else _required_int(
                adc_raw_value,
                f"samples[{index}].adc_raw",
                minimum=-32768,
                maximum=32767,
            )
        )
        validated.append(
            {
                "sample_seq": sample_seq,
                "uptime_us": uptime_us,
                "position_mm": _optional_float(
                    raw_sample.get("position_mm"),
                    f"samples[{index}].position_mm",
                ),
                "sensor_distance_mm": _optional_float(
                    raw_sample.get("sensor_distance_mm"),
                    f"samples[{index}].sensor_distance_mm",
                    minimum=0.0,
                ),
                "adc_raw": adc_raw,
                "adc_voltage_v": _optional_float(
                    raw_sample.get("adc_voltage_v"),
                    f"samples[{index}].adc_voltage_v",
                    minimum=-0.5,
                    maximum=6.5,
                ),
                "sensor_voltage_v": _optional_float(
                    raw_sample.get("sensor_voltage_v"),
                    f"samples[{index}].sensor_voltage_v",
                    minimum=-0.5,
                    maximum=35.0,
                ),
                "accel_x": acceleration[0],
                "accel_y": acceleration[1],
                "accel_z": acceleration[2],
                "gyro_x": gyro[0],
                "gyro_y": gyro[1],
                "gyro_z": gyro[2],
            }
        )

    last_uptime_us = int(validated[-1]["uptime_us"])
    queue_items: list[dict] = []
    for sample in validated:
        sample_received_at = received_at - (
            last_uptime_us - int(sample["uptime_us"])
        ) / 1_000_000.0
        sample.update(
            {
                "_received_at": sample_received_at,
                "device_id": device_id,
                "rail_side": rail_side,
                "batch_seq": batch_seq,
                "dropped_batches": dropped_batches,
                "firmware_version": firmware_version,
            }
        )
        queue_items.append(
            {
                "source": "websocket",
                str(rail_side): sample,
            }
        )
    return queue_items
