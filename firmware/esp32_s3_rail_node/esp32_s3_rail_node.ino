/* ============================================================
   HP028 실물 펌웨어 초안. ESP32-S3-DevKitC-1 한 장.

   하는 일
   - 좌·우 간격, 가속도 3축, 자이로 3축, 온도, 바퀴 위치를 같은 시각에 읽는다
   - 주행 중일 때만 서버 JSON 배치를 보낸다. 멈춰 있으면 연결만 유지한다
   - 평속·감속·정지는 서버 명령을 따른다
   - 세로 충격이 크면 서버 명령과 상관없이 바퀴를 멈춘다
   - 멈춰 있을 때의 간격 잡음은 평균으로 눌러 보낸다

   하지 않는 일
   - 이음부 단차·수직 변형·좌우 높이차 판정. 그건 서버가 한다

   secrets.h 가 없으면 USB 글자만 출력하고 와이파이는 켜지 않는다.
   시리얼 115200, 줄 바꿈 없음.
   g 전진 평속    s 전진 감속    b 후진 평속    0 정지
   z 위치 0      c 충격 정지 해제    r 한 줄 읽기
   BOOT 버튼: 전진 80초 후 정지. 가는 중에 다시 누르면 즉시 정지.
   ============================================================ */

#include <WiFi.h>
#include <Wire.h>
#include <esp_random.h>
#include <esp_timer.h>
#include "config.h"

#if __has_include("secrets.h")
#include "secrets.h"
#define MQTT_ENABLED 1
#include <MQTT.h>
#else
#define MQTT_ENABLED 0
#endif

TwoWire &busL = Wire;
TwoWire &busR = Wire1;

volatile long encL = 0;
volatile long encR = 0;

enum Motion { MOTION_CRUISE, MOTION_SLOW, MOTION_STOP };
Motion motionL = MOTION_STOP;
Motion motionR = MOTION_STOP;
int driveSign = 1;  // +1 전진(빨간 기판 쪽), -1 후진
bool shockLatch = false;
uint32_t runUntilMs = 0;
uint32_t bootEdgeMs = 0;
volatile bool bootFlag = false;

bool mpuOkL = false;
bool mpuOkR = false;
bool adsOkL = false;
bool adsOkR = false;

float gapMeanL = NAN;
float gapMeanR = NAN;

char bootId[9] = "00000000";
uint32_t sampleSeq = 0;
uint32_t batchSeqL = 0;
uint32_t batchSeqR = 0;
uint32_t droppedL = 0;
uint32_t droppedR = 0;

struct Pair {
  int64_t us;
  float posL, posR, gapL, gapR;
  int16_t rawL, rawR;
  float pinL, pinR, sensL, sensR;
  float axL, ayL, azL, axR, ayR, azR;
  float gxL, gyL, gzL, gxR, gyR, gzR;
  float tempL, tempR;
  bool okAdsL, okAdsR, okMpuL, okMpuR;
};

Pair batch[SAMPLES_PER_BATCH];
int batchCount = 0;

bool adsPending = false;
uint32_t adsStartedUs = 0;
int16_t lastRawL = 0;
int16_t lastRawR = 0;
bool haveRawL = false;
bool haveRawR = false;

#if MQTT_ENABLED
WiFiClient netL;
WiFiClient netR;
MQTTClient mqttL(4096);
MQTTClient mqttR(4096);
bool mqttStarted = false;
char lwtL[360];
char lwtR[360];
#endif

void IRAM_ATTR isrL() { encL += digitalRead(ENCB_L) ? 1 : -1; }
void IRAM_ATTR isrR() { encR += digitalRead(ENCB_R) ? 1 : -1; }
void IRAM_ATTR isrBoot() { bootFlag = true; }

bool i2cWrite8(TwoWire &w, uint8_t addr, uint8_t reg, uint8_t val) {
  w.beginTransmission(addr);
  w.write(reg);
  w.write(val);
  return w.endTransmission() == 0;
}

bool i2cWrite16(TwoWire &w, uint8_t addr, uint8_t reg, uint16_t val) {
  w.beginTransmission(addr);
  w.write(reg);
  w.write(val >> 8);
  w.write(val & 0xFF);
  return w.endTransmission() == 0;
}

bool i2cRead(TwoWire &w, uint8_t addr, uint8_t reg, uint8_t *buf, uint8_t n) {
  w.beginTransmission(addr);
  w.write(reg);
  if (w.endTransmission(false) != 0) return false;
  if (w.requestFrom((int)addr, (int)n) != n) return false;
  for (uint8_t i = 0; i < n; i++) buf[i] = w.read();
  return true;
}

