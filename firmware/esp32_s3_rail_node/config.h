#pragma once

// ESP32-S3-DevKitC-1 N16R8 한 장. 왼쪽은 Wire(GPIO11/12), 오른쪽은 Wire1(GPIO13/14).
// 전진은 빨간 모터 기판 쪽. 2026-09-25 실물에서 f 명령으로 확인했다.
// 전진을 바라봤을 때 코드의 왼쪽이 어느 쪽인지는 아직 확정하지 않았다.

constexpr char FIRMWARE_VERSION[] = "0.6.4-draft";

constexpr int SDA_L = 11;
constexpr int SCL_L = 12;
constexpr int SDA_R = 13;
constexpr int SCL_R = 14;

constexpr int ENA_L = 4;
constexpr int IN1_L = 5;
constexpr int IN2_L = 6;
constexpr int ENA_R = 7;
constexpr int IN1_R = 8;
constexpr int IN2_R = 9;

constexpr int ENCA_L = 15;
constexpr int ENCB_L = 16;
constexpr int ENCA_R = 17;
constexpr int ENCB_R = 18;

constexpr uint8_t MPU_ADDR = 0x68;
constexpr uint8_t ADS_ADDR = 0x48;
constexpr uint16_t ADS_CFG = 0xC383;  // AIN0–GND, ±4.096V, 128SPS, 단발 시작
constexpr uint32_t ADS_WAIT_US = 8000;

constexpr float DIV = 3.0f;
constexpr float ADS_LSB = 4.096f / 32768.0f;
constexpr float G_TO_MPS2 = 9.80665f;
// MPU-6050 기본 자이로 ±250 deg/s. 131 LSB가 1 deg/s.
constexpr float GYRO_LSB_PER_DPS = 131.0f;
constexpr float MPU_DEG_TO_RAD = 0.01745329252f;
// 데이터시트: 온도(°C) = raw / 340 + 36.53
constexpr float TEMP_LSB_PER_C = 340.0f;
constexpr float TEMP_OFFSET_C = 36.53f;

// 2026-09-24 교정. 센서 출력 전압 → mm. 센서 뒤 나사를 돌리면 무효다.
constexpr int CAL_N = 5;
constexpr float CAL_MM[CAL_N] = {0.0f, 2.0f, 4.0f, 6.0f, 8.0f};
constexpr float CAL_VL[CAL_N] = {-0.010f, 0.187f, 2.044f, 5.725f, 7.592f};
constexpr float CAL_VR[CAL_N] = {0.004f, 0.242f, 2.935f, 6.546f, 8.210f};

// 300mm 시험 6034카운트. 줄자 대조 전의 잠정값.
constexpr float MM_PER_COUNT = 300.0f / 6034.0f;

// 전진(빨간 기판 쪽)에서 왼쪽 카운트는 증가, 오른쪽은 감소한다.
// 위치는 양쪽 다 전진하면 증가하도록 오른쪽에 부호를 뒤집는다.
constexpr int POS_SIGN_L = 1;
constexpr int POS_SIGN_R = -1;

// 2026-09-25 책상 위 2초 주행은 듀티 120에서 약 2.4cm/s 였다. 레일 위 속도는 아직 줄자로 재지 않았다.
constexpr uint8_t DUTY_CRUISE = 120;
constexpr uint8_t DUTY_SLOW = 60;

// DevKitC-1의 BOOT 버튼은 GPIO0.
// 300 cm 레일에서 출발 자세의 구동바퀴 접점은 왼쪽 끝에서 58 cm다.
// 그 접점이 오른쪽 끝에 닿으면 왼쪽 엔코더는 242 cm다.
// BOOT 전진은 왼쪽이 242 cm가 되거나 72초가 되면 멈춘다.
// RST와 같이 누르면 다운로드 모드라서, 주행 버튼으로 쓰지 않는다.
constexpr int PIN_BOOT = 0;
constexpr uint32_t BUTTON_RUN_MS = 72000;
constexpr float BUTTON_STOP_MM = 2420.0f;
constexpr uint32_t BUTTON_DEBOUNCE_MS = 250;

// 중력(각 칩의 정지 오프셋)을 뺀 세로 가속도가 이 값을 넘으면 통신과 상관없이 멈춘다.
constexpr float SHOCK_MPS2 = 4.0f;
constexpr float Z_OFFSET_L_G = 1.07f;
constexpr float Z_OFFSET_R_G = 1.00f;

// 좌·우를 같은 시각에 한 쌍으로 읽는다. ADS 변환 대기 때문에 50Hz.
constexpr uint32_t SAMPLE_INTERVAL_US = 20000;
constexpr int SAMPLES_PER_BATCH = 10;

constexpr char MQTT_HOST[] = "223.130.128.198";
constexpr uint16_t MQTT_PORT = 1883;

constexpr char DEVICE_L[] = "rail-left-01";
constexpr char DEVICE_R[] = "rail-right-01";
constexpr char TOPIC_TEL_L[] = "rail/v1/nodes/rail-left-01/telemetry";
constexpr char TOPIC_TEL_R[] = "rail/v1/nodes/rail-right-01/telemetry";
constexpr char TOPIC_STA_L[] = "rail/v1/nodes/rail-left-01/status";
constexpr char TOPIC_STA_R[] = "rail/v1/nodes/rail-right-01/status";
constexpr char TOPIC_CMD_L[] = "rail/v1/nodes/rail-left-01/command";
constexpr char TOPIC_CMD_R[] = "rail/v1/nodes/rail-right-01/command";
