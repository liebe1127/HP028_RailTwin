import unittest
from collections import deque
from pathlib import Path
import re

import main
from ml.train_rbf_surrogate import FEATURE_NAMES, WINDOW_LEN


def current_sample(position_mm: float = 450.0) -> dict:
    return {
        "_received_at": 1_735_000_000.0,
        "device_id": "rail-sensor-01",
        "rail_side": "left",
        "firmware_version": "0.1.0",
        "batch_seq": 42,
        "sample_seq": 420,
        "uptime_us": 12_503_400,
        "dropped_batches": 0,
        "position_mm": position_mm,
        "sensor_distance_mm": 4.2,
        "adc_raw": 1000,
        "adc_voltage_v": 0.125,
        "sensor_voltage_v": 0.99,
        "accel_x": 0.1,
        "accel_y": 0.2,
        "accel_z": 9.9,
        "gyro_x": 0.01,
        "gyro_y": 0.02,
        "gyro_z": 0.03,
    }


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        main.feature_windows["left"] = {
            "accel": deque(maxlen=WINDOW_LEN),
            "gyro": deque(maxlen=WINDOW_LEN),
            "distance": deque(maxlen=WINDOW_LEN),
            "position_time": deque(maxlen=2),
        }

    def test_feature_pipeline_uses_current_sensor_contract(self) -> None:
        features, crest = main.preprocess_and_extract_features(
            current_sample(), "left"
        )

        self.assertEqual(len(features), len(FEATURE_NAMES))
        self.assertGreaterEqual(crest, 0.0)
        self.assertNotIn("AAX", FEATURE_NAMES)
        self.assertIn("distance_delta_mm", FEATURE_NAMES)

    def test_downlink_preserves_position_and_risk_contract(self) -> None:
        sample = current_sample()
        sample["_engineered_features"] = {
            name: float(index) for index, name in enumerate(FEATURE_NAMES)
        }
        payload = main.build_side_ws_payload(
            sample,
            side="left",
            pred_rail_deform=2.5,
            crest=3.0,
            rail_risk=[0.0, 0.5],
        )

        self.assertEqual(payload["distance_x"], 45.0)
        self.assertEqual(payload["position_mm"], 450.0)
        self.assertEqual(payload["sensor_distance_mm"], 4.2)
        self.assertEqual(payload["PRED_RAIL_DEFORM"], 2.5)
        self.assertEqual(payload["rail_risk"], [0.0, 0.5])
        self.assertNotIn("DIST", payload)
        self.assertNotIn("AAX", payload)

    def test_influx_line_protocol_contains_current_fields(self) -> None:
        sample = current_sample()
        sample["_engineered_features"] = {
            name: float(index) for index, name in enumerate(FEATURE_NAMES)
        }
        point = main.build_influx_point(
            sample,
            side="left",
            source="websocket",
            pred_rail_deform=2.5,
            crest=3.0,
        )
        line = point.to_line_protocol()

        self.assertIn("device_id=rail-sensor-01", line)
        self.assertIn("position_mm=450", line)
        self.assertIn("sensor_distance_mm=4.2", line)
        self.assertIn("mpu_accel_x=0.1", line)
        self.assertIn("pred_rail_deform=2.5", line)
        self.assertNotIn("adxl_accel", line)

    def test_frontend_referenced_ids_exist(self) -> None:
        html = (
            Path(__file__).resolve().parents[1] / "frontend" / "index.html"
        ).read_text(encoding="utf-8")
        declared_ids = set(re.findall(r'id="([^"]+)"', html))
        referenced_ids = set(
            re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", html)
        )
        self.assertFalse(referenced_ids - declared_ids)


if __name__ == "__main__":
    unittest.main()