int16_t be16(const uint8_t *b) { return (int16_t)((b[0] << 8) | b[1]); }

bool mpuInit(TwoWire &w) {
  if (!i2cWrite8(w, MPU_ADDR, 0x6B, 0x00)) return false;
  delay(10);
  i2cWrite8(w, MPU_ADDR, 0x1C, 0x00);  // 가속도 ±2g
  i2cWrite8(w, MPU_ADDR, 0x1B, 0x00);  // 자이로 ±250 deg/s
  i2cWrite8(w, MPU_ADDR, 0x1A, 0x03);  // 44Hz
  return true;
}

// 0x3B부터 14바이트: 가속도 6, 온도 2, 자이로 6.
bool mpuRead(TwoWire &w, float &ax, float &ay, float &az, float &gx, float &gy, float &gz, float &tempC) {
  uint8_t b[14];
  if (!i2cRead(w, MPU_ADDR, 0x3B, b, 14)) return false;
  ax = be16(b) / 16384.0f * G_TO_MPS2;
  ay = be16(b + 2) / 16384.0f * G_TO_MPS2;
  az = be16(b + 4) / 16384.0f * G_TO_MPS2;
  tempC = be16(b + 6) / TEMP_LSB_PER_C + TEMP_OFFSET_C;
  float dpsToRad = MPU_DEG_TO_RAD / GYRO_LSB_PER_DPS;
  gx = be16(b + 8) * dpsToRad;
  gy = be16(b + 10) * dpsToRad;
  gz = be16(b + 12) * dpsToRad;
  return true;
}

bool adsStart(TwoWire &w) { return i2cWrite16(w, ADS_ADDR, 0x01, ADS_CFG); }

bool adsReadRaw(TwoWire &w, int16_t &raw) {
  uint8_t cfg[2];
  if (!i2cRead(w, ADS_ADDR, 0x01, cfg, 2)) return false;
  if ((cfg[0] & 0x80) == 0) return false;  // 변환이 아직 안 끝남
  uint8_t b[2];
  if (!i2cRead(w, ADS_ADDR, 0x00, b, 2)) return false;
  raw = (int16_t)((b[0] << 8) | b[1]);
  return true;
}

float gapMM(float sensorVolt, bool left) {
  const float *cv = left ? CAL_VL : CAL_VR;
  if (sensorVolt <= cv[0]) return CAL_MM[0];
  for (int i = 1; i < CAL_N; i++) {
    if (sensorVolt <= cv[i]) {
      return CAL_MM[i - 1] + (sensorVolt - cv[i - 1]) * (CAL_MM[i] - CAL_MM[i - 1]) / (cv[i] - cv[i - 1]);
    }
  }
  int k = CAL_N - 1;
  return CAL_MM[k] + (sensorVolt - cv[k]) * (CAL_MM[k] - CAL_MM[k - 1]) / (cv[k] - cv[k - 1]);
}

float holdGap(float &mean, float sample, bool moving) {
  if (isnan(mean) || moving) mean = sample;
  else mean = mean * 0.9f + sample * 0.1f;
  return mean;
}

void motorStop() {
  analogWrite(ENA_L, 0);
  digitalWrite(IN1_L, LOW);
  digitalWrite(IN2_L, LOW);
  analogWrite(ENA_R, 0);
  digitalWrite(IN1_R, LOW);
  digitalWrite(IN2_R, LOW);
}

void motorApply(int sign, uint8_t duty) {
  bool fwd = sign > 0;
  digitalWrite(IN1_L, fwd);
  digitalWrite(IN2_L, !fwd);
  digitalWrite(IN1_R, fwd);
  digitalWrite(IN2_R, !fwd);
  analogWrite(ENA_L, duty);
  analogWrite(ENA_R, duty);
}

Motion parseMotion(const String &body) {
  if (body.indexOf("stop") >= 0) return MOTION_STOP;
  if (body.indexOf("slow") >= 0) return MOTION_SLOW;
  if (body.indexOf("cruise") >= 0) return MOTION_CRUISE;
  return MOTION_STOP;
}

int motionRank(Motion m) { return m == MOTION_STOP ? 2 : (m == MOTION_SLOW ? 1 : 0); }

