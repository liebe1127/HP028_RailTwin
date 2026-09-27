# 핵심 기술스택과 작업 절차 — Tech Stack & Workflow (AI 학습용)

> 용도: Gemini, ChatGPT, Claude, Cursor 등 생성형 AI에 **업로드하거나 대화 시작 시 첨부**하여 프로젝트의 기술스택·데이터 계약·작업 절차·금지 사항을 학습시킨다.  
> 기준일: 2026-08-30. 하드웨어 서술은 2026-09-24 인수인계서 기준이다.  
> 프로젝트 약칭: RailTwin / 스마트해운물류

이 문서는 **사실 기준서**가 아니라 **AI 온보딩서**다. 세부 사실·일정·진척도는 아래 관련 문서를 우선한다. 내용이 충돌하면 **사용자가 직접 확정한 최신 내용**을 따른다.

---

## 0. 이 파일을 AI에 넣는 방법

### 파일을 Finder에서 집는 방법 (공유)

경로를 손으로 찾지 말고 아래 버튼을 더블클릭한다. Finder가 열리고 이 md가 선택된 상태로 나온다. 그 파일을 Gemini·ChatGPT 채팅창에 드래그하면 된다.

- [Finder에서 docs 폴더 열기 / Open docs folder](Finder에서_이폴더열기_Open-Docs-Folder.command)

처음 더블클릭할 때 macOS가 “개발자를 확인할 수 없음”을 띄우면 우클릭 → 열기를 한 번 허용한다.

### Gemini / ChatGPT / Claude

1. 위 버튼으로 Finder를 연 뒤, 이 파일을 채팅창에 드래그해 업로드한다.
2. 작업 종류에 따라 아래 관련 문서를 **함께** 업로드한다.
3. 다음 문장을 첫 메시지로 붙인다.

```text
첨부한 "핵심기술스택과_작업절차_AI학습용_Tech-Stack-and-Workflow.md"를 이 프로젝트의 기술스택·용어·작업 절차 기준으로 학습해줘.
이후 답변과 코드·문서 초안은 이 파일의 금지 사항과 표준 식별자를 지킨다.

추가 원칙:
- 핵심 예측 대상은 갠트리 크레인 하부 주행 레일의 단차·국부 침하·뒤틀림이다.
- 거더 처짐, deflection, PRED_DEFLECTION을 쓰지 않는다.
- 현재 하드웨어는 ESP32-S3-DevKitC-1 N16R8 1장 + 좌·우 각 MPU-6050, ADS1115, GTRIC LR18-08U이다.
- ESP32-C3 Mini 두 노드는 저장소의 이전 펌웨어이다. ESP32-S3-WROOM-1 + ADXL345 + HC-SR04만 취소된 초기 프로토타입이다.
- AI 추론(RBF)·웨이블릿·파고율은 쓰지 않는다. 간격+롤 규칙으로 이상 구간을 표시한다.
- 3D는 Unity WebGL 레일만. Godot·크레인 메시는 현재 범위가 아니다.
- 합성 데이터·더미 스트리머와 실측 결과를 구분한다.
- 근거 없는 성능 수치·회로값·WSS 성공을 만들지 않는다. 모르면 [확인 필요]로 남긴다.
```

### Cursor

새 채팅에서 이 파일과 필요한 기준 문서를 `@`로 첨부한 뒤 위와 같은 원칙을 적어 시작한다. Cursor 작업 규칙은 `.cursor/rules/rail-deformation-context.mdc`가 항상 적용된다.

Mac에서 Unity Hub·WebGL·대시보드를 처음 붙일 때는 [`mac-m5-unity-onboarding.md`](mac-m5-unity-onboarding.md)를 함께 첨부한다.

### 작업별 추가 첨부

