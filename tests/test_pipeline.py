import unittest
from pathlib import Path
import re

import main
from rail_defect import DefectRuleEngine, estimate_roll_deg


def current_sample(position_mm: float = 450.0, distance_mm: float = 4.2, accel_x: float = 0.1) -> dict:
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
        "sensor_distance_mm": distance_mm,
        "adc_raw": 1000,
        "adc_voltage_v": 0.125,
        "sensor_voltage_v": 0.99,
        "accel_x": accel_x,
        "accel_y": 0.2,
        "accel_z": 9.9,
        "gyro_x": 0.01,
        "gyro_y": 0.02,
        "gyro_z": 0.03,
    }


def rail_pair(position_cm: float, gap_l: float, gap_r: float, accel_x: float = 0.0) -> tuple[dict, dict]:
    stamp = 5_000.0 + position_cm
    def one(gap: float) -> dict:
        return {
            "_received_at": stamp,
            "position_mm": position_cm * 10.0,
            "sensor_distance_mm": gap,
            "accel_x": accel_x,
            "accel_y": 0.0,
            "accel_z": 9.80665,
        }
    return one(gap_l), one(gap_r)


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        main.reset_rail_risk_state()
        main.latest_ws_payload_by_side.clear()

    def test_roll_uses_accelerometer_tilt(self) -> None:
        roll = estimate_roll_deg(1.0, 0.0, 9.8)
        self.assertIsNotNone(roll)
        self.assertGreater(abs(roll or 0.0), 0.0)

    def test_four_classes_and_three_stages(self) -> None:
        engine = DefectRuleEngine(segment_count=20, rail_length_cm=100.0)
        seen = set()
        motions = set()
        for lap in (1, 2, 3):
            for x in range(0, 101):
                left = main.generate_crane_demo_sample(float(x), "left", lap)
                right = main.generate_crane_demo_sample(float(x), "right", lap)
                stamp = 1_000.0 + lap * 30.0 + x * 0.1
                left["_received_at"] = stamp
                right["_received_at"] = stamp
                snapshot = engine.evaluate_pair(left, right)
                seen.add(snapshot["defect_type"])
                motions.add(snapshot["motion"])
        self.assertIn("joint_step", seen)
        self.assertIn("vertical", seen)
        self.assertIn("cross_level", seen)
        self.assertIn("stop", motions)
        self.assertIn("slow", motions)
        types = {item["defect_type"] for item in engine.defect_list()}
        self.assertIn("joint_step", types)
        self.assertTrue(any(item.get("remaining_s") is not None for item in engine.defect_list()))

    def test_cross_level_needs_tilt_agreement(self) -> None:
        engine = DefectRuleEngine(segment_count=20, rail_length_cm=100.0)
        for x in range(0, 15):
            engine.evaluate_pair(*rail_pair(x, 4.0, 4.0))
        disagreed = engine.evaluate_pair(*rail_pair(82, 10.0, 4.0, accel_x=-2.0))
        self.assertNotEqual(disagreed["defect_type"], "cross_level")

    def test_downlink_has_defects_not_pred(self) -> None:
        sample = current_sample()
        evaluation = {
            "roll_deg": 6.0,
            "distance_delta_mm": 0.8,
            "roll_delta_deg": 5.0,
            "score": 0.7,
            "abnormal": True,
        }
        payload = main.build_side_ws_payload(
            sample,
            side="left",
            evaluation=evaluation,
            rail_risk=[0.0, 0.5],
            defects=[{
                "side": "both",
                "from_mm": 200.0,
                "to_mm": 250.0,
                "defect_type": "joint_step",
                "stage": "danger",
            }],
        )

        self.assertEqual(payload["distance_x"], 45.0)
        self.assertEqual(payload["position_mm"], 450.0)
        self.assertEqual(payload["sensor_distance_mm"], 4.2)
        self.assertEqual(payload["abnormal_score"], 0.7)
        self.assertEqual(payload["defects"][0]["defect_type"], "joint_step")
        self.assertEqual(payload["defects"][0]["from_mm"], 200.0)
        self.assertNotIn("PRED_RAIL_DEFORM", payload)
        self.assertNotIn("CREST", payload)
        self.assertNotIn("DIST", payload)
        self.assertNotIn("AAX", payload)

    def test_influx_line_protocol_contains_current_fields(self) -> None:
        sample = current_sample()
        point = main.build_influx_point(
            sample,
            side="left",
            source="mqtt",
            evaluation={
                "tilt_deg": 4.0,
                "roll_deg": 4.0,
                "delta_mm": 6.0,
                "distance_delta_mm": 6.0,
                "m_mm": 0.2,
                "apeak": 0.1,
                "score": 0.6,
            },
        )
        line = point.to_line_protocol()

        self.assertIn("device_id=rail-left-01", line)
        self.assertIn("boot_id=a1b2c3d4", line)
        self.assertIn("position_mm=450", line)
        self.assertIn("sensor_distance_mm=4.2", line)
        self.assertIn("mpu_accel_x=0.1", line)
        self.assertIn("abnormal_score=0.6", line)
        self.assertIn("delta_mm=6", line)
        self.assertIn("apeak=0.1", line)
        self.assertNotIn("pred_rail_deform", line)
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
        self.assertIn("unity-canvas", declared_ids)
        self.assertIn("이음부 단차", html)
        self.assertNotIn("PRED_RAIL_DEFORM", html)
        self.assertNotIn("Godot", html)

    def test_combines_independent_left_and_right_nodes(self) -> None:
        main.latest_ws_payload_by_side.clear()
        main.sensor_node_state.clear()
        main.sensor_node_state["left"] = {"connected": True}
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
