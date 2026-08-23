import unittest

from sensor_contract import SensorContractError, normalize_sensor_batch


def valid_batch() -> dict:
    return {
        "type": "sensor_batch",
        "schema_version": 1,
        "device_id": "rail-sensor-01",
        "rail_side": "left",
        "firmware_version": "0.1.0",
        "batch_seq": 7,
        "dropped_batches": 0,
        "samples": [
            {
                "sample_seq": 70,
                "uptime_us": 1_000_000,
                "position_mm": 100.0,
                "sensor_distance_mm": None,
                "adc_raw": 1000,
                "adc_voltage_v": 0.125,
                "sensor_voltage_v": 0.99,
                "accel_mps2": [0.1, 0.2, 9.8],
                "gyro_radps": [0.01, 0.02, 0.03],
            },
            {
                "sample_seq": 71,
                "uptime_us": 1_010_000,
                "position_mm": 101.0,
                "sensor_distance_mm": 4.0,
                "adc_raw": 1001,
                "adc_voltage_v": 0.126,
                "sensor_voltage_v": 1.0,
                "accel_mps2": [0.1, 0.2, 9.8],
                "gyro_radps": [0.01, 0.02, 0.03],
            },
        ],
    }


class SensorContractTests(unittest.TestCase):
    def test_normalizes_batch_and_recovers_sample_times(self) -> None:
        items = normalize_sensor_batch(valid_batch(), received_at=10.0)

        self.assertEqual(len(items), 2)
        first = items[0]["left"]
        second = items[1]["left"]
        self.assertEqual(first["device_id"], "rail-sensor-01")
        self.assertEqual(first["position_mm"], 100.0)
        self.assertAlmostEqual(first["_received_at"], 9.99)
        self.assertAlmostEqual(second["_received_at"], 10.0)

    def test_rejects_invalid_rail_side(self) -> None:
        batch = valid_batch()
        batch["rail_side"] = "center"
        with self.assertRaises(SensorContractError):
            normalize_sensor_batch(batch, received_at=10.0)

    def test_rejects_non_monotonic_sequence(self) -> None:
        batch = valid_batch()
        batch["samples"][1]["sample_seq"] = 70
        with self.assertRaises(SensorContractError):
            normalize_sensor_batch(batch, received_at=10.0)

    def test_rejects_non_finite_sensor_value(self) -> None:
        batch = valid_batch()
        batch["samples"][0]["accel_mps2"][0] = float("nan")
        with self.assertRaises(SensorContractError):
            normalize_sensor_batch(batch, received_at=10.0)


if __name__ == "__main__":
    unittest.main()