| 하려는 일 | 함께 올릴 파일 |
|---|---|
| 코드·기능 구현 | `README.md`, `docs/esp32-mqtt-contract.md`, 해당 소스 |
| 하드웨어·펌웨어 | `docs/hardware-configuration-history.md`, `firmware/esp32_c3_rail_sensor/README.md` |
| 사실 확인·현황 | `docs/notion-project-context.md` |
| 공식 개발보고서 | `docs/development-report-ai-handoff.md`와 그 안의 첨부 목록 |
| 배포 | `docs/ncp-docker-deploy.md`, `.env.example` |

---

## 1. 프로젝트 한 줄 정의

대형 갠트리 크레인이 **하부 주행 레일**을 따라 이동할 때 생기는 간격·충격·기울기·위치 데이터로, 이음부 단차·수직 변형·좌우 높이차를 표시하는 디지털 트윈 안전관리 시스템이다.

센서가 기록하는 이름은 레일 기하(수직 변형 포함)다. 거더 변형은 그 원인 중 하나다.

목표 데이터 흐름:

```text
ESP32-S3-DevKitC-1 1장 (좌·우 MPU-6050 · ADS1115 · GTRIC LR18-08U · 내장 엔코더)
  → 브링업은 USB 시리얼. 서버 계약은 MQTT QoS 1 (NCP Mosquitto)
  → FastAPI (m, Δ, dm/dx, dΔ/dx, apeak, φ → defects · stage · motion)
  → InfluxDB + WebSocket
  → 웹 대시보드 + Unity WebGL 레일 (distance_x, rail_risk)
  → MQTT command (cruise / slow / stop)
```

---

## 2. 정보 적용 우선순위

내용이 충돌할 때 이 순서를 따른다.

1. 사용자가 직접 확정한 최신 내용
2. `.cursor/rules/rail-deformation-context.mdc`와 이 문서
3. `docs/notion-project-context.md`
4. `docs/hardware-configuration-history.md`
5. 저장소의 현재 구현
6. 취소된 프로토타입과 과거 문서

과거 구현이 저장소에 남아 있다는 이유만으로 현재 하드웨어나 최종 성과로 서술하지 않는다.

---

## 3. 핵심 기술스택 — Tech Stack

### 3.1 엣지 · 하드웨어 (Edge / Hardware)

| 구분 | 현재 기준 | 비고 |
|---|---|---|
| MCU | ESP32-S3-DevKitC-1 N16R8 1장 | 좌 `Wire` GPIO11/12, 우 `Wire1` GPIO13/14 |
| 관성 센서 | MPU-6050 ×2 | 브링업은 가속도 ±2g, DLPF 44Hz. 자이로 미사용 |
| 외부 ADC | ADS1115 ×2, 주소 0x48 | AIN0 단발, 128SPS. 루프 20ms 초과 |
| 거리 센서 | GTRIC LR18-08U ×2 | 0–10V, 1–8mm. 20k/10k 분압, 목표 간격 5.00mm |
| 위치 | JGB37-520 내장 엔코더 | A상 상승 에지. 잠정 약 0.0497 mm/카운트 |
| 구동 | L298N ×2, A채널만 | ENA 점퍼 제거. 좌 모터 출력 교차 |
| 전원 | 18650 ×9, MT3608 ×2 | 로직 USB-C, 센서 24V 목표, 모터 3S |

GTRIC 0–10V 출력은 ADS1115에 **직접 연결하지 않는다**. 설계 분압은 20kΩ/10kΩ이다. Ω 실측과 전원 전압 실측은 `[확인 필요]`다. 100nF는 미장착이다.

**저장소에 남은 이전 펌웨어 (조립 실물이 아님)**

- `firmware/esp32_c3_rail_sensor/`: ESP32-C3 Mini 두 장, `rail-left-01` / `rail-right-01`, MQTT, 100Hz/20Hz
- 핀맵이 위 표와 다르다. 현재 보드에 그대로 올리지 않는다

**취소된 초기 프로토타입 (현재 구성으로 쓰지 말 것)**

