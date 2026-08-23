/**
 * ESP32-C3 rail sensor firmware
 *
 * MPU-6050 + ADS1115/LR18-08U + wheel encoder
 * 100 Hz acquisition -> 10-sample JSON batch -> WiFi WebSocket upload
 *
 * Serial is used only for local diagnostics. It is not part of the data path.
 */

#include <Adafruit_ADS1X15.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <ArduinoJson.h>
#include <WebSocketsClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_timer.h>

#include "config.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
constexpr char WIFI_SSID[] = "";
constexpr char WIFI_PASSWORD[] = "";
constexpr char SENSOR_AUTH_TOKEN[] = "";
constexpr char WS_CA_CERT[] = "";
#endif

struct SensorSample {
  uint32_t sampleSeq;
  uint64_t uptimeUs;
  bool positionValid;
  float positionMm;
  bool distanceValid;
  int16_t adcRaw;
  float adcVoltageV;
  float sensorVoltageV;
  float sensorDistanceMm;
  bool imuValid;
  float accelMps2[3];
  float gyroRadps[3];
};

struct PendingBatch {
  uint32_t batchSeq;
  String payload;
  bool sent;
};

Adafruit_ADS1115 ads;
Adafruit_MPU6050 mpu;
WebSocketsClient webSocket;

SensorSample sampleBatch[SAMPLES_PER_BATCH];
size_t sampleCount = 0;
PendingBatch pendingBatches[MAX_PENDING_BATCHES];
size_t pendingCount = 0;

bool adsReady = false;
bool mpuReady = false;
bool wsConfigured = false;
bool wsConnected = false;
uint32_t nextSampleSeq = 1;
uint32_t nextBatchSeq = 1;
uint32_t droppedBatches = 0;
uint64_t lastSampleUs = 0;
uint64_t lastAdcUs = 0;
uint32_t lastWifiAttemptMs = 0;

int16_t latestAdcRaw = 0;
float latestAdcVoltageV = 0.0f;
float latestSensorVoltageV = 0.0f;
float latestSensorDistanceMm = 0.0f;
bool latestDistanceValid = false;

volatile int32_t encoderCount = 0;
volatile uint8_t lastEncoderState = 0;
portMUX_TYPE encoderMux = portMUX_INITIALIZER_UNLOCKED;

String authorizationHeader;

void ARDUINO_ISR_ATTR handleEncoderChange() {
  static constexpr int8_t transitionTable[16] = {
      0, -1, 1, 0,
      1, 0, 0, -1,
      -1, 0, 0, 1,
      0, 1, -1, 0,
  };

  const uint8_t currentState =
      (static_cast<uint8_t>(digitalRead(PIN_ENCODER_A)) << 1) |
      static_cast<uint8_t>(digitalRead(PIN_ENCODER_B));
  const uint8_t transition = (lastEncoderState << 2) | currentState;

  portENTER_CRITICAL_ISR(&encoderMux);
  encoderCount += transitionTable[transition];
  lastEncoderState = currentState;
  portEXIT_CRITICAL_ISR(&encoderMux);
}

int32_t readEncoderCount() {
  portENTER_CRITICAL(&encoderMux);
  const int32_t count = encoderCount;
  portEXIT_CRITICAL(&encoderMux);
  return count;
}

bool encoderPositionMm(float &positionMm) {
  if (ENCODER_COUNTS_PER_WHEEL_REV <= 0.0f) {
    return false;
  }
  const float circumferenceMm = PI * WHEEL_DIAMETER_MM;
  positionMm =
      static_cast<float>(readEncoderCount()) * circumferenceMm /
      ENCODER_COUNTS_PER_WHEEL_REV;
  return true;
}

void updateAdcReading(uint64_t nowUs) {
  if (!adsReady || nowUs - lastAdcUs < ADC_INTERVAL_US) {
    return;
  }
  lastAdcUs = nowUs;

  latestAdcRaw = ads.readADC_SingleEnded(ADS1115_CHANNEL);
  latestAdcVoltageV = ads.computeVolts(latestAdcRaw);
  const float dividerRatio =
      DIVIDER_BOTTOM_OHM / (DIVIDER_TOP_OHM + DIVIDER_BOTTOM_OHM);
  latestSensorVoltageV =
      dividerRatio > 0.0f ? latestAdcVoltageV / dividerRatio : 0.0f;

  latestDistanceValid = false;
  if (ENABLE_LINEAR_DISTANCE_ESTIMATE &&
      SENSOR_OUTPUT_MAX_V > SENSOR_OUTPUT_MIN_V) {
    const float normalized = constrain(
        (latestSensorVoltageV - SENSOR_OUTPUT_MIN_V) /
            (SENSOR_OUTPUT_MAX_V - SENSOR_OUTPUT_MIN_V),
        0.0f, 1.0f);
    latestSensorDistanceMm =
        SENSOR_DISTANCE_MIN_MM +
        normalized * (SENSOR_DISTANCE_MAX_MM - SENSOR_DISTANCE_MIN_MM);
    latestDistanceValid = true;
  }
}

