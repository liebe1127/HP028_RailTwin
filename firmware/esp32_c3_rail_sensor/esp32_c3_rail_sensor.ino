/**
 * ESP32-C3 rail sensor firmware
 *
 * MPU-6050 + ADS1115/LR18-08U + wheel encoder + L298N demo drive
 * Boot: motor forward while sampling.
 * 세로 충격이 LOCAL_STOP_DYNAMIC_Z를 넘으면 서버와 상관없이 모터를 멈춘다.
 * 서버 명령 토픽 .../command 의 motion=cruise|slow|stop 으로 속도를 바꾼다.
 * 100 Hz acquisition -> 10-sample JSON batch -> WiFi MQTT QoS 1 publish
 *
 * Serial is used only for local diagnostics. It is not part of the data path.
 */

#include <Adafruit_ADS1X15.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <ArduinoJson.h>
#include <ESP32MQTTClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_wifi.h>
#include <esp_attr.h>
#include <esp_system.h>
#include <esp_timer.h>

#include "config.h"
#include "tls_root_ca.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
constexpr char WIFI_SSID[] = "";
constexpr char WIFI_PASSWORD[] = "";
constexpr char MQTT_PASSWORD[] = "";
#endif

struct SensorSample {
  uint32_t sampleSeq;
  uint64_t uptimeUs;
  bool positionValid;
  float positionMm;
  bool adcValid;
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
};

Adafruit_ADS1115 ads;
Adafruit_MPU6050 mpu;
ESP32MQTTClient mqttClient;

SensorSample sampleBatch[SAMPLES_PER_BATCH];
size_t sampleCount = 0;
PendingBatch pendingBatches[MAX_PENDING_BATCHES];
size_t pendingCount = 0;

bool adsReady = false;
bool mpuReady = false;
bool mqttConfigured = false;
uint32_t nextSampleSeq = 1;
uint32_t nextBatchSeq = 1;
uint32_t droppedBatches = 0;
uint64_t lastSampleUs = 0;
uint64_t lastAdcUs = 0;
uint32_t lastWifiAttemptMs = 0;
bool wifiJoinLogged = false;
bool motorRunning = false;
uint32_t motorStartedMs = 0;
volatile bool localStopLatched = false;
volatile uint8_t pendingMotion = 0;
volatile bool motionPending = false;

int16_t latestAdcRaw = 0;
float latestAdcVoltageV = 0.0f;
float latestSensorVoltageV = 0.0f;
float latestSensorDistanceMm = 0.0f;
bool latestDistanceValid = false;

volatile int32_t encoderCount = 0;
portMUX_TYPE encoderMux = portMUX_INITIALIZER_UNLOCKED;

char bootId[9] = "";
String mqttBrokerUri;
String mqttTelemetryTopic;
String mqttStatusTopic;
String mqttCommandTopic;
String mqttOnlinePayload;
String mqttOfflinePayload;

constexpr uint32_t STATUS_MPU_UNAVAILABLE = 1U << 0;
constexpr uint32_t STATUS_ADS_UNAVAILABLE = 1U << 1;
constexpr uint32_t STATUS_ENCODER_UNCALIBRATED = 1U << 2;
constexpr uint32_t STATUS_DISTANCE_UNCALIBRATED = 1U << 3;
uint32_t currentStatusFlags() {
  uint32_t flags = 0;
  if (!mpuReady) {
    flags |= STATUS_MPU_UNAVAILABLE;
  }
  if (!adsReady) {
    flags |= STATUS_ADS_UNAVAILABLE;
  }
  if (NODE_ENCODER_COUNTS_PER_WHEEL_REV <= 0.0f) {
    flags |= STATUS_ENCODER_UNCALIBRATED;
  }
  if (!NODE_ENABLE_LINEAR_DISTANCE_ESTIMATE) {
    flags |= STATUS_DISTANCE_UNCALIBRATED;
  }
  return flags;
}

void ARDUINO_ISR_ATTR handleEncoderPulse() {
  portENTER_CRITICAL_ISR(&encoderMux);
  encoderCount += 1;
  portEXIT_CRITICAL_ISR(&encoderMux);
}

int32_t readEncoderCount() {
  portENTER_CRITICAL(&encoderMux);
  const int32_t count = encoderCount;
  portEXIT_CRITICAL(&encoderMux);
  return count;
}

