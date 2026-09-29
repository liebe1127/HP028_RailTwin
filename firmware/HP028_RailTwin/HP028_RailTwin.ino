/* ============================================================
   HP028_RailTwin  —  배선 점검용 테스트 코드 (bring-up)
   ESP32-S3-DevKitC-1 N16R8 / I2C 2버스 구성
   2026-09-24  센서 교정표 반영 + 센서 위치 맞춤(a) + 30cm 주행 시험(k, t)

   라이브러리 설치 필요 없음. Wire 만 씁니다.
   (MPU6050·ADS1115 를 레지스터로 직접 다룹니다 — 라이브러리
    버전 문제로 헤매지 않으려는 목적)

   업로드 후 시리얼 모니터 115200, 줄 바꿈 "줄 바꿈 없음"
   ============================================================ */

#include <Wire.h>

// ── 핀 배정 (배선표 2장) ────────────────────────────────────
#define SDA_L  11      // 좌 I2C0  (좌 MPU6050 + 좌 ADS1115)
#define SCL_L  12
#define SDA_R  13      // 우 I2C1  (우 MPU6050 + 우 ADS1115)
#define SCL_R  14

#define ENA_L   4      // 좌 L298N
#define IN1_L   5
#define IN2_L   6
#define ENA_R   7      // 우 L298N
#define IN1_R   8
#define IN2_R   9

#define ENCA_L 15      // 좌 엔코더
#define ENCB_L 16
#define ENCA_R 17      // 우 엔코더
#define ENCB_R 18

// ── 상수 ────────────────────────────────────────────────────
#define MPU_ADDR 0x68
#define ADS_ADDR 0x48

const float R_TOP = 20000.0;    // 분압 상단
const float R_BOT = 10000.0;    // 분압 하단
const float DIV   = (R_TOP + R_BOT) / R_BOT;   // 3.0
const float ADS_LSB = 4.096 / 32768.0;          // 125 uV  (GAIN ±4.096V)

const uint8_t MOTOR_DUTY = 120;   // 0~255. 시험용 저속

// ── 30cm 주행 시험 설정 ─────────────────────────────────────
const float   TARGET_GAP_MM  = 5.00;   // 센서 설치 기준 간격
const float   ALIGN_TOL_MM   = 0.05;   // 위치 맞춤 허용 오차
long          COUNTS_PER_300 = 6034;      // 'k' 로 측정한 값을 여기 적고 다시 업로드 (0 이면 t 불가)
const float   RUN_MM         = 300.0;  // 주행 거리
const uint8_t RUN_DUTY       = 120;    // 주행 속도 (0~255)
const uint32_t RUN_TIMEOUT   = 20000;  // 최대 주행 시간 ms
const float   GAP_SAFE_MIN   = 1.0;    // 이 범위를 벗어나면 즉시 정지
const float   GAP_SAFE_MAX   = 8.5;

TwoWire &busL = Wire;
TwoWire &busR = Wire1;

volatile long encL = 0, encR = 0;