- MCU: ESP32-S3-WROOM-1. 현재 보드인 DevKitC-1 N16R8와 다르다
- 가속도: ADXL345
- 거리: HC-SR04
- 그 스케치는 2026-09-27에 저장소에서 삭제했다.
- 과거 필드: `AAX`, `DIST`, `MAX` 계열

### 3.2 펌웨어 (Firmware)

- 조립 실물 브링업: Arduino C++, 보드 `ESP32S3 Dev Module`, 스케치 `RailTwin_BringUp.ino` (저장소 밖), IDE 1.8.19, COM8
- 저장소 경로 `firmware/esp32_c3_rail_sensor/`는 이전 C3 두 노드 MQTT 펌웨어이다. 아래 항목은 그 코드의 설명이다
- 라이브러리: Adafruit ADS1X15, Adafruit MPU6050, Adafruit Unified Sensor, ArduinoJson, ESP32MQTTClient
- 전송: WiFi → MQTT QoS 1 → NCP Mosquitto. USB 시리얼은 진단용
- 배치: IMU 샘플 10개를 JSON 배치로 전송 (공칭 10 Hz)
- 좌·우 프로필: `node_profile.left.h.example` / `node_profile.right.h.example` → 로컬 `node_profile.h` (Git 무시)
- 비밀: `secrets.h.example` → `secrets.h` (WiFi·해당 보드 MQTT 비밀번호)
- 거리 추정 플래그 `NODE_ENABLE_LINEAR_DISTANCE_ESTIMATE`는 교정 전까지 비활성

좌 프로필을 양쪽 보드에 올리지 않는다. `device_id`와 MQTT username이 같다.

### 3.3 백엔드 · 스트림 (Backend / Stream)

| 항목 | 기술 |
|---|---|
| 언어 | Python 3 |
| API | FastAPI, Uvicorn |
| 센서 업링크 | MQTT (`paho-mqtt`), QoS 1, 토픽 `rail/v1/nodes/{device_id}/telemetry` · `/status` |
| 화면 다운링크 | WebSocket `/ws` |
| 큐 | 비동기 Producer–Queue–Consumer |
| 시계열 | InfluxDB (`influxdb-client[async]`), Flux |
| 설정 | `python-dotenv`, `.env` |
| 시연 | `DEMO_MODE=true` 더미 스트리머 (1 m, 이음부 20–25 cm, 수직 45–70 cm, 좌우 높이 80–90 cm, 시뮬레이션 표기) |

핵심 파일:

- `main.py` — 수집, 4분류 판정, InfluxDB, WebSocket, 속도 명령, 더미 스트리머
- `sensor_contract.py` — 업링크 JSON 검증·정규화
- `frontend/index.html` — 웹 대시보드
- `godot/rail_twin_websocket.gd` — Godot 수신 스크립트

주요 함수·식별자:

| 용도 | 이름 |
|---|---|
| 결함 목록 | `defects` |
| 예측값 변수 | (사용 안 함) |
| WebSocket 키 | `defects`, `defect_type`, `stage`, `motion`, `m_mm`, `delta_mm`, `apeak`, `tilt_deg` |
| InfluxDB 필드 | `m_mm`, `delta_mm`, `apeak`, `tilt_deg`, `abnormal_score` |
| 학습 타겟 | (RBF 제외. 판정은 규칙) |
| 파고율 | 사용 안 함. 충격은 `apeak` |
| 위치 (화면) | `distance_x` (cm, `position_mm`에서 변환) |
| 구간 이상 | `rail_risk` |

`deflection`, `처짐`, `PRED_DEFLECTION`을 새로 쓰지 않는다.

Python 의존성 (`requirements.txt`): FastAPI, Uvicorn, influxdb-client, python-dotenv, paho-mqtt, numpy.

### 3.4 규칙 판정

웨이블릿·파고율·RBF는 쓰지 않는다. 처리 순서:

1. 주행 중 좌·우 간격·세로 가속도·기울기·위치 수집
2. 엣지 임계값으로 정지 노이즈 억제. 세로 충격이 크면 ESP32가 직접 정지
3. 약 50mm 구간마다 `m`, `Δ`, `dm/dx`, `dΔ/dx`, `apeak`, `φ` 계산
4. 이음부 단차 / 수직 변형 / 좌우 높이차와 정상·주의·위험 단계를 `defects`로 표시

| 항목 | 내용 |
|---|---|
| 엔진 | `rail_defect.py` 규칙 |
| 근거 | `m_mm`, `delta_mm`, `dm_dx`, `ddelta_dx`, `apeak`, `tilt_deg` |
| 동작 | `motion` = `cruise` / `slow` / `stop` |

### 3.5 프론트엔드 · 디지털 트윈 (Frontend / Digital Twin)

| 구분 | 기술 | 역할 |
|---|---|---|
| 웹 대시보드 | HTML, Vanilla JS, Tailwind CSS | 센서값, 여섯 특징, 분류·단계, 장치·서버 상태 |
| 3D 트윈 | Unity WebGL | `distance_x`로 위치, `rail_risk`로 정상·주의·위험 색 |
| 구간 색 | 초록–노랑–빨강 | 정상 → 주의 → 위험 |

저장소의 Godot 스크립트는 이력이다. 현재 화면은 Unity WebGL(레일만) 또는 브라우저 레일 뷰다.

구매한 상용 DGCRANE 모델(디지털 시각화)과 Blender 단순화 평판·하드보드 물리 모형은 **다른 트랙**이다. 동일 모델처럼 쓰지 않는다.

### 3.6 인프라 · 협업 (Infra / Collaboration)

| 항목 | 기술 |
|---|---|
| 컨테이너 | Docker, `docker-compose.yml`, `docker-compose.https.yml` |
| MQTT 브로커 | Eclipse Mosquitto 2 |
| 클라우드 | 네이버 클라우드 (NCP). 운영 IP 예: `223.130.128.198` |
| CI 배포 | GitHub Actions `.github/workflows/deploy-ncp.yml` |
| 문서·일정 | Notion |
| 코드 | GitHub |
| 로컬 규칙 | `.cursor/rules/rail-deformation-context.mdc` |

운영 주소 (문서 기준, 실제 접속 성공은 별도 검증):

- 대시보드: `https://223.130.128.198:8000/dashboard`
- Godot / 화면 WS: `wss://223.130.128.198:8000/ws`
- ESP32 MQTT: `mqtt://223.130.128.198:1883`

HTTPS 페이지에서 비암호화 WebSocket이 차단된 이력이 있다. 문서의 WSS 주소를 실제 연동 성공으로 확대하지 않는다.

---

## 4. 데이터 계약 요약 — Data Contract

자세한 스키마는 `docs/esp32-mqtt-contract.md`를 따른다. 계약 버전 `schema_version=1`.

### 업링크 (ESP32 → MQTT → FastAPI)

주요 필드: `type`, `schema_version`, `device_id`, `rail_side`, `firmware_version`, `boot_id`, `batch_seq`, `sample_seq`, `uptime_us`, `dropped_batches`, `position_mm`, `sensor_distance_mm`, `adc_raw`, `adc_voltage_v`, `sensor_voltage_v`, `accel_mps2[3]`, `gyro_radps[3]`.

- 왼쪽: `device_id=rail-left-01`, `rail_side=left`
- 오른쪽: `device_id=rail-right-01`, `rail_side=right`
- FastAPI MQTT 계정: `railtwin-backend` (구독만)

### 다운링크 (FastAPI → 웹 / Godot)

`ts`, `distance_x`, `CREST`, `PRED_RAIL_DEFORM`, `rail_risk`, `rail_length_cm`, `segment_count`, 그리고 장치·전송 추적 필드. 좌·우는 화면 WebSocket의 `left` · `right` 객체로 구분한다.