bool encoderPositionMm(float &positionMm) {
  if (NODE_ENCODER_COUNTS_PER_WHEEL_REV > 0.0f) {
    const float circumferenceMm = PI * WHEEL_DIAMETER_MM;
    positionMm =
        NODE_POSITION_ZERO_OFFSET_MM +
        static_cast<float>(
            readEncoderCount() * NODE_ENCODER_DIRECTION) *
            circumferenceMm /
            NODE_ENCODER_COUNTS_PER_WHEEL_REV;
    return true;
  }
  if (motorStartedMs == 0 || DEMO_DRIVE_LENGTH_MM <= 0.0f) {
    return false;
  }
  uint32_t elapsedMs = millis() - motorStartedMs;
  if (elapsedMs > MOTOR_FORWARD_MS) {
    elapsedMs = MOTOR_FORWARD_MS;
  }
  positionMm =
      NODE_POSITION_ZERO_OFFSET_MM +
      DEMO_DRIVE_LENGTH_MM * static_cast<float>(elapsedMs) /
          static_cast<float>(MOTOR_FORWARD_MS);
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
      NODE_DIVIDER_BOTTOM_OHM /
      (NODE_DIVIDER_TOP_OHM + NODE_DIVIDER_BOTTOM_OHM);
  latestSensorVoltageV =
      dividerRatio > 0.0f ? latestAdcVoltageV / dividerRatio : 0.0f;

  latestDistanceValid = false;
  if (SENSOR_OUTPUT_MAX_V > SENSOR_OUTPUT_MIN_V) {
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
  sample.adcValid = adsReady;
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
  document["boot_id"] = bootId;
  document["firmware_version"] = FIRMWARE_VERSION;
  document["batch_seq"] = batchSeq;
  document["dropped_batches"] = droppedBatches;
  document["status_flags"] = currentStatusFlags();

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

    if (sample.adcValid) {
      item["adc_raw"] = sample.adcRaw;
      item["adc_voltage_v"] = sample.adcVoltageV;
      item["sensor_voltage_v"] = sample.sensorVoltageV;
    } else {
      item["adc_raw"] = nullptr;
      item["adc_voltage_v"] = nullptr;
      item["sensor_voltage_v"] = nullptr;
    }
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
  };
  ++pendingCount;
  sampleCount = 0;
}

String buildNodeStatusPayload(const char *status) {
  DynamicJsonDocument document(512);
  document["type"] = "node_status";
  document["schema_version"] = 1;
  document["device_id"] = DEVICE_ID;
  document["rail_side"] = RAIL_SIDE;
  document["boot_id"] = bootId;
  document["firmware_version"] = FIRMWARE_VERSION;
  document["status"] = status;
  document["status_flags"] = currentStatusFlags();
  String payload;
  serializeJson(document, payload);
  return payload;
}

void onMotionCommand(const std::string &topic, const std::string &payload);

void onMqttConnect(esp_mqtt_client_handle_t client) {
  mqttClient.publish(
      mqttStatusTopic.c_str(),
      mqttOnlinePayload.c_str(),
      MQTT_QOS,
      true);
  mqttClient.subscribe(mqttCommandTopic.c_str(), onMotionCommand, MQTT_QOS);
  Serial.println("[MQTT] connected");
}

void onMotionCommand(const std::string &topic, const std::string &payload) {
  (void)topic;
  DynamicJsonDocument document(192);
  if (deserializeJson(document, payload) != DeserializationError::Ok) {
    return;
  }
  const char *motion = document["motion"] | "";
  if (strcmp(motion, "stop") == 0) {
    pendingMotion = 2;
  } else if (strcmp(motion, "slow") == 0) {
    pendingMotion = 1;
  } else if (strcmp(motion, "cruise") == 0) {
    pendingMotion = 0;
  } else {
    return;
  }
  motionPending = true;
}

#if ESP_IDF_VERSION < ESP_IDF_VERSION_VAL(5, 0, 0)
esp_err_t handleMQTT(esp_mqtt_event_handle_t event) {
  mqttClient.onEventCallback(event);
  return ESP_OK;
}
#else
void handleMQTT(
    void *handlerArgs,
    esp_event_base_t base,
    int32_t eventId,
    void *eventData) {
  auto *event = static_cast<esp_mqtt_event_handle_t>(eventData);
  mqttClient.onEventCallback(event);
}
#endif