Motion effectiveMotion() {
  return motionRank(motionL) >= motionRank(motionR) ? motionL : motionR;
}

bool runActive() { return effectiveMotion() != MOTION_STOP; }

const char *motionName(Motion m) {
  if (m == MOTION_CRUISE) return "cruise";
  if (m == MOTION_SLOW) return "slow";
  return "stop";
}

void applyDrive() {
  if (shockLatch) {
    motorStop();
    return;
  }
  Motion m = effectiveMotion();
  if (m == MOTION_STOP) {
    motorStop();
    return;
  }
  motorApply(driveSign, m == MOTION_CRUISE ? DUTY_CRUISE : DUTY_SLOW);
}

long readEnc(volatile long &enc) {
  noInterrupts();
  long v = enc;
  interrupts();
  return v;
}

void zeroEncoders() {
  noInterrupts();
  encL = 0;
  encR = 0;
  interrupts();
}

#if MQTT_ENABLED
void onCommand(String &topic, String &body) {
  if (body.indexOf("zero") >= 0) {
    zeroEncoders();
    Serial.println("위치 0");
    return;
  }
  Motion m = parseMotion(body);
  if (topic.indexOf(DEVICE_L) >= 0) motionL = m;
  else if (topic.indexOf(DEVICE_R) >= 0) motionR = m;
  Serial.printf("명령 %s  →  적용 %s\n", body.c_str(), motionName(effectiveMotion()));
}

void fillLwt(char *dst, size_t n, const char *device, const char *side) {
  snprintf(dst, n,
           "{\"type\":\"node_status\",\"schema_version\":1,\"device_id\":\"%s\","
           "\"rail_side\":\"%s\",\"boot_id\":\"%s\",\"firmware_version\":\"%s\","
           "\"status\":\"offline\",\"status_flags\":0}",
           device, side, bootId, FIRMWARE_VERSION);
}

void startMqtt() {
  fillLwt(lwtL, sizeof lwtL, DEVICE_L, "left");
  fillLwt(lwtR, sizeof lwtR, DEVICE_R, "right");
  mqttL.begin(MQTT_HOST, MQTT_PORT, netL);
  mqttR.begin(MQTT_HOST, MQTT_PORT, netR);
  mqttL.onMessage(onCommand);
  mqttR.onMessage(onCommand);
  mqttL.setKeepAlive(30);
  mqttR.setKeepAlive(30);
  mqttL.setTimeout(300);
  mqttR.setTimeout(300);
  mqttL.setWill(TOPIC_STA_L, lwtL, true, 1);
  mqttR.setWill(TOPIC_STA_R, lwtR, true, 1);
  mqttStarted = true;
}

void publishOnline(MQTTClient &client, const char *topic, const char *device, const char *side) {
  char body[360];
  snprintf(body, sizeof body,
           "{\"type\":\"node_status\",\"schema_version\":1,\"device_id\":\"%s\","
           "\"rail_side\":\"%s\",\"boot_id\":\"%s\",\"firmware_version\":\"%s\","
           "\"status\":\"online\",\"status_flags\":0}",
           device, side, bootId, FIRMWARE_VERSION);
  client.publish(topic, body, true, 1);
}

void connectOne(MQTTClient &client, WiFiClient &net, const char *device, const char *pass,
                const char *cmdTopic, const char *staTopic, const char *side) {
  if (client.connected()) return;
  net.stop();
  if (!client.connect(device, device, pass)) return;
  client.subscribe(cmdTopic, 1);
  publishOnline(client, staTopic, device, side);
  Serial.printf("MQTT %s 연결\n", side);
}

void serviceMqtt() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (!mqttStarted) startMqtt();
  mqttL.loop();
  mqttR.loop();
  static uint32_t nextTry = 0;
  if (mqttL.connected() && mqttR.connected()) return;
  if (millis() < nextTry) return;
  nextTry = millis() + 3000;
  connectOne(mqttL, netL, DEVICE_L, MQTT_LEFT_PASSWORD, TOPIC_CMD_L, TOPIC_STA_L, "left");
  connectOne(mqttR, netR, DEVICE_R, MQTT_RIGHT_PASSWORD, TOPIC_CMD_R, TOPIC_STA_R, "right");
}
#endif

int statusFlags(bool mpuOk, bool adsOk) {
  int flags = 0;
  if (!mpuOk) flags |= 1;
  if (!adsOk) flags |= 2;
  if (shockLatch) flags |= 4;
  return flags;
}