`MIRROR_RIGHT_TO_LEFT=true`이면 한쪽만 있을 때 반대쪽에 복제할 수 있다. 시연용이며 실측 좌·우 독립 계측과 혼동하지 않는다.

---

## 5. 저장소 지도 — Repository Map

```text
main.py                          FastAPI 서버 (수집·특징·추론·WS·Influx)
sensor_contract.py               MQTT JSON 계약 검증
frontend/index.html              웹 대시보드
godot/rail_twin_websocket.gd     Godot WS 수신
ml/train_rbf_surrogate.py        합성 RBF 학습
ml/export_synthetic_training_figures.py
firmware/esp32_s3_rail_node/     조립 실물 펌웨어
tests/                           파이프라인·계약·MQTT·프로필 시험
deploy/mosquitto/                브로커 설정
docs/                            기준 문서·증빙 그림
legacy/serial_receiver.py        과거 시리얼 수신 (현재 주경로 아님)
```

현재 펌웨어는 `firmware/esp32_s3_rail_node/`이다.

---

## 6. 작업 절차 — Work Procedures

### 6.1 공통 시작 절차

어떤 도구(Gemini, ChatGPT, Cursor)를 쓰든 아래를 먼저 한다.

1. 이 문서의 금지 사항·표준 식별자·현재 하드웨어를 확인한다.
2. 작업 종류에 맞는 기준 문서를 읽는다.
3. **구현 완료 / 구현·미검증 / 미실시 / 계획**을 섞어 쓰지 않는다.
4. 합성·더미와 실측을 한 문장 안에서 같은 성과처럼 쓰지 않는다.
5. 모르면 추측하지 않고 `[확인 필요]`로 남긴다.

상태 칸 뜻:

| 상태 | 뜻 |
|---|---|
| 구현·확인 | 코드 또는 실물이 있고, 사용자 확인 또는 로그·시험으로 동작이 확인됨 |
| 구현·미검증 | 코드·조립은 있으나 실측·장시간·운영 WSS 등 증빙이 없음 |
| 미실시 | 계획만 있거나 아직 하지 않음 |
| 계획 | 백로그·2차 평가 이후 항목 |

### 6.2 Cursor에서 코드·기능을 구현할 때

1. `.cursor/rules/rail-deformation-context.mdc`가 이미 적용되어 있다고 가정한다.
2. 센서·필드·하드웨어를 건드리면 `docs/hardware-configuration-history.md`와 `docs/esp32-mqtt-contract.md`를 읽는다.
3. 표준 식별자(`predict_rail_deform`, `PRED_RAIL_DEFORM` 등)를 유지한다.
4. 웹 UI를 바꾸면 가능한 범위에서 브라우저로 동작을 확인한다.
5. 사용자가 커밋을 요청하기 전에는 `git commit`하지 않는다.
6. 공식 개발보고서 초안(`docs/2026_스마트해운물류_개발보고서_초안.md`)은 **사용자가 보고서 작업을 요청했을 때만** 수정한다.

로컬 실행 순서:

```text
1. firmware/esp32_c3_rail_sensor/ 에서 secrets.h, node_profile.h 설정
2. cp .env.example .env  (비밀번호·DEMO_MODE 설정)
3. python3 ml/train_rbf_surrogate.py   → rbf_dummy_model.pth
4. uvicorn main:app --host 0.0.0.0 --port 8000
5. 실물 입력은 DEMO_MODE=false, 시연은 DEMO_MODE=true
```

좌·우 펌웨어 업로드:

```text
cp node_profile.left.h.example node_profile.h   → 왼쪽 보드 컴파일·업로드
cp node_profile.right.h.example node_profile.h  → 오른쪽 보드 컴파일·업로드
시리얼 부팅 배너로 device_id · rail_side 확인
```

