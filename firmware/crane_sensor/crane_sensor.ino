/**
 * crane_sensor.ino
 * 크레인 상태 데이터 수집 펌웨어
 * 대상 보드 : ESP32-S3-WROOM-1
 * 센서     : ADXL345 (I2C 가속도) + MPU-6050 (I2C 6축 자이로-가속도) + HC-SR04 (초음파 거리)
 *
 * ═══════════════════════════════════════════════════════════
 *  [회로 연결 정보 — 브레드보드 점퍼 와이어]
 * ───────────────────────────────────────────────────────────
 *  ■ ADXL345 + MPU-6050 (동일 I2C 버스 공유, 병렬 연결)
 *    두 센서 모두 I2C 통신이므로 ESP32-S3의 SDA/SCL 라인을
 *    브레드보드 위에서 그대로 병렬 연결(공유)한다.
 *    (I2C는 버스 방식이라 여러 디바이스가 같은 SDA/SCL을 공유 가능,
 *     단 두 센서의 I2C 주소가 달라야 함 — ADXL345=0x53, MPU-6050=0x68)
 *
 *    ADXL345 핀   →  ESP32-S3 핀
 *    VCC          →  3.3V   (3V3 핀, 절대 5V 연결 금지)
 *    GND          →  GND
 *    SDA          →  GPIO 8  (공유 SDA)
 *    SCL          →  GPIO 9  (공유 SCL)
 *    SDO/ADDR     →  GND     (I2C 주소 0x53 고정)
 *    CS           →  3.3V    (SPI 비활성화 → I2C 모드 전환)
 *    INT1, INT2   →  연결 안 함
 *
 *    MPU-6050 핀  →  ESP32-S3 핀
 *    VCC          →  3.3V   (※ 모듈에 따라 5V 허용 보드도 있으나 3.3V 권장)
 *    GND          →  GND
 *    SDA          →  GPIO 8  (ADXL345와 동일 라인에 병렬 연결)
 *    SCL          →  GPIO 9  (ADXL345와 동일 라인에 병렬 연결)
 *    AD0          →  GND     (I2C 주소 0x68 고정, 3.3V 연결 시 0x69로 변경됨)
 *    INT          →  연결 안 함
 *
 *    ※ SDA/SCL 공유 시 각 라인에 4.7kΩ 풀업 저항 1개만 있으면 충분
 *      (모듈 보드에 이미 풀업이 내장된 경우 중복 연결 주의)
 *
 *  ■ HC-SR04 (GPIO, 기존과 동일)
 *    HC-SR04 핀  →  ESP32-S3 핀
 *    VCC         →  5V       (VBUS 핀 — USB 전원 공급 필요)
 *    GND         →  GND
 *    Trig        →  GPIO 5
 *    Echo        →  GPIO 4   ※ HC-SR04 Echo 출력은 5V 로직!
 *                             전압 분배기(1kΩ + 2kΩ)를 Echo 라인에 삽입할 것.
 *                             (Echo → 1kΩ → GPIO4 → 2kΩ → GND)
 * ───────────────────────────────────────────────────────────
 *  [필요 라이브러리 — Arduino IDE 라이브러리 매니저에서 설치]
 *    - "Adafruit ADXL345" by Adafruit
 *    - "Adafruit MPU6050" by Adafruit
 *    - "Adafruit Unified Sensor" by Adafruit  (공통 의존성)
 * ═══════════════════════════════════════════════════════════
 *
 *  [출력 포맷]  115200 bps, 1초 주기, 줄바꿈(\n) 포함
 *    AAX:0.12,AAY:-0.05,AAZ:9.81,DIST:23.45,MAX:0.01,MAY:-0.02,MAZ:9.80,GX:0.5,GY:1.2,GZ:-0.3
 *
 *    AAX/AAY/AAZ : ADXL345 가속도 (m/s²)
 *    DIST        : HC-SR04 거리 (cm)
 *    MAX/MAY/MAZ : MPU-6050 가속도 (m/s²)
 *    GX/GY/GZ    : MPU-6050 자이로 (rad/s)
 */

#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_ADXL345_U.h>
#include <Adafruit_MPU6050.h>

// ─────────────────────────────────────────────
//  핀 설정
// ─────────────────────────────────────────────
constexpr uint8_t PIN_TRIG = 5;
constexpr uint8_t PIN_ECHO = 4;

// ─────────────────────────────────────────────
//  타이밍 설정
// ─────────────────────────────────────────────
constexpr uint32_t SAMPLE_INTERVAL_MS = 1000;   // 데이터 전송 주기 (ms)
constexpr uint32_t HC_SR04_TIMEOUT_US = 30000;  // Echo 대기 타임아웃 (µs, 약 5 m 해당)

// ─────────────────────────────────────────────
//  센서 객체
// ─────────────────────────────────────────────
Adafruit_ADXL345_Unified adxl = Adafruit_ADXL345_Unified(12345);  // I2C 0x53
Adafruit_MPU6050 mpu;                                             // I2C 0x68

// 마지막 전송 시각 기록용
static uint32_t lastSampleMs = 0;

// ─────────────────────────────────────────────
//  HC-SR04 거리 측정 함수
//  반환값: 거리(cm), 타임아웃 시 -1.0f
// ─────────────────────────────────────────────
float measureDistanceCm() {
  // Trig 핀에 10 µs 펄스 인가
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);

  // Echo 핀 HIGH 구간 측정 (타임아웃 처리)
  uint32_t duration = pulseIn(PIN_ECHO, HIGH, HC_SR04_TIMEOUT_US);

  if (duration == 0) {
    return -1.0f;  // 타임아웃 또는 측정 범위 초과
  }

  // 음속 343 m/s 기준: 왕복 거리이므로 / 2
  // duration(µs) × 0.0343 cm/µs ÷ 2
  return (float)duration * 0.01715f;
}