bool publishSide(bool left) {
  char body[4096];
  int n = snprintf(body, sizeof body,
                   "{\"type\":\"sensor_batch\",\"schema_version\":1,\"device_id\":\"%s\","
                   "\"rail_side\":\"%s\",\"boot_id\":\"%s\",\"firmware_version\":\"%s\","
                   "\"batch_seq\":%lu,\"dropped_batches\":%lu,\"status_flags\":%d,\"samples\":[",
                   left ? DEVICE_L : DEVICE_R,
                   left ? "left" : "right",
                   bootId,
                   FIRMWARE_VERSION,
                   (unsigned long)(left ? batchSeqL : batchSeqR),
                   (unsigned long)(left ? droppedL : droppedR),
                   statusFlags(left ? mpuOkL : mpuOkR, left ? adsOkL : adsOkR));
  if (n < 0 || n >= (int)sizeof body) return false;

  for (int i = 0; i < batchCount; i++) {
    const Pair &p = batch[i];
    bool okAds = left ? p.okAdsL : p.okAdsR;
    bool okMpu = left ? p.okMpuL : p.okMpuR;
    float pos = left ? p.posL : p.posR;
    float gap = left ? p.gapL : p.gapR;
    int16_t raw = left ? p.rawL : p.rawR;
    float pin = left ? p.pinL : p.pinR;
    float sens = left ? p.sensL : p.sensR;
    float ax = left ? p.axL : p.axR;
    float ay = left ? p.ayL : p.ayR;
    float az = left ? p.azL : p.azR;
    float gx = left ? p.gxL : p.gxR;
    float gy = left ? p.gyL : p.gyR;
    float gz = left ? p.gzL : p.gzR;
    float tempC = left ? p.tempL : p.tempR;
    char gapTxt[16];
    char tempTxt[16];
    if (okAds) snprintf(gapTxt, sizeof gapTxt, "%.3f", gap);
    else snprintf(gapTxt, sizeof gapTxt, "null");
    if (okMpu) snprintf(tempTxt, sizeof tempTxt, "%.2f", tempC);
    else snprintf(tempTxt, sizeof tempTxt, "null");
    int wrote = snprintf(body + n, sizeof body - n,
                         "%s{\"sample_seq\":%lu,\"uptime_us\":%lld,\"position_mm\":%.2f,"
                         "\"sensor_distance_mm\":%s,\"adc_raw\":%d,\"adc_voltage_v\":%.3f,"
                         "\"sensor_voltage_v\":%.3f,\"accel_mps2\":[%.3f,%.3f,%.3f],"
                         "\"gyro_radps\":[%.4f,%.4f,%.4f],\"temp_c\":%s}",
                         i ? "," : "",
                         (unsigned long)(sampleSeq - batchCount + 1 + i),
                         (long long)p.us,
                         pos,
                         gapTxt,
                         raw,
                         pin,
                         sens,
                         okMpu ? ax : 0.0f,
                         okMpu ? ay : 0.0f,
                         okMpu ? az : 0.0f,
                         okMpu ? gx : 0.0f,
                         okMpu ? gy : 0.0f,
                         okMpu ? gz : 0.0f,
                         tempTxt);
    if (wrote < 0 || n + wrote >= (int)sizeof body) return false;
    n += wrote;
  }
  if (n + 3 >= (int)sizeof body) return false;
  body[n++] = ']';
  body[n++] = '}';
  body[n] = 0;

  Serial.println(body);
#if MQTT_ENABLED
  if (!mqttStarted) return true;
  MQTTClient &client = left ? mqttL : mqttR;
  const char *topic = left ? TOPIC_TEL_L : TOPIC_TEL_R;
  if (!client.connected()) return false;
  return client.publish(topic, body, false, 1);
#else
  return true;
#endif
}

void flushBatch() {
  if (batchCount == 0) return;
  batchSeqL++;
  batchSeqR++;
  if (!publishSide(true)) droppedL++;
  if (!publishSide(false)) droppedR++;
  batchCount = 0;
}