### 6.3 Gemini가 설계하고 Cursor가 구현할 때 (Gemini ↔ Cursor 루프)

역할 분담:

- **Gemini**: 설계, 절차, Cursor에 붙여 넣을 구현 프롬프트, 보고서 문장 검토
- **Cursor**: 저장소의 실제 코드·파일 수정, 린트, 로컬 검증
- **사용자**: Gemini 출력을 Cursor에 전달하고, Cursor 결과를 Gemini에 다시 보고

권장 순서:

1. Gemini에 이 파일(+ 필요 시 관련 문서)을 학습시킨다.
2. Gemini에게 **구현이 아니라 Cursor 입력용 프롬프트**를 달라고 한다. 프롬프트에는 고칠 파일, 금지 사항, 완료 조건을 넣는다.
3. 사용자는 Cursor 채팅에 그 프롬프트를 붙여 넣는다.
4. Cursor는 요청된 구현만 수행하고, 변경 파일을 짧게 설명한다.
5. 사용자가 요청하면 Cursor는 아래 형식으로 Gemini 보고용 요약을 만든다. 이전 보고 이후 변경만 적는다.

```text
## 추가 진행 상황 요약 (Gemini 보고용)

---

**추가 작업:** [한 줄]

**생성/수정 파일:** `파일명` [신규 생성 / 수정]

---

**구현 내용**
- 항목

---

**현재 상태**

| 항목 | 상태 |
|---|---|
| 기능 A | 완료 |
| 이번에 끝난 기능 | **완료** |
| 다음 기능 | 미구현 — 다음 단계 |
```

Gemini에게 코드를 직접 다시 짜게 하지 말고, Cursor가 고친 파일 목록과 요약만 넘기는 편이 충돌이 적다.

### 6.4 ChatGPT로 공식 개발보고서를 이식할 때

제출 양식의 기준은 Markdown이 아니라 주최 측 **공식 11쪽 PDF**다.

1. Cursor에서 사실 원고를 `docs/2026_스마트해운물류_개발보고서_초안.md`에 맞춘다.
2. ChatGPT에 PDF와 기준 문서를 업로드한다. 절차·프롬프트는 `docs/development-report-ai-handoff.md`, 복사 프롬프트는 `docs/development-report-chatgpt-transfer-prompt.md`.
3. 공식 항목명·순서·표 구조를 변경·삭제하지 않는다.
4. 작품 개요와 작품 구성도는 각각 1쪽이다.
5. 팀원 세부목표 표에는 블라인드 평가원칙에 따라 **실명을 쓰지 않는다**.
6. ChatGPT 결과를 다시 Cursor·저장소·사용자 확인과 대조한다.
7. `[확인 필요]`를 임의로 채우지 않는다.

### 6.5 현황·진척도를 물을 때

대화용 현황과 공식 보고서 원고를 섞지 않는다. 현황은 구현 여부만 말하고, 공식 PDF 항목을 재구성하지 않는다.

반드시 구분할 것:

- 합성 데이터·더미 스트리머 ≠ 실측 성능
- 저장소 C3 펌웨어 ≠ 조립된 ESP32-S3 브링업
- 전체 모형 조립 ≠ 반복 주행·라벨 데이터 수집
- 문서화된 WSS 주소 ≠ 실제 접속 성공
- Notion 완료 체크 ≠ 실물 검증

2026-09-25 사용자 확인: ESP32-S3 실물 조립이 끝났고, 브링업에서 I2C·금속 반응·모터·30cm 주행을 확인했다. **반복 주행 시험과 실측 데이터 저장은 미실시.** 2026-08-23의 ESP32-C3 두 노드 확인은 그 전 기록이다.

### 6.6 문서·그림·발표 자료를 만들 때

