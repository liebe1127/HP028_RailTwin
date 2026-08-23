import unittest
from collections import deque
from pathlib import Path
import re

import main
from ml.train_rbf_surrogate import FEATURE_NAMES, WINDOW_LEN


def current_sample(position_mm: float = 450.0) -> dict:
    return {
        "_received_at": 1_735_000_000.0,
        "device_id": "rail-left-01",
        "rail_side": "left",
        "boot_id": "a1b2c3d4",
        "firmware_version": "0.3.0",
        "batch_seq": 42,
        "sample_seq": 420,
        "uptime_us": 12_503_400,
        "dropped_batches": 0,
        "status_flags": 0,
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
        self.assertEqual(payload["boot_id"], "a1b2c3d4")
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
            source="mqtt",
            pred_rail_deform=2.5,
            crest=3.0,
        )
        line = point.to_line_protocol()

        self.assertIn("device_id=rail-left-01", line)
        self.assertIn("boot_id=a1b2c3d4", line)
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
        self.assertIn("ESP32 MQTT", html)
        self.assertIn("chart-seq", declared_ids)
        self.assertIn("node-left-badge", declared_ids)

    def test_combines_independent_left_and_right_nodes(self) -> None:
        main.latest_ws_payload_by_side.clear()
        left = {"device_id": "rail-left-01", "rail_side": "left"}
        right = {"device_id": "rail-right-01", "rail_side": "right"}

        left_only = main.update_downlink_snapshot(
            "mqtt", {"left": left}
        )
        combined = main.update_downlink_snapshot(
            "mqtt", {"right": right}
        )

        self.assertIn("left", left_only)
        self.assertNotIn("right", left_only)
        self.assertEqual(combined["left"]["device_id"], "rail-left-01")
        self.assertEqual(combined["right"]["device_id"], "rail-right-01")

    def test_reboot_creates_a_new_deduplication_stream(self) -> None:
        before = {
            "device_id": "rail-left-01",
            "rail_side": "left",
            "boot_id": "11111111",
        }
        after = {**before, "boot_id": "22222222"}

        self.assertNotEqual(
            main.sensor_stream_key(before),
            main.sensor_stream_key(after),
        )

    def test_tracks_left_and_right_nodes_from_mqtt_status(self) -> None:
        main.sensor_node_state.clear()
        left = {
            "device_id": "rail-left-01",
            "rail_side": "left",
            "boot_id": "11111111",
            "firmware_version": "0.3.0",
            "batch_seq": 1,
            "dropped_batches": 0,
            "status_flags": 12,
        }
        right = {
            **left,
            "device_id": "rail-right-01",
            "rail_side": "right",
            "boot_id": "22222222",
        }

        main.record_sensor_node_batch(left)
        main.record_sensor_node_batch(right)
        main.record_sensor_node_status(
            {
                "device_id": "rail-left-01",
                "rail_side": "left",
                "status": "offline",
                "status_flags": 12,
            }
        )

        self.assertFalse(main.sensor_node_state["left"]["connected"])
        self.assertTrue(main.sensor_node_state["right"]["connected"])
        self.assertEqual(main.sensor_node_state["left"]["transport"], "mqtt")


if __name__ == "__main__":
    unittest.main()
