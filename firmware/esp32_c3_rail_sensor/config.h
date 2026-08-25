#pragma once

#include <Arduino.h>

#if __has_include("node_profile.h")
#include "node_profile.h"
#else
#error "Copy node_profile.left.h.example or node_profile.right.h.example to node_profile.h before compiling."
#endif

#if defined(RAIL_NODE_LEFT) && defined(RAIL_NODE_RIGHT)
#error "Select exactly one rail node profile."
#elif !defined(RAIL_NODE_LEFT) && !defined(RAIL_NODE_RIGHT)
#error "node_profile.h must define RAIL_NODE_LEFT or RAIL_NODE_RIGHT."
#endif

static_assert(
    NODE_ENCODER_DIRECTION == 1 || NODE_ENCODER_DIRECTION == -1,
    "NODE_ENCODER_DIRECTION must be 1 or -1.");

// Hardware pins. Verify these values against the assembled ESP32-C3 Mini module.
constexpr int PIN_I2C_SDA = 8;
constexpr int PIN_I2C_SCL = 9;
// Single-channel Hall pulse from the gear motor (no quadrature B line wired).
// Direction is not sensed from hardware; NODE_ENCODER_DIRECTION is trusted as-is.
constexpr int PIN_ENCODER = 3;

// L298N on the drive unit. If the wheel runs backward, set MOTOR_INVERT.
// ENA jumper on the driver must be removed for PWM speed control.
constexpr int PIN_MOTOR_IN1 = 0;
constexpr int PIN_MOTOR_IN2 = 1;
constexpr int PIN_MOTOR_ENA = 4;
constexpr bool MOTOR_INVERT = true;
// Give WiFi/MQTT time to connect before the demo drive starts, so the live
// dashboard is already watching when the motor moves.
constexpr uint32_t MOTOR_START_DELAY_MS = 15'000;
constexpr uint32_t MOTOR_FORWARD_MS = 30'000;
constexpr uint32_t MOTOR_PWM_FREQ_HZ = 5'000;
// Speed unchanged from the 20s run (duty=180); only the run duration was
// extended. DEMO_DRIVE_LENGTH_MM scaled 700mm/20s -> 1050mm/30s to keep the
// same assumed speed for the dashboard's uncalibrated position estimate.
constexpr uint8_t MOTOR_PWM_DUTY = 180;
// Used only while the encoder is uncalibrated, so Godot can track the run.
constexpr float DEMO_DRIVE_LENGTH_MM = 1'050.0f;

constexpr uint8_t ADS1115_ADDRESS = 0x48;
constexpr uint8_t MPU6050_ADDRESS = 0x68;
constexpr uint8_t ADS1115_CHANNEL = 0;

// Acquisition: 100 Hz sampling, 10 samples per MQTT batch (10 Hz upload).
constexpr uint32_t SAMPLE_INTERVAL_US = 10'000;
constexpr size_t SAMPLES_PER_BATCH = 10;
constexpr uint32_t ADC_INTERVAL_US = 50'000;

// Offline retry buffer. Oldest unpublished batch is discarded only when this is full.
constexpr size_t MAX_PENDING_BATCHES = 64;
constexpr uint32_t WIFI_RETRY_INTERVAL_MS = 5'000;

// Shared wheel geometry. Counts, direction and zero offset are node-specific.
constexpr float WHEEL_DIAMETER_MM = 53.0f;

// LR18-08U nominal transfer range. Divider and calibration enable are node-specific.
constexpr float SENSOR_OUTPUT_MIN_V = 0.0f;
constexpr float SENSOR_OUTPUT_MAX_V = 10.0f;
constexpr float SENSOR_DISTANCE_MIN_MM = 1.0f;
constexpr float SENSOR_DISTANCE_MAX_MM = 8.0f;

constexpr char FIRMWARE_VERSION[] = "0.4.0";

// Public NCP endpoint. No hostname/TLS until a new domain is issued.
constexpr char MQTT_HOST[] = "223.130.128.198";
constexpr uint16_t MQTT_PORT = 1883;
constexpr char MQTT_TOPIC_PREFIX[] = "rail/v1/nodes";
constexpr bool MQTT_USE_TLS = false;
constexpr uint8_t MQTT_QOS = 1;
constexpr uint16_t MQTT_KEEPALIVE_SECONDS = 30;
constexpr uint16_t MQTT_MAX_PACKET_BYTES = 12'288;