SensorSample captureSample(uint64_t nowUs) {
  SensorSample sample{};
  sample.sampleSeq = nextSampleSeq++;
  sample.uptimeUs = nowUs;
  sample.positionValid = encoderPositionMm(sample.positionMm);

  updateAdcReading(nowUs);
  sample.adcRaw = latestAdcRaw;
  sample.adcVoltageV = latestAdcVoltageV;
  sample.sensorVoltageV = latestSensorVoltageV;
  sample.distanceValid = latestDistanceValid;
  sample.sensorDistanceMm = latestSensorDistanceMm;

  sample.imuValid = mpuReady;
  if (mpuReady) {
    sensors_event_t acceleration;
    sensors_event_t gyro;
    sensors_event_t temperature;
    mpu.getEvent(&acceleration, &gyro, &temperature);

    sample.accelMps2[0] = acceleration.acceleration.x;
    sample.accelMps2[1] = acceleration.acceleration.y;
    sample.accelMps2[2] = acceleration.acceleration.z;
    sample.gyroRadps[0] = gyro.gyro.x;
    sample.gyroRadps[1] = gyro.gyro.y;
    sample.gyroRadps[2] = gyro.gyro.z;
  }
  return sample;
}

String serializeBatch(uint32_t batchSeq) {
  DynamicJsonDocument document(8192);
  document["type"] = "sensor_batch";
  document["schema_version"] = 1;
  document["device_id"] = DEVICE_ID;
  document["rail_side"] = RAIL_SIDE;
  document["firmware_version"] = FIRMWARE_VERSION;
  document["batch_seq"] = batchSeq;
  document["dropped_batches"] = droppedBatches;

  JsonArray samples = document.createNestedArray("samples");
  for (size_t i = 0; i < sampleCount; ++i) {
    const SensorSample &sample = sampleBatch[i];
    JsonObject item = samples.createNestedObject();
    item["sample_seq"] = sample.sampleSeq;
    item["uptime_us"] = sample.uptimeUs;

    if (sample.positionValid) {
      item["position_mm"] = sample.positionMm;
    } else {
      item["position_mm"] = nullptr;
    }

    item["adc_raw"] = sample.adcRaw;
    item["adc_voltage_v"] = sample.adcVoltageV;
    item["sensor_voltage_v"] = sample.sensorVoltageV;
    if (sample.distanceValid) {
      item["sensor_distance_mm"] = sample.sensorDistanceMm;
    } else {
      item["sensor_distance_mm"] = nullptr;
    }

    JsonArray acceleration = item.createNestedArray("accel_mps2");
    JsonArray gyro = item.createNestedArray("gyro_radps");
    if (sample.imuValid) {
      for (size_t axis = 0; axis < 3; ++axis) {
        acceleration.add(sample.accelMps2[axis]);
        gyro.add(sample.gyroRadps[axis]);
      }
    } else {
      for (size_t axis = 0; axis < 3; ++axis) {
        acceleration.add(nullptr);
        gyro.add(nullptr);
      }
    }
  }

  String payload;
  serializeJson(document, payload);
  return payload;
}

void discardOldestPendingBatch() {
  if (pendingCount == 0) {
    return;
  }
  for (size_t i = 1; i < pendingCount; ++i) {
    pendingBatches[i - 1] = pendingBatches[i];
  }
  --pendingCount;
}

void queueBatch() {
  const uint32_t batchSeq = nextBatchSeq++;
  if (pendingCount == MAX_PENDING_BATCHES) {
    discardOldestPendingBatch();
    ++droppedBatches;
  }

  pendingBatches[pendingCount] = {
      batchSeq,
      serializeBatch(batchSeq),
      false,
  };
  ++pendingCount;
  sampleCount = 0;
}

void acknowledgeBatches(uint32_t acknowledgedSeq) {
  size_t removeCount = 0;
  while (removeCount < pendingCount &&
         pendingBatches[removeCount].batchSeq <= acknowledgedSeq) {
    ++removeCount;
  }
  for (size_t i = removeCount; i < pendingCount; ++i) {
    pendingBatches[i - removeCount] = pendingBatches[i];
  }
  pendingCount -= removeCount;
}

void sendHello() {
  DynamicJsonDocument document(512);
  document["type"] = "hello";
  document["schema_version"] = 1;
  document["device_id"] = DEVICE_ID;
  document["rail_side"] = RAIL_SIDE;
  document["firmware_version"] = FIRMWARE_VERSION;
  document["sample_interval_us"] = SAMPLE_INTERVAL_US;
  document["samples_per_batch"] = SAMPLES_PER_BATCH;

  String payload;
  serializeJson(document, payload);
  webSocket.sendTXT(payload);
}

