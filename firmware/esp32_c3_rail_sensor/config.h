#pragma once

#include <Arduino.h>

// Hardware pins. Verify these values against the assembled ESP32-C3 Mini module.
constexpr int PIN_I2C_SDA = 8;
constexpr int PIN_I2C_SCL = 9;
constexpr int PIN_ENCODER_A = 6;
constexpr int PIN_ENCODER_B = 7;

constexpr uint8_t ADS1115_ADDRESS = 0x48;
constexpr uint8_t MPU6050_ADDRESS = 0x68;
constexpr uint8_t ADS1115_CHANNEL = 0;

// Acquisition: 100 Hz sampling, 10 samples per WebSocket batch (10 Hz upload).
constexpr uint32_t SAMPLE_INTERVAL_US = 10'000;
constexpr size_t SAMPLES_PER_BATCH = 10;
constexpr uint32_t ADC_INTERVAL_US = 50'000;

// Retry buffer. Oldest unacknowledged batch is discarded only when this is full.
constexpr size_t MAX_PENDING_BATCHES = 24;
constexpr uint32_t WIFI_RETRY_INTERVAL_MS = 5'000;
constexpr uint32_t WS_RECONNECT_INTERVAL_MS = 3'000;

// Wheel/encoder calibration.
constexpr float WHEEL_DIAMETER_MM = 53.0f;
// Set this to the measured quadrature counts per wheel revolution.
// Position is sent as null while this remains zero.
constexpr float ENCODER_COUNTS_PER_WHEEL_REV = 0.0f;

// LR18-08U divider and provisional transfer function.
// Measure the installed resistors and actual voltages before enabling distance conversion.
constexpr float DIVIDER_TOP_OHM = 470'000.0f;
constexpr float DIVIDER_BOTTOM_OHM = 68'000.0f;
constexpr bool ENABLE_LINEAR_DISTANCE_ESTIMATE = false;
constexpr float SENSOR_OUTPUT_MIN_V = 0.0f;
constexpr float SENSOR_OUTPUT_MAX_V = 10.0f;
constexpr float SENSOR_DISTANCE_MIN_MM = 1.0f;
constexpr float SENSOR_DISTANCE_MAX_MM = 8.0f;

constexpr char DEVICE_ID[] = "rail-sensor-01";
constexpr char RAIL_SIDE[] = "left";
constexpr char FIRMWARE_VERSION[] = "0.1.0";

constexpr char WS_HOST[] = "hp028-railtwin.duckdns.org";
constexpr uint16_t WS_PORT = 443;
constexpr char WS_PATH[] = "/ws/sensor";
constexpr bool WS_USE_TLS = true;
