import re
import unittest
from pathlib import Path


FIRMWARE_DIR = (
    Path(__file__).resolve().parents[1]
    / "firmware"
    / "esp32_c3_rail_sensor"
)


def profile_values(filename: str) -> tuple[str, str]:
    content = (FIRMWARE_DIR / filename).read_text(encoding="utf-8")
    device = re.search(r'DEVICE_ID\[\]\s*=\s*"([^"]+)"', content)
    side = re.search(r'RAIL_SIDE\[\]\s*=\s*"([^"]+)"', content)
    if device is None or side is None:
        raise AssertionError(f"missing identity in {filename}")
    return device.group(1), side.group(1)


class FirmwareProfileTests(unittest.TestCase):
    def test_left_and_right_profiles_are_unique(self) -> None:
        left = profile_values("node_profile.left.h.example")
        right = profile_values("node_profile.right.h.example")

        self.assertEqual(left, ("rail-left-01", "left"))
        self.assertEqual(right, ("rail-right-01", "right"))
        self.assertNotEqual(left, right)

    def test_local_profile_and_secrets_are_ignored(self) -> None:
        ignored = (FIRMWARE_DIR / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("node_profile.h", ignored)
        self.assertIn("secrets.h", ignored)

    def test_firmware_contains_reboot_and_health_fields(self) -> None:
        firmware = (
            FIRMWARE_DIR / "esp32_c3_rail_sensor.ino"
        ).read_text(encoding="utf-8")
        self.assertIn('document["boot_id"]', firmware)
        self.assertIn('document["status_flags"]', firmware)
        self.assertIn("mqttTelemetryTopic", firmware)
        self.assertIn("enableLastWillMessage", firmware)
        self.assertIn("MQTT_QOS", firmware)

    def test_mqtt_endpoint_uses_current_ncp_ip(self) -> None:
        config = (FIRMWARE_DIR / "config.h").read_text(encoding="utf-8")
        self.assertIn("223.130.128.198", config)
        self.assertIn("MQTT_USE_TLS = false", config)
        self.assertIn("MQTT_PORT = 1883", config)

    def test_optional_tls_root_is_embedded(self) -> None:
        certificate = (
            FIRMWARE_DIR / "tls_root_ca.h"
        ).read_text(encoding="utf-8")
        self.assertIn("ISRG Root X1", certificate)
        self.assertIn("-----BEGIN CERTIFICATE-----", certificate)
        self.assertIn("-----END CERTIFICATE-----", certificate)


if __name__ == "__main__":
    unittest.main()
