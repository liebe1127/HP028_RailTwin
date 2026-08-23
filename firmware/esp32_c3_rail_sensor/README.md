# ESP32-C3 rail sensor firmware

Current sensor module firmware for:

- ESP32-C3 Mini
- MPU-6050
- ADS1115
- GTRIC LR18-08U
- quadrature wheel encoder

The active data path is WiFi WebSocket. USB serial output is diagnostic only.

## Arduino libraries

Install these libraries from Arduino Library Manager:

- Adafruit ADS1X15
- Adafruit MPU6050
- Adafruit Unified Sensor
- ArduinoJson
- WebSockets by Markus Sattler

Select the ESP32-C3 board package supplied by Espressif.

## Configuration

1. Copy `secrets.h.example` to `secrets.h`.
2. Fill in WiFi credentials, sensor token, and the production root CA.
3. Verify every pin in `config.h` against the assembled module.
4. Measure `DIVIDER_TOP_OHM` and `DIVIDER_BOTTOM_OHM`.
5. Set `ENCODER_COUNTS_PER_WHEEL_REV` from the motor gear ratio and measured quadrature count.
6. Keep `ENABLE_LINEAR_DISTANCE_ESTIMATE=false` until the LR18 voltage-to-distance calibration has been measured.

With zero encoder counts per revolution, `position_mm` is transmitted as `null`.
Without calibrated LR18 conversion, `sensor_distance_mm` is transmitted as `null`; raw ADC and voltage fields remain available.

## Sampling and transport

- MPU-6050 sampling: 100 Hz
- ADS1115 sampling: 20 Hz, latest value attached to each IMU sample
- Upload: ten samples per JSON batch, nominally 10 Hz
- Retry: unacknowledged batches remain in a bounded RAM queue
- Overflow: the oldest batch is dropped and `dropped_batches` increments

The server must acknowledge accepted batches:

```json
{"type":"ack","batch_seq":42}
```

WebSocket transport preserves ordering only while connected. Sequence numbers, acknowledgements, and the dropped-batch counter are the source of truth for detecting missing data.

## Hardware validation required

The checked-in pin map and divider values are provisional defaults based on the team guide. Before driving the assembled model:

- verify ESP32-C3 boot-strap and exposed-pin constraints;
- verify common ground and sensor supply voltage;
- measure ADS1115 input at minimum and maximum sensor output;
- confirm that the divider leaves margin below the ADC supply rail;
- calibrate encoder direction and counts per wheel revolution;
- record an I2C scan and a short WebSocket capture.