// ── I2C 기본 ────────────────────────────────────────────────
bool i2cWrite8(TwoWire &w, uint8_t addr, uint8_t reg, uint8_t val) {
  w.beginTransmission(addr);
  w.write(reg); w.write(val);
  return w.endTransmission() == 0;
}
bool i2cWrite16(TwoWire &w, uint8_t addr, uint8_t reg, uint16_t val) {
  w.beginTransmission(addr);
  w.write(reg); w.write(val >> 8); w.write(val & 0xFF);
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

// ── MPU6050 ────────────────────────────────────────────────
bool mpuInit(TwoWire &w) {
  if (!i2cWrite8(w, MPU_ADDR, 0x6B, 0x00)) return false;  // 절전 해제
  delay(10);
  i2cWrite8(w, MPU_ADDR, 0x1C, 0x00);   // 가속도 ±2g
  i2cWrite8(w, MPU_ADDR, 0x1A, 0x03);   // DLPF 44Hz
  return true;
}
uint8_t mpuWhoAmI(TwoWire &w) {
  uint8_t v = 0;
  i2cRead(w, MPU_ADDR, 0x75, &v, 1);
  return v;
}
bool mpuAccel(TwoWire &w, float &ax, float &ay, float &az) {
  uint8_t b[6];
  if (!i2cRead(w, MPU_ADDR, 0x3B, b, 6)) return false;
  ax = (int16_t)(b[0] << 8 | b[1]) / 16384.0f;
  ay = (int16_t)(b[2] << 8 | b[3]) / 16384.0f;
  az = (int16_t)(b[4] << 8 | b[5]) / 16384.0f;
  return true;
}

// ── ADS1115 (A0 단극, ±4.096V, 128SPS, 단발 변환) ───────────
bool adsRead(TwoWire &w, int16_t &raw) {
  const uint16_t cfg = 0xC383;
  if (!i2cWrite16(w, ADS_ADDR, 0x01, cfg)) return false;
  delay(10);                                   // 변환 대기
  uint8_t b[2];
  if (!i2cRead(w, ADS_ADDR, 0x00, b, 2)) return false;
  raw = (int16_t)(b[0] << 8 | b[1]);
  return true;
}
float adsVolt(int16_t raw)   { return raw * ADS_LSB; }          // ADS 핀 전압
float sensorVolt(int16_t raw){ return adsVolt(raw) * DIV; }     // 센서 출력 전압

// ── 교정표 (2026-09-24 실측, 센서 V → 거리 mm) ─────────────
const int   CAL_N = 5;
const float CAL_MM[CAL_N] = {0.0, 2.0, 4.0, 6.0, 8.0};
const float CAL_VL[CAL_N] = {-0.010, 0.187, 2.044, 5.725, 7.592};  // 좌
const float CAL_VR[CAL_N] = { 0.004, 0.242, 2.935, 6.546, 8.210};  // 우

float gapMM(int16_t raw, bool left) {
  const float *cv = left ? CAL_VL : CAL_VR;
  float v = sensorVolt(raw);
  if (v <= cv[0]) return CAL_MM[0];
  for (int i = 1; i < CAL_N; i++) {
    if (v <= cv[i])
      return CAL_MM[i-1] + (v - cv[i-1]) * (CAL_MM[i] - CAL_MM[i-1]) / (cv[i] - cv[i-1]);
  }
  int k = CAL_N - 1;   // 8mm 초과 — 마지막 구간 기울기로 연장
  return CAL_MM[k] + (v - cv[k]) * (CAL_MM[k] - CAL_MM[k-1]) / (cv[k] - cv[k-1]);
}

// ── 엔코더 ─────────────────────────────────────────────────
void IRAM_ATTR isrL() { encL += digitalRead(ENCB_L) ? 1 : -1; }
void IRAM_ATTR isrR() { encR += digitalRead(ENCB_R) ? 1 : -1; }

// ── 모터 ───────────────────────────────────────────────────
void motorStop() {
  analogWrite(ENA_L, 0); digitalWrite(IN1_L, LOW); digitalWrite(IN2_L, LOW);
  analogWrite(ENA_R, 0); digitalWrite(IN1_R, LOW); digitalWrite(IN2_R, LOW);
}
void motorRun(char side, bool fwd, uint8_t duty) {
  if (side == 'L') {
    digitalWrite(IN1_L, fwd); digitalWrite(IN2_L, !fwd);
    analogWrite(ENA_L, duty);
  } else {
    digitalWrite(IN1_R, fwd); digitalWrite(IN2_R, !fwd);
    analogWrite(ENA_R, duty);
  }
}
void driveBoth(bool fwd, uint32_t ms) {
  Serial.printf("\n%s  %lu ms  (글자를 누르면 즉시 정지)\n", fwd ? "코드의 앞" : "코드의 뒤", (unsigned long)ms);
  encL = 0; encR = 0;
  motorRun('L', fwd, MOTOR_DUTY);
  motorRun('R', fwd, MOTOR_DUTY);
  uint32_t t0 = millis();
  while (millis() - t0 < ms) {
    if (Serial.available()) break;
  }
  motorStop();
  Serial.printf("정지  엔코더 좌 %ld  우 %ld\n", encL, encR);
  while (Serial.available()) Serial.read();
}

// ── 1. I2C 스캔 ────────────────────────────────────────────
void scan(TwoWire &w, const char *tag) {
  Serial.printf("\n[%s 버스] 스캔\n", tag);
  int n = 0;
  for (uint8_t a = 1; a < 127; a++) {
    w.beginTransmission(a);
    if (w.endTransmission() == 0) {
      Serial.printf("   0x%02X  %s\n", a,
        a == 0x68 ? "← MPU6050" : (a == 0x48 ? "← ADS1115" : ""));
      n++;
    }
  }
  if (n == 0) Serial.println("   아무것도 없음  ← 이 버스의 배선을 보십시오");
  else if (n == 2) Serial.println("   정상 (2개)");
  else Serial.printf("   %d개 — 0x68 과 0x48 둘 다 나와야 정상\n", n);
}

// ── 2. 센서 읽기 ───────────────────────────────────────────
void readOnce() {
  int16_t rL, rR;
  bool okL = adsRead(busL, rL), okR = adsRead(busR, rR);
  float axL, ayL, azL, axR, ayR, azR;
  bool mL = mpuAccel(busL, axL, ayL, azL);
  bool mR = mpuAccel(busR, axR, ayR, azR);

  Serial.print("좌 ");
  if (okL) Serial.printf("ADS %6d  %6.3fV(핀)  %6.3fV(센서)  %6.2fmm",
                         rL, adsVolt(rL), sensorVolt(rL), gapMM(rL, true));
  else     Serial.print("ADS 읽기실패");
  if (mL)  Serial.printf("   MPU %+5.2f %+5.2f %+5.2f", axL, ayL, azL);
  else     Serial.print("   MPU 읽기실패");
  Serial.printf("   ENC %ld\n", encL);

  Serial.print("우 ");
  if (okR) Serial.printf("ADS %6d  %6.3fV(핀)  %6.3fV(센서)  %6.2fmm",
                         rR, adsVolt(rR), sensorVolt(rR), gapMM(rR, false));
  else     Serial.print("ADS 읽기실패");
  if (mR)  Serial.printf("   MPU %+5.2f %+5.2f %+5.2f", axR, ayR, azR);
  else     Serial.print("   MPU 읽기실패");
  Serial.printf("   ENC %ld\n", encR);
}

// ── 3. 접지 합격 판정 (배선표 11장 10단계) ──────────────────
float meanMM(TwoWire &w, int n) {
  double s = 0; int ok = 0; int16_t r;
  for (int i = 0; i < n; i++) if (adsRead(w, r)) { s += gapMM(r, &w == &busL); ok++; }
  return ok ? s / ok : NAN;
}
void groundTest() {
  Serial.println("\n=== 접지 시험 ===  모터 정지 상태 측정");
  float offL = meanMM(busL, 20), offR = meanMM(busR, 20);
  Serial.printf("  정지   좌 %.3f mm   우 %.3f mm\n", offL, offR);

  Serial.println("  모터 구동...");
  motorRun('L', true, MOTOR_DUTY);
  motorRun('R', true, MOTOR_DUTY);
  delay(400);
  float onL = meanMM(busL, 20), onR = meanMM(busR, 20);
  motorStop();
  Serial.printf("  구동중 좌 %.3f mm   우 %.3f mm\n", onL, onR);

  float dL = fabs(onL - offL), dR = fabs(onR - offR);
  Serial.printf("  차이   좌 %.3f mm   우 %.3f mm   (기준 0.05mm 미만)\n", dL, dR);
  Serial.printf("  판정   %s\n",
    (dL < 0.05 && dR < 0.05) ? "합격" : "불합격 — 배선표 9장(접지)으로 돌아갈 것");
}

// ── 4. 센서 위치 맞춤 (a) ──────────────────────────────────
//   두 센서가 모두 TARGET_GAP_MM 에 오도록 센서 너트를 돌려 맞춘다
void alignMode() {
  Serial.printf("\n=== 센서 위치 맞춤 ===  목표 %.2f mm  (±%.2f)  아무 키나 누르면 종료\n",
                TARGET_GAP_MM, ALIGN_TOL_MM);
  while (!Serial.available()) {
    float gL = meanMM(busL, 5), gR = meanMM(busR, 5);
    float eL = gL - TARGET_GAP_MM, eR = gR - TARGET_GAP_MM;
    Serial.printf("좌 %5.2f mm (%+5.2f) %s    우 %5.2f mm (%+5.2f) %s\n",
      gL, eL, fabs(eL) <= ALIGN_TOL_MM ? "OK  " : (eL > 0 ? "가깝게" : "멀게  "),
      gR, eR, fabs(eR) <= ALIGN_TOL_MM ? "OK  " : (eR > 0 ? "가깝게" : "멀게  "));
    delay(200);
  }
  while (Serial.available()) Serial.read();
}

// ── 5. 엔코더 교정 (k) ─────────────────────────────────────
//   모터로 CAL_RUN_MS 동안 달린 뒤, 자로 잰 실제 이동 거리(mm)를 입력한다
const uint32_t CAL_RUN_MS = 1500;      // 교정 주행 시간 (레일 길이에 맞게 조절)

void encoderCal() {
  Serial.println("\n=== 엔코더 교정 ===");
  Serial.println("대차 앞바퀴 위치를 레일에 표시한 뒤 아무 키나 누르면 출발합니다.");
  while (!Serial.available()) delay(10);
  while (Serial.available()) Serial.read();

  encL = 0; encR = 0;
  motorRun('L', true, RUN_DUTY);
  motorRun('R', true, RUN_DUTY);
  uint32_t t0 = millis();
  while (millis() - t0 < CAL_RUN_MS && !Serial.available()) delay(5);
  motorStop();
  delay(300);                                   // 관성으로 굴러간 것까지 포함
  while (Serial.available()) Serial.read();

  long cL = labs(encL), cR = labs(encR), cAvg = (cL + cR) / 2;
  Serial.printf("  엔코더  좌 %ld   우 %ld   평균 %ld\n", cL, cR, cAvg);
  if (cL == 0 || cR == 0) { Serial.println("  ⚠ 한쪽이 0 — 그쪽 엔코더 배선 확인"); return; }
  if (fabs((float)cL - cR) / cAvg > 0.05)
    Serial.println("  ⚠ 좌우 차이 5% 초과 — 바퀴 미끄러짐 또는 엔코더 확인");

  Serial.println("\n표시한 곳부터 앞바퀴까지 이동 거리를 자로 재서 mm 로 입력하십시오 (예: 185)");
  while (!Serial.available()) delay(10);
  delay(100);
  String in = "";
  while (Serial.available()) in += (char)Serial.read();
  float mm = in.toFloat();
  if (mm <= 0) { Serial.println("  숫자를 읽지 못했습니다. k 부터 다시 하십시오."); return; }

  COUNTS_PER_300 = lround(cAvg * 300.0 / mm);
  Serial.printf("  입력 %.1f mm  →  COUNTS_PER_300 = %ld\n", mm, COUNTS_PER_300);
  Serial.println("  지금 바로 t 를 쓸 수 있습니다 (전원을 끄면 사라짐).");
  Serial.printf("  계속 쓰려면 코드 맨 위를  long COUNTS_PER_300 = %ld;  로 고쳐 업로드하십시오.\n",
                COUNTS_PER_300);
}

// ── 6. 30cm 주행 시험 (t) ──────────────────────────────────
struct Stat {                 // 평균·표준편차·최소·최대
  double s = 0, s2 = 0; float mn = 1e9, mx = -1e9; long n = 0;
  void add(float v) { s += v; s2 += (double)v * v; n++; if (v < mn) mn = v; if (v > mx) mx = v; }
  float mean() const { return n ? s / n : NAN; }
  float sd()   const { return n > 1 ? sqrt(fmax(0.0, s2 / n - (s / n) * (s / n))) : 0; }
};

void runTest() {
  if (COUNTS_PER_300 <= 0) {
    Serial.println("\nCOUNTS_PER_300 가 0 입니다. 먼저 'k' 로 엔코더를 교정하십시오.");
    return;
  }
  Serial.println("\n=== 30cm 주행 시험 ===  아무 키나 누르면 즉시 정지");

  // 1) 정지 상태 기준값 (1초)
  Stat s0L, s0R;
  for (int i = 0; i < 40; i++) {
    int16_t r;
    if (adsRead(busL, r)) s0L.add(gapMM(r, true));
    if (adsRead(busR, r)) s0R.add(gapMM(r, false));
  }
  Serial.printf("정지 기준  좌 %.3f mm (흔들림 %.3f)   우 %.3f mm (흔들림 %.3f)\n",
                s0L.mean(), s0L.sd(), s0R.mean(), s0R.sd());
  delay(500);

  // 2) 주행하며 기록
  Serial.println("\nCSV,t_ms,dist_mm,gapL_mm,gapR_mm,diff_mm,azL_g,azR_g");
  Stat gL, gR, dLR, vzL, vzR;
  long fail = 0, samples = 0;
  const char *stopWhy = "목표 거리 도달";
  encL = 0; encR = 0;
  motorRun('L', true, RUN_DUTY);
  motorRun('R', true, RUN_DUTY);
  uint32_t t0 = millis(), lastMove = t0;
  long lastCnt = 0;
  float dist = 0;

  while (true) {
    uint32_t t = millis() - t0;
    long cL = labs(encL), cR = labs(encR);
    dist = (cL + cR) / 2.0f * 300.0f / COUNTS_PER_300;

    int16_t rL, rR; float a1, a2, zL = NAN, zR = NAN;
    bool okL = adsRead(busL, rL), okR = adsRead(busR, rR);
    mpuAccel(busL, a1, a2, zL); mpuAccel(busR, a1, a2, zR);
    samples++;
    float xL = NAN, xR = NAN;
    if (okL && okR) {
      xL = gapMM(rL, true); xR = gapMM(rR, false);
      gL.add(xL); gR.add(xR); dLR.add(xL - xR);
      if (!isnan(zL)) vzL.add(zL);
      if (!isnan(zR)) vzR.add(zR);
      Serial.printf("CSV,%lu,%.1f,%.3f,%.3f,%.3f,%.3f,%.3f\n", t, dist, xL, xR, xL - xR, zL, zR);
    } else {
      fail++;
      if (fail > 20) { stopWhy = "센서 읽기 연속 실패 (I2C 확인)"; break; }
    }

    if (dist >= RUN_MM) break;
    if (Serial.available())            { stopWhy = "사용자 정지"; break; }
    if (t > RUN_TIMEOUT)               { stopWhy = "시간 초과"; break; }
    if (!isnan(xL) && (xL < GAP_SAFE_MIN || xL > GAP_SAFE_MAX || xR < GAP_SAFE_MIN || xR > GAP_SAFE_MAX))
                                       { stopWhy = "센서 간격 범위 이탈 (안전 정지)"; break; }
    if (cL + cR != lastCnt) { lastCnt = cL + cR; lastMove = millis(); }
    else if (millis() - lastMove > 1000) { stopWhy = "엔코더 1초간 멈춤 (걸림/배선)"; break; }
  }
  motorStop();
  uint32_t dur = millis() - t0;
  while (Serial.available()) Serial.read();

  // 3) 결과 요약
  long cL = labs(encL), cR = labs(encR);
  float distL = cL * 300.0f / COUNTS_PER_300, distR = cR * 300.0f / COUNTS_PER_300;
  float rate = samples * 1000.0f / fmax(1, dur);

  Serial.println("\n================ 결과 ================");
  Serial.printf("정지 사유       %s\n", stopWhy);
  Serial.printf("주행 거리       %.1f mm  (좌 %.1f / 우 %.1f)   %.2f 초   평균 %.0f mm/s\n",
                dist, distL, distR, dur / 1000.0, dist * 1000.0 / fmax(1, dur));
  Serial.printf("샘플            %ld 개  (%.0f Hz)   읽기 실패 %ld\n", samples, rate, fail);
  Serial.printf("좌 간격         평균 %.3f  최소 %.3f  최대 %.3f  폭 %.3f  (정지 기준 %.3f)\n",
                gL.mean(), gL.mn, gL.mx, gL.mx - gL.mn, s0L.mean());
  Serial.printf("우 간격         평균 %.3f  최소 %.3f  최대 %.3f  폭 %.3f  (정지 기준 %.3f)\n",
                gR.mean(), gR.mn, gR.mx, gR.mx - gR.mn, s0R.mean());
  Serial.printf("좌-우 차이      평균 %+.3f  최소 %+.3f  최대 %+.3f\n",
                dLR.mean(), dLR.mn, dLR.mx);
  Serial.printf("진동(az 표준편차) 좌 %.3f g   우 %.3f g\n", vzL.sd(), vzR.sd());

  Serial.println("\n---------------- 판정 ----------------");
  bool okDist = dist >= RUN_MM * 0.98;
  bool okRead = fail == 0 && rate >= 20;
  bool okSafe = gL.mn >= GAP_SAFE_MIN && gL.mx <= GAP_SAFE_MAX &&
                gR.mn >= GAP_SAFE_MIN && gR.mx <= GAP_SAFE_MAX;
  bool okEnc  = fabs(distL - distR) <= 0.05 * fmax(distL, distR);
  bool okNoiseL = s0L.sd() < 0.01, okNoiseR = s0R.sd() < 0.01;
  Serial.printf("  [%s] 30cm 완주\n",                    okDist ? "OK" : "X ");
  Serial.printf("  [%s] 센서 읽기 실패 없음, 20Hz 이상\n", okRead ? "OK" : "X ");
  Serial.printf("  [%s] 간격이 측정 범위(%.1f~%.1f mm) 안\n", okSafe ? "OK" : "X ", GAP_SAFE_MIN, GAP_SAFE_MAX);
  Serial.printf("  [%s] 좌우 엔코더 거리 차 5%% 이내\n",  okEnc ? "OK" : "X ");
  Serial.printf("  [%s] 정지 상태 센서 흔들림 0.01mm 미만\n", (okNoiseL && okNoiseR) ? "OK" : "X ");
  Serial.printf("  종합  %s\n", (okDist && okRead && okSafe && okEnc && okNoiseL && okNoiseR)
                                ? "합격 — 시스템 정상 동작" : "확인 필요 — X 항목을 보십시오");
  Serial.println("  (간격 '폭'은 레일 상태를 그대로 보여 줍니다. 결함 없는 구간이면 작아야 정상)");
}

// ── setup ──────────────────────────────────────────────────
void setup() {
  // 모터를 가장 먼저 확실히 정지
  pinMode(IN1_L, OUTPUT); pinMode(IN2_L, OUTPUT); pinMode(ENA_L, OUTPUT);
  pinMode(IN1_R, OUTPUT); pinMode(IN2_R, OUTPUT); pinMode(ENA_R, OUTPUT);
  motorStop();

  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 5000) delay(10);   // 시리얼 모니터 연결 대기 (최대 5초)
  Serial.println("\n\n=== HP028_RailTwin 배선 점검 ===");

  busL.begin(SDA_L, SCL_L, 100000);
  busR.begin(SDA_R, SCL_R, 100000);

  scan(busL, "좌");
  scan(busR, "우");

  Serial.printf("\nWHO_AM_I   좌 0x%02X   우 0x%02X   (0x68·0x70·0x72 중 하나면 정상)\n",
                mpuWhoAmI(busL), mpuWhoAmI(busR));
  Serial.printf("MPU 초기화 좌 %s   우 %s\n",
                mpuInit(busL) ? "OK" : "실패", mpuInit(busR) ? "OK" : "실패");

  pinMode(ENCA_L, INPUT_PULLUP); pinMode(ENCB_L, INPUT_PULLUP);
  pinMode(ENCA_R, INPUT_PULLUP); pinMode(ENCB_R, INPUT_PULLUP);
  attachInterrupt(ENCA_L, isrL, RISING);
  attachInterrupt(ENCA_R, isrR, RISING);

  Serial.println(
    "\n명령 (한 글자 입력 후 엔터)\n"
    "  s  I2C 다시 스캔\n"
    "  r  센서 한 번 읽기\n"
    "  c  센서 연속 읽기 (아무 키나 누르면 정지)\n"
    "  f  양쪽 2초, 코드의 앞     b  양쪽 2초, 코드의 뒤\n"
    "  1  좌 모터 1초        2  우 모터 1초\n"
    "  g  접지 시험 (모터 켜고 센서 흔들림 측정)\n"
    "  a  센서 위치 맞춤 (목표 5.00mm)\n"
    "  k  엔코더 교정 (모터로 조금 달린 뒤 거리 입력)\n"
    "  t  30cm 주행 시험\n"
    "  0  전부 정지\n");
}