void takeSample() {
  if (!runActive()) {
    if (batchCount > 0) flushBatch();
    return;
  }
  long cL = readEnc(encL);
  long cR = readEnc(encR);
  static long prevL = 0;
  static long prevR = 0;
  bool moving = (cL != prevL) || (cR != prevR);
  prevL = cL;
  prevR = cR;

  float axL, ayL, azL, gxL, gyL, gzL, tempL;
  float axR, ayR, azR, gxR, gyR, gzR, tempR;
  bool okL = mpuOkL && mpuRead(busL, axL, ayL, azL, gxL, gyL, gzL, tempL);
  bool okR = mpuOkR && mpuRead(busR, axR, ayR, azR, gxR, gyR, gzR, tempR);
  if (okL && fabsf((azL / G_TO_MPS2) - Z_OFFSET_L_G) * G_TO_MPS2 > SHOCK_MPS2) shockLatch = true;
  if (okR && fabsf((azR / G_TO_MPS2) - Z_OFFSET_R_G) * G_TO_MPS2 > SHOCK_MPS2) shockLatch = true;

  float pinL = haveRawL ? lastRawL * ADS_LSB : 0;
  float pinR = haveRawR ? lastRawR * ADS_LSB : 0;
  float sensL = pinL * DIV;
  float sensR = pinR * DIV;
  float gapL = haveRawL ? holdGap(gapMeanL, gapMM(sensL, true), moving) : 0;
  float gapR = haveRawR ? holdGap(gapMeanR, gapMM(sensR, false), moving) : 0;

  if (batchCount >= SAMPLES_PER_BATCH) flushBatch();
  Pair &p = batch[batchCount++];
  sampleSeq++;
  p.us = esp_timer_get_time();
  p.posL = POS_SIGN_L * cL * MM_PER_COUNT;
  p.posR = POS_SIGN_R * cR * MM_PER_COUNT;
  p.gapL = gapL;
  p.gapR = gapR;
  p.rawL = lastRawL;
  p.rawR = lastRawR;
  p.pinL = pinL;
  p.pinR = pinR;
  p.sensL = sensL;
  p.sensR = sensR;
  p.axL = okL ? axL : 0;
  p.ayL = okL ? ayL : 0;
  p.azL = okL ? azL : 0;
  p.gxL = okL ? gxL : 0;
  p.gyL = okL ? gyL : 0;
  p.gzL = okL ? gzL : 0;
  p.tempL = okL ? tempL : 0;
  p.axR = okR ? axR : 0;
  p.ayR = okR ? ayR : 0;
  p.azR = okR ? azR : 0;
  p.gxR = okR ? gxR : 0;
  p.gyR = okR ? gyR : 0;
  p.gzR = okR ? gzR : 0;
  p.tempR = okR ? tempR : 0;
  p.okAdsL = haveRawL;
  p.okAdsR = haveRawR;
  p.okMpuL = okL;
  p.okMpuR = okR;
  if (batchCount >= SAMPLES_PER_BATCH) flushBatch();
}

void serviceAds() {
  uint32_t now = micros();
  if (!adsPending) {
    adsOkL = adsStart(busL);
    adsOkR = adsStart(busR);
    adsPending = adsOkL || adsOkR;
    adsStartedUs = now;
    return;
  }
  if ((uint32_t)(now - adsStartedUs) < ADS_WAIT_US) return;
  int16_t raw;
  if (adsOkL && adsReadRaw(busL, raw)) {
    lastRawL = raw;
    haveRawL = true;
  }
  if (adsOkR && adsReadRaw(busR, raw)) {
    lastRawR = raw;
    haveRawR = true;
  }
  adsPending = false;
}

void printLive() {
  float ax, ay, az, gx, gy, gz, tc, bx, by, bz, hx, hy, hz, tcR;
  bool okL = mpuRead(busL, ax, ay, az, gx, gy, gz, tc);
  bool okR = mpuRead(busR, bx, by, bz, hx, hy, hz, tcR);
  (void)gx;
  (void)gy;
  (void)gz;
  (void)tc;
  (void)hx;
  (void)hy;
  (void)hz;
  (void)tcR;
  long cL = readEnc(encL);
  long cR = readEnc(encR);
  Serial.printf("좌 위치 %.1f mm  간격 %.2f   우 위치 %.1f mm  간격 %.2f   Z %.2f / %.2f m/s2   %s %s\n",
                POS_SIGN_L * cL * MM_PER_COUNT,
                haveRawL ? gapMM(lastRawL * ADS_LSB * DIV, true) : NAN,
                POS_SIGN_R * cR * MM_PER_COUNT,
                haveRawR ? gapMM(lastRawR * ADS_LSB * DIV, false) : NAN,
                okL ? az : NAN,
                okR ? bz : NAN,
                shockLatch ? "충격정지" : motionName(effectiveMotion()),
                driveSign > 0 ? "전진" : "후진");
}

