import json
import unittest

import main
from sensor_contract import SensorContractError


def telemetry_payload(**overrides) -> dict:
    payload = {
        "type": "sensor_batch",
        "schema_version": 1,
        "device_id": "rail-left-01",
        "rail_side": "left",
        "boot_id": "a1b2c3d4",
        "firmware_version": "0.3.0",
        "batch_seq": 7,
        "dropped_batches": 0,
        "status_flags": 12,
        "samples": [
            {
                "sample_seq": 70,
                "uptime_us": 1_000_000,
                "position_mm": 100.0,
                "sensor_distance_mm": 4.0,
                "adc_raw": 1000,
                "adc_voltage_v": 0.125,
                "sensor_voltage_v": 0.99,
                "accel_mps2": [0.1, 0.2, 9.8],
                "gyro_radps": [0.01, 0.02, 0.03],
            }
        ],
    }
    payload.update(overrides)
    return payload


class MqttIngestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        main.sensor_last_batch_seq.clear()
        main.sensor_node_state.clear()
        while not main.sensor_queue.empty():
            main.sensor_queue.get_nowait()
            main.sensor_queue.task_done()

    async def test_accepts_matching_telemetry_topic(self) -> None:
        accepted = await main.process_mqtt_message(
            "rail/v1/nodes/rail-left-01/telemetry",
            json.dumps(telemetry_payload()).encode("utf-8"),
            10.0,
        )

        self.assertEqual(accepted, 1)
        item = main.sensor_queue.get_nowait()
        self.assertEqual(item["source"], "mqtt")
        self.assertEqual(item["left"]["device_id"], "rail-left-01")
        self.assertTrue(main.sensor_node_state["left"]["connected"])

    async def test_rejects_topic_device_mismatch(self) -> None:
        with self.assertRaises(SensorContractError):
            await main.process_mqtt_message(
                "rail/v1/nodes/rail-right-01/telemetry",
                json.dumps(telemetry_payload()).encode("utf-8"),
                10.0,
            )

    async def test_skips_duplicate_batch_seq_on_the_same_boot(self) -> None:
        payload = json.dumps(telemetry_payload(batch_seq=3)).encode("utf-8")
        first = await main.process_mqtt_message(
            "rail/v1/nodes/rail-left-01/telemetry", payload, 10.0
        )
        second = await main.process_mqtt_message(
            "rail/v1/nodes/rail-left-01/telemetry", payload, 10.1
        )

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(main.sensor_queue.qsize(), 1)

    async def test_accepts_status_and_lwt_offline(self) -> None:
        online = {
            "type": "node_status",
            "schema_version": 1,
            "device_id": "rail-right-01",
            "rail_side": "right",
            "boot_id": "bbbbcccc",
            "firmware_version": "0.3.0",
            "status": "online",
            "status_flags": 0,
        }
        await main.process_mqtt_message(
            "rail/v1/nodes/rail-right-01/status",
            json.dumps(online).encode("utf-8"),
            10.0,
        )
        self.assertTrue(main.sensor_node_state["right"]["connected"])

        offline = {**online, "status": "offline"}
        await main.process_mqtt_message(
            "rail/v1/nodes/rail-right-01/status",
            json.dumps(offline).encode("utf-8"),
            11.0,
        )
        self.assertFalse(main.sensor_node_state["right"]["connected"])
        self.assertEqual(main.sensor_queue.qsize(), 0)

    async def test_tracks_left_and_right_nodes_independently(self) -> None:
        left = telemetry_payload()
        right = telemetry_payload(
            device_id="rail-right-01",
            rail_side="right",
            boot_id="22222222",
            batch_seq=1,
        )
        await main.process_mqtt_message(
            "rail/v1/nodes/rail-left-01/telemetry",
            json.dumps(left).encode("utf-8"),
            10.0,
        )
        await main.process_mqtt_message(
            "rail/v1/nodes/rail-right-01/telemetry",
            json.dumps(right).encode("utf-8"),
            10.0,
        )
        await main.process_mqtt_message(
            "rail/v1/nodes/rail-left-01/status",
            json.dumps(
                {
                    "type": "node_status",
                    "device_id": "rail-left-01",
                    "rail_side": "left",
                    "status": "offline",
                    "status_flags": 12,
                }
            ).encode("utf-8"),
            11.0,
        )

        self.assertFalse(main.sensor_node_state["left"]["connected"])
        self.assertTrue(main.sensor_node_state["right"]["connected"])


if __name__ == "__main__":
    unittest.main()