// ── loop ───────────────────────────────────────────────────
void loop() {
  if (!Serial.available()) return;
  char c = Serial.read();
  while (Serial.available()) Serial.read();   // 나머지 비우기

  switch (c) {
    case 's': scan(busL, "좌"); scan(busR, "우"); break;
    case 'r': readOnce(); break;
    case 'c':
      Serial.println("연속 읽기 — 아무 키나 누르면 정지");
      while (!Serial.available()) { readOnce(); delay(300); }
      while (Serial.available()) Serial.read();
      break;
    case 'f': driveBoth(true, 2000); break;
    case 'b': driveBoth(false, 2000); break;
    case '1':
      Serial.println("좌 모터 1초");
      encL = 0; motorRun('L', true, MOTOR_DUTY); delay(1000); motorStop();
      Serial.printf("  엔코더 %ld  (0 이면 엔코더 배선 확인)\n", encL);
      break;
    case '2':
      Serial.println("우 모터 1초");
      encR = 0; motorRun('R', true, MOTOR_DUTY); delay(1000); motorStop();
      Serial.printf("  엔코더 %ld  (0 이면 엔코더 배선 확인)\n", encR);
      break;
    case 'g': groundTest(); break;
    case 'a': alignMode(); break;
    case 'k': encoderCal(); break;
    case 't': runTest(); break;
    case '0': motorStop(); Serial.println("정지"); break;
    default: break;
  }
}