void beginTimedRun() {
  shockLatch = false;
  driveSign = 1;
  motionL = motionR = MOTION_CRUISE;
  zeroEncoders();
  runUntilMs = millis() + BUTTON_RUN_MS;
  Serial.println("BOOT 전진 80초");
}

void pollBoot() {
  bool pressed = false;
  noInterrupts();
  if (bootFlag) {
    bootFlag = false;
    pressed = true;
  }
  interrupts();

  uint32_t now = millis();
  if (pressed && (uint32_t)(now - bootEdgeMs) >= BUTTON_DEBOUNCE_MS) {
    bootEdgeMs = now;
    if (runUntilMs != 0) {
      runUntilMs = 0;
      motionL = motionR = MOTION_STOP;
      Serial.println("BOOT 정지");
    } else {
      beginTimedRun();
    }
  }
  if (runUntilMs != 0 && (int32_t)(now - runUntilMs) >= 0) {
    runUntilMs = 0;
    motionL = motionR = MOTION_STOP;
    Serial.println("80초 끝");
    printLive();
  }
}

void handleSerial() {
  if (!Serial.available()) return;
  char c = Serial.read();
  while (Serial.available()) Serial.read();
  if (c == 'g' || c == 's' || c == 'b' || c == '0') runUntilMs = 0;
  if (c == 'g') {
    driveSign = 1;
    motionL = motionR = MOTION_CRUISE;
  } else if (c == 's') {
    driveSign = 1;
    motionL = motionR = MOTION_SLOW;
  } else if (c == 'b') {
    driveSign = -1;
    motionL = motionR = MOTION_CRUISE;
  } else if (c == '0') {
    motionL = motionR = MOTION_STOP;
  } else if (c == 'z') {
    zeroEncoders();
    Serial.println("위치 0");
  } else if (c == 'c') {
    shockLatch = false;
    Serial.println("충격 정지 해제");
  } else if (c == 'r') {
    printLive();
  }
}

void setup() {
  pinMode(IN1_L, OUTPUT);
  pinMode(IN2_L, OUTPUT);
  pinMode(ENA_L, OUTPUT);
  pinMode(IN1_R, OUTPUT);
  pinMode(IN2_R, OUTPUT);
  pinMode(ENA_R, OUTPUT);
  motorStop();
  pinMode(PIN_BOOT, INPUT_PULLUP);
  attachInterrupt(PIN_BOOT, isrBoot, FALLING);

  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);

  snprintf(bootId, sizeof bootId, "%08lx", (unsigned long)esp_random());
  Serial.printf("\nHP028 실물 초안 %s  boot %s\n", FIRMWARE_VERSION, bootId);
  Serial.println("전진 = 빨간 기판 쪽. 판정은 서버가 한다.");
  Serial.println("BOOT = 전진 80초. RST = 다시 켜기만, 바퀴는 안 돌림.");

  busL.begin(SDA_L, SCL_L, 100000);
  busR.begin(SDA_R, SCL_R, 100000);
  mpuOkL = mpuInit(busL);
  mpuOkR = mpuInit(busR);
  Serial.printf("기울기 칩  좌 %s  우 %s\n", mpuOkL ? "OK" : "실패", mpuOkR ? "OK" : "실패");

  pinMode(ENCA_L, INPUT_PULLUP);
  pinMode(ENCB_L, INPUT_PULLUP);
  pinMode(ENCA_R, INPUT_PULLUP);
  pinMode(ENCB_R, INPUT_PULLUP);
  attachInterrupt(ENCA_L, isrL, RISING);
  attachInterrupt(ENCA_R, isrR, RISING);

#if MQTT_ENABLED
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("와이파이 연결 시도: %s\n", WIFI_SSID);
#else
  Serial.println("secrets.h 없음. USB로만 배치를 출력한다.");
#endif
}

void loop() {
  pollBoot();
  applyDrive();
  serviceAds();
  static uint32_t nextSample = 0;
  uint32_t now = micros();
  if (nextSample == 0) nextSample = now;
  if ((int32_t)(now - nextSample) >= 0) {
    nextSample += SAMPLE_INTERVAL_US;
    if ((int32_t)(now - nextSample) > 0) nextSample = now + SAMPLE_INTERVAL_US;
    takeSample();
  }
  handleSerial();
  applyDrive();
#if MQTT_ENABLED
  serviceMqtt();
#endif
}