void flushPendingBatch() {
  if (!mqttClient.isConnected() || pendingCount == 0) {
    return;
  }
  const uint32_t batchSeq = pendingBatches[0].batchSeq;
  if (mqttClient.publish(
          mqttTelemetryTopic.c_str(),
          pendingBatches[0].payload.c_str(),
          MQTT_QOS,
          false)) {
    discardOldestPendingBatch();
    Serial.printf("[MQTT] queued QoS1 batch=%lu\n",
                  static_cast<unsigned long>(batchSeq));
  }
}

void onWifiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_CONNECTED:
      Serial.println("[WIFI] associated");
      break;
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      Serial.printf("[WIFI] got ip=%s\n", WiFi.localIP().toString().c_str());
      break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      wifiJoinLogged = false;
      Serial.printf(
          "[WIFI] disconnected reason=%u\n",
          static_cast<unsigned>(info.wifi_sta_disconnected.reason));
      break;
    default:
      break;
  }
}

void configureC3StaRadio() {
  wifi_country_t country = {};
  country.cc[0] = 'K';
  country.cc[1] = 'R';
  country.schan = 1;
  country.nchan = 13;
  country.policy = WIFI_COUNTRY_POLICY_MANUAL;
  esp_wifi_set_country(&country);
  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_protocol(
      WIFI_IF_STA,
      WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N);
  esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20);
}

void connectWifiIfNeeded() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiJoinLogged) {
      Serial.printf(
          "[WIFI] connected ip=%s rssi=%d\n",
          WiFi.localIP().toString().c_str(),
          WiFi.RSSI());
      wifiJoinLogged = true;
    }
    return;
  }
  wifiJoinLogged = false;

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

void configureMqtt() {
  if (mqttConfigured || WiFi.status() != WL_CONNECTED) {
    return;
  }
  if (strlen(MQTT_PASSWORD) == 0) {
    Serial.println("[MQTT] MQTT_PASSWORD is empty");
    return;
  }
  if (MQTT_USE_TLS && strlen(WS_CA_CERT) == 0) {
    Serial.println("[MQTT] root CA is required for TLS");
    return;
  }

  mqttBrokerUri = MQTT_USE_TLS ? "mqtts://" : "mqtt://";
  mqttBrokerUri += MQTT_HOST;
  mqttBrokerUri += ":";
  mqttBrokerUri += MQTT_PORT;
  mqttTelemetryTopic = MQTT_TOPIC_PREFIX;
  mqttTelemetryTopic += "/";
  mqttTelemetryTopic += DEVICE_ID;
  mqttTelemetryTopic += "/telemetry";
  mqttStatusTopic = MQTT_TOPIC_PREFIX;
  mqttStatusTopic += "/";
  mqttStatusTopic += DEVICE_ID;
  mqttStatusTopic += "/status";
  mqttCommandTopic = MQTT_TOPIC_PREFIX;
  mqttCommandTopic += "/";
  mqttCommandTopic += DEVICE_ID;
  mqttCommandTopic += "/command";
  mqttOnlinePayload = buildNodeStatusPayload("online");
  mqttOfflinePayload = buildNodeStatusPayload("offline");

  mqttClient.setURI(mqttBrokerUri.c_str(), DEVICE_ID, MQTT_PASSWORD);
  mqttClient.setMqttClientName(DEVICE_ID);
  mqttClient.setKeepAlive(MQTT_KEEPALIVE_SECONDS);
  mqttClient.setMaxPacketSize(MQTT_MAX_PACKET_BYTES);
  mqttClient.setMaxOutPacketSize(MQTT_MAX_PACKET_BYTES);
  mqttClient.enablePersistence();
  mqttClient.enableLastWillMessage(
      mqttStatusTopic.c_str(),
      mqttOfflinePayload.c_str(),
      true,
      MQTT_QOS);
  mqttClient.setAutoReconnect(true);
  if (MQTT_USE_TLS) {
    mqttClient.setCaCert(WS_CA_CERT);
  }
  mqttConfigured = mqttClient.loopStart();
  if (!mqttConfigured) {
    Serial.println("[MQTT] client start failed");
  }
}

void stopMotor() {
  digitalWrite(PIN_MOTOR_IN1, LOW);
  digitalWrite(PIN_MOTOR_IN2, LOW);
  ledcWrite(PIN_MOTOR_ENA, 0);
  if (motorRunning) {
    Serial.println("[MOTOR] stop");
    motorRunning = false;
  }
}