1. 개발보고서·프로젝트 설명 전에는 `docs/notion-project-context.md`를 읽는다.
2. 공식 보고서 항목은 `docs/development-report-template-map.md` 순서를 유지한다.
3. 상용 3D 자산·비공개 링크를 공개 저장소나 보고서에 노출하지 않는다.
4. 사진에서 보이는 것만 설명한다. 보이지 않는 저항값·전압·동작 성공을 추측하지 않는다.
5. 구동륜 도면은 답면 47mm, 플랜지 외경 53mm이다. 과거 7cm 도면과 구분한다. 출력품 실측은 미확인이다.

---

## 7. 용어 규칙 — Terminology

| 쓰지 말 것 | 대신 쓸 것 |
|---|---|
| 거더 처짐, 크레인 처짐, deflection | 레일 변형, 단차/침하/뒤틀림, rail_deform |
| PRED_DEFLECTION, PRED_RAIL_DEFORM | `defects[]` |
| 막연한 "상태(변위·틸트)" | 주행 시 간격·기울기·위치 데이터 |
| ESP32-S3-WROOM-1 + ADXL345 + HC-SR04를 현재 보드처럼 | 취소된 초기 프로토타입. 현재 MCU는 DevKitC-1 N16R8 1장 |
| ESP32-C3 두 장을 조립 실물처럼 | 저장소에 남은 이전 펌웨어 |
| 합성 MAE를 현장 정확도처럼 | 합성 파이프라인 검증 수치 (실측 아님) |
| Godot가 현재 엔진 | Unity WebGL 레일 |

---

## 8. AI가 하지 말 것 — Do Not

- 거더 처짐을 핵심 타겟으로 설명·구현하기
- `deflection` / `처짐` / `PRED_DEFLECTION`을 새로 만들기
- ESP32-S3-WROOM-1 · ADXL345 · HC-SR04를 현재 구성으로 쓰기
- ESP32-C3 Mini 두 장을 2026-09-24 조립 실물로 쓰기
- 원시 센서값을 RBF에 바로 넣는다고 쓰기
- 근거 없는 정확도·사고 예방 효과·비용 절감률 만들기
- 분압 저항·보호소자·측정전압을 자료 없이 확정하기
- 문서의 WSS 주소를 실제 연동 성공으로 단정하기
- 구매 상용 3D 모델과 물리 모형을 같은 모델로 쓰기
- 사용자가 요청하지 않은 `git commit` / `git push`
- 공식 PDF 항목명·순서·표를 독자 목차로 바꾸기
- 개발보고서 역할표에 실명 넣기 (블라인드 평가)
- `.env`, `secrets.h`, MQTT 비밀번호를 문서나 채팅에 그대로 적기

---

## 9. 관련 기준 문서 — Related Canonical Docs

| 파일 | 역할 |
|---|---|
| `.cursor/rules/rail-deformation-context.mdc` | Cursor 상시 용어·타겟 규칙 |
| `docs/notion-project-context.md` | 사실·일정·진척도 통합 문맥 |
| `docs/hardware-configuration-history.md` | 현재 센서 vs 취소 프로토타입 |
| `docs/esp32-mqtt-contract.md` | MQTT 업링크 계약 |
| `docs/esp32-websocket-contract.md` | 화면 WebSocket 계약 |
| `docs/development-report-ai-handoff.md` | 보고서 Cursor·ChatGPT 인계 |
| `docs/development-report-chatgpt-transfer-prompt.md` | ChatGPT 복사 프롬프트 |
| `docs/development-report-template-map.md` | 공식 PDF 항목·순서 |
| `docs/2026_스마트해운물류_개발보고서_초안.md` | PDF에 넣을 작업 원고 |
| `docs/ncp-docker-deploy.md` | NCP Docker 배포 |
| `README.md` | 실행 방법·스택 요약 |

원본 Notion ZIP과 공식 PDF는 저장소 밖에 있을 수 있다. 클라우드 에이전트는 로컬 `docs/` 기준 문서를 사용한다.
