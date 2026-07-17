/**
 * crane_sensor.ino
 * 크레인 상태 데이터 수집 펌웨어
 * 대상 보드 : ESP32-S3-WROOM-1
 * 센서     : ADXL345 (I2C 가속도) + HC-SR04 (초음파 거리)
 *
 * ═══════════════════════════════════════════════════════════
 *  [회로 연결 정보 — 브레드보드 점퍼 와이어]
 * ───────────────────────────────────────────────────────────
 *  ■ ADXL345 (I2C)
 *    ADXL345 핀  →  ESP32-S3 핀
 *    VCC         →  3.3V  (3V3 핀, 절대 5V 연결 금지)
 *    GND         →  GND
 *    SDA         →  GPIO 8  (ESP32-S3 기본 I2C SDA)
 *    SCL         →  GPIO 9  (ESP32-S3 기본 I2C SCL)
 *    SDO/ADDR    →  GND     (I2C 주소 0x53 고정)
 *                   ※ SDO를 3.3V에 연결하면 주소 0x1D로 변경됨
 *    CS          →  3.3V    (SPI 비활성화 → I2C 모드 전환)
 *    INT1, INT2  →  연결 안 함 (인터럽트 미사용)
 *
 *  ■ HC-SR04 (GPIO)
 *    HC-SR04 핀  →  ESP32-S3 핀
 *    VCC         →  5V       (VBUS 핀 — USB 전원 공급 필요)
 *    GND         →  GND
 *    Trig        →  GPIO 5
 *    Echo        →  GPIO 4   ※ HC-SR04 Echo 출력은 5V 로직!
 *                             ESP32-S3는 3.3V 허용이므로
 *                             반드시 전압 분배기(1kΩ + 2kΩ) 또는
 *                             레벨 시프터를 Echo 라인에 삽입할 것.
 *                             (전압 분배기: Echo → 1kΩ → GPIO4
 *                                                   → 2kΩ → GND)
 * ───────────────────────────────────────────────────────────
 *  [필요 라이브러리 — Arduino IDE 라이브러리 매니저에서 설치]
 *    - "Adafruit ADXL345" by Adafruit
 *    - "Adafruit Unified Sensor" by Adafruit  (의존성)
 * ═══════════════════════════════════════════════════════════
 *
 *  [출력 포맷]  115200 bps, 1초 주기, 줄바꿈(\n) 포함
 *    AX:0.12,AY:-0.05,AZ:9.81,DIST:23.45
 */

#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_ADXL345_U.h>

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
//  ADXL345 객체 (I2C, 고유 ID = 12345)
// ─────────────────────────────────────────────
Adafruit_ADXL345_Unified adxl = Adafruit_ADXL345_Unified(12345);

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

  Serial.println("[BOOT] 크레인 센서 펌웨어 시작");

  // HC-SR04 핀 초기화
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  digitalWrite(PIN_TRIG, LOW);
  Serial.println("[OK]  HC-SR04 핀 초기화 완료 (Trig=5, Echo=4)");

  // ADXL345 초기화
  if (!adxl.begin()) {
    Serial.println("[ERROR] ADXL345 초기화 실패!");
    Serial.println("        체크리스트:");
    Serial.println("        1. VCC → 3.3V, GND → GND 연결 확인");
    Serial.println("        2. SDA → GPIO8, SCL → GPIO9 연결 확인");
    Serial.println("        3. CS 핀을 3.3V에 연결했는지 확인");
    Serial.println("        4. 다른 I2C 디바이스와 주소 충돌 여부 확인");
    Serial.println("        프로그램을 재시작하거나 배선을 점검하세요.");
    while (1) {
      delay(1000);  // 무한 대기 (watchdog 방지용 delay 포함)
    }
  }

  // 측정 범위 설정: ±16g (크레인 진동 대응)
  adxl.setRange(ADXL345_RANGE_16_G);

  Serial.println("[OK]  ADXL345 초기화 완료 (범위 ±16g, I2C 0x53)");
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
  sensors_event_t event;
  adxl.getEvent(&event);

  float ax = event.acceleration.x;  // m/s²
  float ay = event.acceleration.y;
  float az = event.acceleration.z;

  // ── HC-SR04 읽기 ──
  float dist = measureDistanceCm();

  // ── 직렬 출력 (CSV-like 단일 라인) ──
  // 포맷: AX:0.12,AY:-0.05,AZ:9.81,DIST:23.45
  Serial.print("AX:");
  Serial.print(ax, 2);
  Serial.print(",AY:");
  Serial.print(ay, 2);
  Serial.print(",AZ:");
  Serial.print(az, 2);
  Serial.print(",DIST:");

  if (dist < 0.0f) {
    Serial.println("ERR");   // 측정 실패 시 ERR 출력 (파이썬에서 필터링 가능)
  } else {
    Serial.println(dist, 2);
  }
}