void startMotorForward() {
  digitalWrite(PIN_MOTOR_IN1, MOTOR_INVERT ? LOW : HIGH);
  digitalWrite(PIN_MOTOR_IN2, MOTOR_INVERT ? HIGH : LOW);
  ledcWrite(PIN_MOTOR_ENA, MOTOR_PWM_DUTY);
  motorRunning = true;
  motorStartedMs = millis();
  Serial.printf(
      "[MOTOR] forward %lus duty=%u\n",
      static_cast<unsigned long>(MOTOR_FORWARD_MS / 1000),
      static_cast<unsigned>(MOTOR_PWM_DUTY));
}

void applyPendingMotion() {
  if (localStopLatched) {
    if (motorRunning) {
      stopMotor();
    }
    return;
  }
  if (!motionPending || !motorRunning) {
    return;
  }
  motionPending = false;
  const uint8_t motion = pendingMotion;
  if (motion == 2) {
    stopMotor();
    return;
  }
  ledcWrite(PIN_MOTOR_ENA, motion == 1 ? MOTOR_SLOW_DUTY : MOTOR_PWM_DUTY);
}

void noteLocalSafety(const SensorSample &sample) {
  if (!sample.imuValid || localStopLatched) {
    return;
  }
  const float dynamicZ = fabsf(sample.accelMps2[2] - 9.80665f);
  if (dynamicZ < LOCAL_STOP_DYNAMIC_Z) {
    return;
  }
  localStopLatched = true;
  stopMotor();
  Serial.printf("[MOTOR] local safety stop az=%.2f\n", dynamicZ);
}

void updateMotor() {
  applyPendingMotion();
  if (localStopLatched) {
    return;
  }
  if (!motorRunning) {
    if (motorStartedMs == 0 && millis() >= MOTOR_START_DELAY_MS) {
      startMotorForward();
    }
    return;
  }
  if (millis() - motorStartedMs >= MOTOR_FORWARD_MS) {
    stopMotor();
  }
}

void initializeMotor() {
  pinMode(PIN_MOTOR_IN1, OUTPUT);
  pinMode(PIN_MOTOR_IN2, OUTPUT);
  ledcAttach(PIN_MOTOR_ENA, MOTOR_PWM_FREQ_HZ, 8);
  digitalWrite(PIN_MOTOR_IN1, LOW);
  digitalWrite(PIN_MOTOR_IN2, LOW);
  ledcWrite(PIN_MOTOR_ENA, 0);
}

void initializeSensors() {
  Serial.println("[SENSOR] i2c begin");
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setTimeOut(20);
  Serial.println("[SENSOR] i2c ready");

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
  pinMode(PIN_ENCODER, INPUT_PULLUP);
  attachInterrupt(
      digitalPinToInterrupt(PIN_ENCODER), handleEncoderPulse, RISING);
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("[BOOT] serial-ready");
  snprintf(
      bootId,
      sizeof(bootId),
      "%08lx",
      static_cast<unsigned long>(esp_random()));
  Serial.printf(
      "[BOOT] %s firmware=%s rail=%s boot=%s\n",
      DEVICE_ID,
      FIRMWARE_VERSION,
      RAIL_SIDE,
      bootId);

  initializeSensors();
  initializeEncoder();
  initializeMotor();

  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  configureC3StaRadio();
  WiFi.onEvent(onWifiEvent);
  WiFi.setAutoReconnect(true);
  lastWifiAttemptMs = millis() - WIFI_RETRY_INTERVAL_MS;
  lastSampleUs = esp_timer_get_time();
  lastAdcUs = lastSampleUs - ADC_INTERVAL_US;
}

void loop() {
  updateMotor();
  connectWifiIfNeeded();
  configureMqtt();

  const uint64_t nowUs = esp_timer_get_time();
  if (nowUs - lastSampleUs >= SAMPLE_INTERVAL_US) {
    lastSampleUs += SAMPLE_INTERVAL_US;
    SensorSample sample = captureSample(nowUs);
    noteLocalSafety(sample);
    sampleBatch[sampleCount++] = sample;
    if (sampleCount == SAMPLES_PER_BATCH) {
      queueBatch();
    }
  }

  flushPendingBatch();
  delay(1);
}