void handleWebSocketEvent(
    WStype_t type, uint8_t *payload, size_t payloadLength) {
  switch (type) {
    case WStype_CONNECTED:
      wsConnected = true;
      for (size_t i = 0; i < pendingCount; ++i) {
        pendingBatches[i].sent = false;
      }
      sendHello();
      Serial.println("[WS] connected");
      break;

    case WStype_DISCONNECTED:
      wsConnected = false;
      Serial.println("[WS] disconnected");
      break;

    case WStype_TEXT: {
      DynamicJsonDocument response(512);
      if (deserializeJson(response, payload, payloadLength) !=
          DeserializationError::Ok) {
        return;
      }
      const char *messageType = response["type"] | "";
      if (strcmp(messageType, "ack") == 0) {
        acknowledgeBatches(response["batch_seq"] | 0U);
      }
      break;
    }

    default:
      break;
  }
}

void flushPendingBatch() {
  if (!wsConnected) {
    return;
  }
  for (size_t i = 0; i < pendingCount; ++i) {
    if (!pendingBatches[i].sent) {
      if (webSocket.sendTXT(pendingBatches[i].payload)) {
        pendingBatches[i].sent = true;
      }
      return;
    }
  }
}

void connectWifiIfNeeded() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  const uint32_t nowMs = millis();
  if (nowMs - lastWifiAttemptMs < WIFI_RETRY_INTERVAL_MS) {
    return;
  }
  lastWifiAttemptMs = nowMs;

  if (strlen(WIFI_SSID) == 0) {
    Serial.println("[WIFI] secrets.h is missing or WIFI_SSID is empty");
    return;
  }

  Serial.printf("[WIFI] connecting to %s\n", WIFI_SSID);
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void configureWebSocket() {
  if (wsConfigured || WiFi.status() != WL_CONNECTED) {
    return;
  }

  authorizationHeader = "Authorization: Bearer ";
  authorizationHeader += SENSOR_AUTH_TOKEN;
  authorizationHeader += "\r\n";
  webSocket.setExtraHeaders(authorizationHeader.c_str());
  webSocket.onEvent(handleWebSocketEvent);
  webSocket.setReconnectInterval(WS_RECONNECT_INTERVAL_MS);
  webSocket.enableHeartbeat(15'000, 3'000, 2);

  if (WS_USE_TLS) {
    if (strlen(WS_CA_CERT) > 0) {
      webSocket.setCACert(WS_CA_CERT);
    }
    webSocket.beginSSL(WS_HOST, WS_PORT, WS_PATH);
  } else {
    webSocket.begin(WS_HOST, WS_PORT, WS_PATH);
  }
  wsConfigured = true;
}

void initializeSensors() {
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);

  adsReady = ads.begin(ADS1115_ADDRESS, &Wire);
  if (adsReady) {
    ads.setGain(GAIN_ONE);
    Serial.println("[SENSOR] ADS1115 ready");
  } else {
    Serial.println("[SENSOR] ADS1115 unavailable");
  }

  mpuReady = mpu.begin(MPU6050_ADDRESS, &Wire);
  if (mpuReady) {
    mpu.setAccelerometerRange(MPU6050_RANGE_16_G);
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_44_HZ);
    Serial.println("[SENSOR] MPU6050 ready");
  } else {
    Serial.println("[SENSOR] MPU6050 unavailable");
  }
}

void initializeEncoder() {
  pinMode(PIN_ENCODER_A, INPUT_PULLUP);
  pinMode(PIN_ENCODER_B, INPUT_PULLUP);
  lastEncoderState =
      (static_cast<uint8_t>(digitalRead(PIN_ENCODER_A)) << 1) |
      static_cast<uint8_t>(digitalRead(PIN_ENCODER_B));
  attachInterrupt(
      digitalPinToInterrupt(PIN_ENCODER_A), handleEncoderChange, CHANGE);
  attachInterrupt(
      digitalPinToInterrupt(PIN_ENCODER_B), handleEncoderChange, CHANGE);
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf(
      "[BOOT] %s firmware=%s rail=%s\n",
      DEVICE_ID,
      FIRMWARE_VERSION,
      RAIL_SIDE);

  initializeSensors();
  initializeEncoder();

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  lastWifiAttemptMs = millis() - WIFI_RETRY_INTERVAL_MS;
  lastSampleUs = esp_timer_get_time();
  lastAdcUs = lastSampleUs - ADC_INTERVAL_US;
}

void loop() {
  connectWifiIfNeeded();
  configureWebSocket();
  if (wsConfigured) {
    webSocket.loop();
  }

  const uint64_t nowUs = esp_timer_get_time();
  if (nowUs - lastSampleUs >= SAMPLE_INTERVAL_US) {
    lastSampleUs += SAMPLE_INTERVAL_US;
    sampleBatch[sampleCount++] = captureSample(nowUs);
    if (sampleCount == SAMPLES_PER_BATCH) {
      queueBatch();
    }
  }

  flushPendingBatch();
  delay(1);
}
