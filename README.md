![갠트리 크레인 예측 안전관리 시스템 아키텍처](docs/system-architecture.png)

# 가변 계측–레일 변형 디지털 트윈 기반 갠트리 크레인 예측 안전관리 시스템

## 프로젝트 소개

본 프로젝트는 대형 갠트리 크레인 주행 시 발생하는 동적 진동 및 가속도 데이터를 실시간으로 계측하고, AI 예측 모델을 통해 하부 주행 레일의 미세 변형(단차, 국부적인 침하, 뒤틀림 등)을 사전에 예측하여 감지하는 디지털 트윈 기반의 안전관리 시스템을 구축하는 것을 목표로 합니다. 엣지 컴퓨팅(ESP32-S3) 단말에서 수집된 신호의 노이즈를 걸러내는 특징 공학 파이프라인과 PyTorch 기반 RBF(Radial Basis Function) 대리 모델을 결합하여, 복잡한 연산을 대체하고 레일의 위험 상태를 3D로 시각화하는 초저지연 모니터링 환경을 제공합니다.

> **핵심 타겟:** 거더(상단 구조) 처짐이 아니라, **하부 주행 레일의 변형(단차·침하·뒤틀림)** 예측입니다.

## 팀원 및 담당 역할

* **배용진:** SENSOR & EDGE (엣지 컴퓨팅 및 센서 데이터 획득/전처리)
* **배준호:** BACKEND & REAL-TIME DATA STREAM / AI PREDICTIVE MODEL (비동기 백엔드, 데이터 스트림 구축 및 PyTorch RBF 레일 변형 예측 엔진 구현)
* **김병서:** DIGITAL TWIN & WEB VIEW (1:1 스케일 물리 모델 매핑 및 웹/3D 기반 실시간 레일 위험 상태 시각화)

## 사용 하드웨어 및 기술 스택

* **하드웨어 (Edge):** ESP32-S3-WROOM-1 듀얼 코어 보드, MPU-6050(6축 자이로/가속도), ADXL345(가속도), HC-SR04(초음파 거리), SW-420(진동), ACS712(전류).
* **백엔드 & 스트림:** Python, FastAPI, Redis (향후), InfluxDB (시계열 데이터 저장), WebSocket, pyserial (프로토타입용).
* **AI 모델:** PyTorch, RBF(Radial Basis Function) 기반 대리 모델 (입력: 진동/가속도 특징 + 파고율 등).
* **특징 공학:** 웨이블릿(`sym3`) 디노이징, 파고율(Crest Factor) 추출 — 레일 단차 충격 특징 강조.
* **프론트엔드 / 디지털 트윈:** HTML/Vanilla JS, Tailwind CSS, Godot 3D (시연·시각화).

## 시스템 아키텍처 및 개발 로드맵

프로젝트는 총 4개의 Phase로 나뉘어 진행됩니다. 현재 시리얼 직결 프로토타입, RBF 추론, 시연용 더미 스트리머까지 구현된 상태입니다.

### Phase 1: Sensor & Edge (진행 완료)

* ESP32-S3와 ADXL345, MPU-6050, HC-SR04 핀 매핑 및 펌웨어 구현.
* 주행 진동/가속도·거리 데이터를 CSV-like 단일 문자열로 시리얼 출력.
* 정지 시 무의미한 노이즈 전송을 막는 엣지 임계값(0.01g) 필터 적용.

### Phase 2: Backend & Real-Time Data Stream (프로토타입 완료, 고도화 예정)

* **현재:** 호스트–ESP32 C-to-C 직결 + FastAPI 비동기 Queue → InfluxDB / WebSocket.
* **시연:** ESP32 미연결 시 1m 플라스틱 크레인 시나리오 더미 스트리머(10Hz)로 파이프라인 검증.
* **향후:** MQTT + Redis IoT 브로커 기반 무선 파이프라인 전환.

### Phase 3: Real-Time AI Predictive Model (진행 중)

* PyTorch RBF 대리 모델로 레일 변형 위험 지표를 실시간 추론.
* 웨이블릿 노이즈 제거 + 파고율 등 특징 공학 후 모델 입력 (원시 센서값 직입력이 아님).
* 위험 구간(단차 충격)에서 파고율이 임계치 이상으로 상승하는 시연 시나리오 검증 완료.

### Phase 4: Digital Twin & Web View (진행 중)

* WebSocket 연동 실시간 웹 대시보드 프로토타입 구축.
* 향후 Godot 등 3D 디지털 트윈에서 레일 위치(`distance_x`)·위험도(파고율/예측값)를 시각화.

## 프로토타입 실행 방법 (Getting Started)

1. **하드웨어 세팅 (선택):** ESP32-S3에 센서를 연결하고 C-to-C로 호스트에 직결. 없으면 더미 스트리머가 자동 동작합니다.
2. **펌웨어 업로드:** `firmware/crane_sensor/crane_sensor.ino` 업로드 후 **시리얼 모니터를 닫아** 포트를 확보합니다.
3. **모델 학습 (최초 1회):** `python ml/train_rbf_surrogate.py` → `rbf_dummy_model.pth` 생성.
4. **백엔드 가동:** `uvicorn main:app --host 0.0.0.0 --port 8000`
5. **대시보드 / Godot:** `frontend/index.html` 또는 `ws://127.0.0.1:8000/ws` 로 실시간 스트림 확인.
