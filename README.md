![하부 레일 변형 예측 기반 갠트리 크레인 디지털 트윈 안전관리 시스템 아키텍처](docs/system-architecture.png)

# 가변 계측–레일 변형 디지털 트윈 기반 갠트리 크레인 예측 안전관리 시스템

## 프로젝트 소개

본 프로젝트는 대형 갠트리 크레인 주행 시 발생하는 동적 진동 및 가속도 데이터를 실시간으로 계측하고, AI 예측 모델을 통해 하부 주행 레일의 미세 변형(단차, 국부적인 침하, 뒤틀림 등)을 사전에 예측하여 감지하는 디지털 트윈 기반의 안전관리 시스템을 구축하는 것을 목표로 합니다. 엣지 컴퓨팅(ESP32-C3 Mini) 단말에서 수집된 신호의 노이즈를 걸러내는 특징 공학 파이프라인과 PyTorch 기반 RBF(Radial Basis Function) 대리 모델을 결합하여, 복잡한 연산을 대체하고 레일의 위험 상태를 3D로 시각화하는 초저지연 모니터링 환경을 제공합니다.

> **핵심 타겟:** 거더(상단 구조) 처짐이 아니라, **하부 주행 레일의 변형(단차·침하·뒤틀림)** 예측입니다.

## 팀원 및 담당 역할

* **배용진:** SENSOR & EDGE (엣지 컴퓨팅 및 센서 데이터 획득/전처리)
* **배준호:** BACKEND & REAL-TIME DATA STREAM / AI PREDICTIVE MODEL (비동기 백엔드, 데이터 스트림 구축 및 PyTorch RBF 레일 변형 예측 엔진 구현)
* **김병서:** DIGITAL TWIN & WEB VIEW (1:1 스케일 물리 모델 매핑 및 웹/3D 기반 실시간 레일 위험 상태 시각화)

## 사용 하드웨어 및 기술 스택

* **현재 하드웨어 (Edge):** ESP32-C3 Mini, MPU-6050(6축 자이로/가속도), ADS1115(외부 ADC), GTRIC M18 아날로그 유도형 근접 센서.
* **하드웨어 이력:** ESP32-S3·ADXL345·HC-SR04 구성과 기존 펌웨어는 취소된 초기 프로토타입이며 현재 구성에 사용하지 않습니다. 자세한 구분은 [`docs/hardware-configuration-history.md`](docs/hardware-configuration-history.md)를 참조하세요.
* **백엔드 & 스트림:** Python, FastAPI, InfluxDB, ESP32 센서 업링크 WebSocket, 웹·Godot 다운링크 WebSocket.
* **AI 모델:** PyTorch, RBF(Radial Basis Function) 기반 대리 모델 (입력: 진동/가속도 특징 + 파고율 등).
* **특징 공학:** 웨이블릿(`sym3`) 디노이징, 파고율(Crest Factor) 추출 — 레일 단차 충격 특징 강조.
* **프론트엔드 / 디지털 트윈:** HTML/Vanilla JS, Tailwind CSS, Godot 3D (시연·시각화).

## 시스템 아키텍처 및 개발 로드맵

프로젝트는 총 4개의 Phase로 나뉩니다. 현재 ESP32-C3 WiFi WebSocket 수집, 현재 센서용 RBF 추론, InfluxDB 저장, 시연용 더미 스트리머와 시각화가 구현되어 있습니다.

### Phase 1: Sensor & Edge (펌웨어 구현, 실물 교정·검증 필요)

* ESP32-C3 Mini와 MPU-6050, ADS1115, GTRIC M18 센서를 결합한 최종 센서 모듈 구성.
* MPU6050 100Hz, ADS1115 20Hz 수집 후 10개 샘플을 WebSocket JSON 배치로 전송.
* GTRIC 센서의 실제 출력과 분압 회로, 엔코더 회전당 계수는 실측 후 펌웨어 설정에 반영.
* 저장소의 ESP32-S3·ADXL345·HC-SR04 펌웨어는 과거 작업 열람용으로만 보존.

### Phase 2: Backend & Real-Time Data Stream (프로토타입 완료, 고도화 예정)

* **센서 업링크:** ESP32-C3 → WiFi → `/ws/sensor` → FastAPI 비동기 Queue.
* **분석 다운링크:** FastAPI → `/ws` → 웹 대시보드 / Godot.
* **시연:** `DEMO_MODE=true`일 때 1m 레일·40~50cm 단차 충격 더미 스트리머(10Hz)로 파이프라인 검증.

### Phase 3: Real-Time AI Predictive Model (진행 중)

* PyTorch RBF 대리 모델로 레일 변형 위험 지표를 실시간 추론.
* 웨이블릿 노이즈 제거 + 파고율 등 특징 공학 후 모델 입력 (원시 센서값 직입력이 아님).
* 위험 구간(단차 충격)에서 파고율이 임계치 이상으로 상승하는 시연 시나리오 검증 완료.

### Phase 4: Digital Twin & Web View (진행 중)

* WebSocket 연동 실시간 웹 대시보드 프로토타입 구축.
* Godot 3D 디지털 트윈에서 레일 위치(`distance_x`)·위험도(파고율/예측값)를 시각화.

## 프로토타입 실행 방법 (Getting Started)

1. **펌웨어 설정:** `firmware/esp32_c3_rail_sensor/`에서 `secrets.h.example`을 `secrets.h`로 복사하고 WiFi·센서 토큰·인증서를 설정합니다.
2. **과거 펌웨어 열람:** `firmware/crane_sensor/crane_sensor.ino`는 취소된 ESP32-S3·ADXL345·HC-SR04 프로토타입의 기록이며 현재 장치에 업로드하지 않습니다.
3. **환경 설정:** `.env.example`을 `.env`로 복사하고 ESP32와 같은 `SENSOR_AUTH_TOKEN`을 사용합니다. 실물 입력은 `DEMO_MODE=false`입니다.
4. **모델 학습 (최초 1회):** `python3 ml/train_rbf_surrogate.py` → `rbf_dummy_model.pth` 생성.
5. **백엔드 가동:** `uvicorn main:app --host 0.0.0.0 --port 8000`
6. **센서/화면 접속:** ESP32는 `ws(s)://서버/ws/sensor`, 대시보드와 Godot는 `ws(s)://서버/ws`를 사용합니다.

## 개발보고서 및 AI 인계

* **ESP32 WebSocket 계약:** [`docs/esp32-websocket-contract.md`](docs/esp32-websocket-contract.md)
* **공식 PDF 양식 항목표:** [`docs/development-report-template-map.md`](docs/development-report-template-map.md)
* **프로젝트 통합 문맥:** [`docs/notion-project-context.md`](docs/notion-project-context.md)
* **센서 하드웨어 변경 이력:** [`docs/hardware-configuration-history.md`](docs/hardware-configuration-history.md)
* **Cursor·ChatGPT 인계 프롬프트:** [`docs/development-report-ai-handoff.md`](docs/development-report-ai-handoff.md)