// ─────────────────────────────────────────────
//  setup()
// ─────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  // 시리얼 모니터가 준비될 때까지 최대 3초 대기
  uint32_t waitStart = millis();
  while (!Serial && (millis() - waitStart < 3000)) {
    delay(10);
  }

  Serial.println("[BOOT] 크레인 센서 펌웨어 시작 (ADXL345 + MPU-6050 + HC-SR04)");

  // I2C 버스 시작 (ADXL345, MPU-6050 공유)
  Wire.begin();

  // HC-SR04 핀 초기화
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  digitalWrite(PIN_TRIG, LOW);
  Serial.println("[OK]  HC-SR04 핀 초기화 완료 (Trig=5, Echo=4)");

  // ── ADXL345 초기화 ──
  if (!adxl.begin()) {
    Serial.println("[ERROR] ADXL345 초기화 실패!");
    Serial.println("        체크리스트:");
    Serial.println("        1. VCC → 3.3V, GND → GND 연결 확인");
    Serial.println("        2. SDA → GPIO8, SCL → GPIO9 연결 확인 (MPU-6050과 공유)");
    Serial.println("        3. CS 핀을 3.3V에 연결했는지 확인");
    Serial.println("        4. I2C 주소 충돌 여부 확인 (ADXL345=0x53)");
    Serial.println("        프로그램을 재시작하거나 배선을 점검하세요.");
    while (1) {
      delay(1000);  // 무한 대기 (watchdog 방지용 delay 포함)
    }
  }
  adxl.setRange(ADXL345_RANGE_16_G);  // 크레인 진동 대응 ±16g
  Serial.println("[OK]  ADXL345 초기화 완료 (범위 ±16g, I2C 0x53)");

  // ── MPU-6050 초기화 ──
  if (!mpu.begin()) {
    Serial.println("[ERROR] MPU-6050 초기화 실패!");
    Serial.println("        체크리스트:");
    Serial.println("        1. VCC → 3.3V, GND → GND 연결 확인");
    Serial.println("        2. SDA → GPIO8, SCL → GPIO9 연결 확인 (ADXL345와 공유)");
    Serial.println("        3. AD0 핀이 GND에 연결되어 있는지 확인 (주소 0x68)");
    Serial.println("        4. I2C 주소 충돌 여부 확인 (MPU-6050=0x68)");
    Serial.println("        프로그램을 재시작하거나 배선을 점검하세요.");
    while (1) {
      delay(1000);  // 무한 대기 (watchdog 방지용 delay 포함)
    }
  }
  mpu.setAccelerometerRange(MPU6050_RANGE_16_G);   // 크레인 진동 대응 ±16g
  mpu.setGyroRange(MPU6050_RANGE_500_DEG);         // 크레인 회전 대응 ±500°/s
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
  Serial.println("[OK]  MPU-6050 초기화 완료 (가속도 ±16g, 자이로 ±500°/s, I2C 0x68)");

  Serial.println("[INFO] 데이터 출력 시작 (1초 주기, 115200 bps)");
  Serial.println("─────────────────────────────────────────────");

  lastSampleMs = millis();
}

// ─────────────────────────────────────────────
//  loop()
// ─────────────────────────────────────────────
void loop() {
  uint32_t now = millis();

  // millis() 오버플로 대응 포함 경과 시간 계산
  if ((uint32_t)(now - lastSampleMs) < SAMPLE_INTERVAL_MS) {
    return;
  }
  lastSampleMs = now;

  // ── ADXL345 읽기 ──
  sensors_event_t adxlEvent;
  adxl.getEvent(&adxlEvent);
  float aax = adxlEvent.acceleration.x;  // m/s²
  float aay = adxlEvent.acceleration.y;
  float aaz = adxlEvent.acceleration.z;

  // ── HC-SR04 읽기 ──
  float dist = measureDistanceCm();

  // ── MPU-6050 읽기 (가속도 + 자이로) ──
  sensors_event_t mpuAccel, mpuGyro, mpuTemp;
  mpu.getEvent(&mpuAccel, &mpuGyro, &mpuTemp);
  float max_ = mpuAccel.acceleration.x;  // m/s²
  float may  = mpuAccel.acceleration.y;
  float maz  = mpuAccel.acceleration.z;
  float gx   = mpuGyro.gyro.x;           // rad/s
  float gy   = mpuGyro.gyro.y;
  float gz   = mpuGyro.gyro.z;

  // ── 직렬 출력 (CSV-like 단일 라인) ──
  // 포맷: AAX:0.12,AAY:-0.05,AAZ:9.81,DIST:23.45,MAX:0.01,MAY:-0.02,MAZ:9.80,GX:0.5,GY:1.2,GZ:-0.3
  Serial.print("AAX:");
  Serial.print(aax, 2);
  Serial.print(",AAY:");
  Serial.print(aay, 2);
  Serial.print(",AAZ:");
  Serial.print(aaz, 2);
  Serial.print(",DIST:");

  if (dist < 0.0f) {
    Serial.print("ERR");   // 측정 실패 시 ERR 출력 (파이썬에서 필터링 가능)
  } else {
    Serial.print(dist, 2);
  }

  Serial.print(",MAX:");
  Serial.print(max_, 2);
  Serial.print(",MAY:");
  Serial.print(may, 2);
  Serial.print(",MAZ:");
  Serial.print(maz, 2);
  Serial.print(",GX:");
  Serial.print(gx, 2);
  Serial.print(",GY:");
  Serial.print(gy, 2);
  Serial.print(",GZ:");
  Serial.println(gz, 2);
}
