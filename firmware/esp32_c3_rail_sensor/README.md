# ESP32-C3 rail sensor firmware

Current sensor module firmware for:

- two ESP32-C3 Mini nodes: one attached to the left rail drive and one to the right
- MPU-6050
- ADS1115
- GTRIC LR18-08U
- quadrature wheel encoder

The active data path is WiFi MQTTS QoS 1 to Mosquitto. USB serial output is diagnostic only.

## Arduino libraries

Install these libraries from Arduino Library Manager:

- Adafruit ADS1X15
- Adafruit MPU6050
- Adafruit Unified Sensor
- ArduinoJson
- ESP32MQTTClient by cyijun

Select the ESP32-C3 board package supplied by Espressif.

## Configuration

1. Copy `secrets.h.example` to `secrets.h`.
2. Fill in WiFi credentials and that board's MQTT password.
3. Before compiling the left board, copy `node_profile.left.h.example` to `node_profile.h`. Use the left MQTT password.
4. Before compiling the right board, replace it with `node_profile.right.h.example`. Use the right MQTT password.
5. Verify every pin in `config.h` against both assembled modules.
6. Measure and enter each module's divider resistors in its node profile.
7. Set each profile's encoder counts, direction, and position zero independently.
8. Keep each node's distance conversion disabled until that LR18 has been calibrated.

Example upload sequence:

```bash
cp node_profile.left.h.example node_profile.h
# Compile and upload to the LEFT ESP32-C3.

cp node_profile.right.h.example node_profile.h
# Compile and upload to the RIGHT ESP32-C3.
```

`node_profile.h` is intentionally ignored by Git. Compilation fails when it is missing or when both rail sides are selected. Confirm the serial boot banner before installing each board:

```text
[BOOT] rail-left-01 firmware=0.3.0 rail=left boot=1a2b3c4d
[BOOT] rail-right-01 firmware=0.3.0 rail=right boot=5e6f7788
```

Never upload the left profile to both boards. The broker authenticates each node as `device_id`, and the server uses the combination of `device_id`, `rail_side`, and per-reboot `boot_id` for independent duplicate detection.

With zero node encoder counts per revolution, `position_mm` is transmitted as `null`.
Without calibrated LR18 conversion, `sensor_distance_mm` is transmitted as `null`; raw ADC and voltage fields remain available when ADS1115 is ready.

## Sampling and transport

- MPU-6050 sampling: 100 Hz
- ADS1115 sampling: 20 Hz, latest value attached to each IMU sample
- Upload: ten samples per JSON batch, nominally 10 Hz, MQTT QoS 1
- Topics: `rail/v1/nodes/{device_id}/telemetry` and `/status`
- Status: retained `online` after connect, LWT retained `offline` on unexpected disconnect
- Retry: unpublished batches remain in a bounded RAM queue while MQTT is disconnected
- Overflow: the oldest batch is dropped and `dropped_batches` increments
- Reboot detection: each boot generates a new hexadecimal `boot_id`
- Node health: `status_flags` reports sensor availability and calibration state

QoS 1 PUBACK means the Mosquitto broker accepted the batch. FastAPI still deduplicates with `boot_id` and `batch_seq`.
The firmware refuses MQTT login when the password is empty.
TLS is currently disabled because the NCP endpoint is a public IP (`223.130.128.198:1883`) without a hostname certificate.

## Hardware validation required

The checked-in pin map and divider values are provisional defaults based on the team guide. Before driving the assembled model:

- verify ESP32-C3 boot-strap and exposed-pin constraints;
- verify common ground and sensor supply voltage;
- measure ADS1115 input at minimum and maximum sensor output;
- confirm that the divider leaves margin below the ADC supply rail;
- calibrate encoder direction and counts per wheel revolution;
- verify left and right report unique device IDs and correct rail sides;
- reboot either board and verify its batch sequence is accepted from 1 again;
- record an I2C scan and a short MQTT capture.

## Status flags

- bit 0 (`1`): MPU6050 unavailable
- bit 1 (`2`): ADS1115 unavailable
- bit 2 (`4`): encoder not calibrated
- bit 3 (`8`): LR18 distance conversion not calibrated
