# 가변 계측–레일 이상 구간 디지털 트윈 기반 갠트리 크레인 안전관리 시스템

![하부 레일 이상 구간 디지털 트윈 시스템 아키텍처](docs/system-architecture.png)

## 프로젝트 소개

본 프로젝트는 대형 갠트리 크레인이 **하부 주행 레일**을 따라 이동할 때 생기는 간격·충격·기울기·위치 데이터로, 이음부 단차·수직 변형·좌우 높이차를 구분해 웹 대시보드와 Unity WebGL에 표시하는 디지털 트윈입니다. 정상·주의·위험에 따라 평속·감속·정지를 정합니다. RBF는 쓰지 않습니다.

> **핵심 타겟:** 센서가 기록하는 이름은 **수직 변형**을 포함한 레일 기하입니다. 거더 변형·기초 침하·받침 열화는 그 원인입니다.

## 팀원 및 담당 역할

* **배용진:** SENSOR & EDGE (센서 데이터 획득, 교정, 축 정의)
* **배준호:** BACKEND & RULE ENGINE (비동기 수집, 4분류 규칙 판정)
* **김병서:** WEB & UNITY WEBGL (대시보드, 레일 3D)
* **김정우:** 조립·시험 (축소 모형, 반복 주행)

## 사용 하드웨어 및 기술 스택

* **현재 하드웨어 (Edge):** 좌·우 레일 구동부별 ESP32-C3 Mini 1대씩, 각 노드의 MPU-6050, ADS1115, GTRIC LR18-08U.
* **하드웨어 이력:** ESP32-S3·ADXL345·HC-SR04는 취소된 초기 프로토타입입니다. [`docs/hardware-configuration-history.md`](docs/hardware-configuration-history.md)
* **백엔드 & 스트림:** Python, FastAPI, InfluxDB, ESP32 MQTT 업링크, 웹·Unity 다운링크 WebSocket.
* **판정:** 구간 특징 여섯 개로 이음부 단차·수직 변형·좌우 높이차. 웨이블릿·파고율·RBF는 쓰지 않음.
* **프론트엔드:** HTML/Vanilla JS, Tailwind CSS, Unity WebGL(레일만).

## 시스템 아키텍처 및 개발 로드맵

프로젝트는 총 4개의 Phase로 나뉩니다. 현재 ESP32-C3 MQTT 수집, 4분류 규칙 판정, InfluxDB 저장, 시연용 더미 스트리머와 웹·Unity 레일 뷰가 구현되어 있습니다.

### Phase 1: Sensor & Edge (펌웨어 구현, 실물 교정·검증 필요)

* 좌·우 구동부에 고유 ID와 레일 방향을 가진 ESP32-C3 센서 모듈을 각각 구성.
* MPU6050 100Hz, ADS1115 20Hz 수집 후 10개 샘플을 MQTT QoS 1 JSON 배치로 전송.
* GTRIC 간격·엔코더 위치·IMU 롤 축은 실측 후 펌웨어·서버 설정에 반영.
* 저장소의 ESP32-S3·ADXL345·HC-SR04 펌웨어는 과거 작업 열람용으로만 보존.

### Phase 2: Backend & Real-Time Data Stream (프로토타입 완료, 고도화 예정)

* **센서 업링크:** ESP32-C3 → WiFi → MQTT QoS 1 → NCP Mosquitto → FastAPI 구독 → 비동기 Queue.
* **분석 다운링크:** FastAPI → `/ws` → 웹 대시보드 / Unity WebGL.
* **시연:** `DEMO_MODE=true`일 때 1m 레일의 20~25cm, 45~70cm, 80~90cm에 세 결함을 넣는다. 화면에는 시뮬레이션이라고 표시한다.

### Phase 3: Rule-Based Zone Detection (진행 중)

* 원시 간격을 구간 특징 `m`, `Δ`, `dm/dx`, `dΔ/dx`, `apeak`, `φ`로 만들어 `defects[]`와 단계 색 `rail_risk`를 낸다.
* 주의는 감속, 위험은 진입 전 정지. 정지 명령은 MQTT `.../command`이고, ESP32는 세로 충격만으로도 멈춘다.
* PyTorch RBF·`PRED_RAIL_DEFORM`·파고율은 목표 스택에서 제외.

### Phase 4: Web Dashboard & Unity Rails (진행 중)

* WebSocket 연동 실시간 웹 대시보드.
* Unity WebGL에 **레일만** 띄우고, 이상 구간 색상과 갠트리 위치를 같은 좌표로 표시. 크레인 메시는 넣지 않는다.

## 프로토타입 실행 방법 (Getting Started)

1. **펌웨어 설정:** `firmware/esp32_c3_rail_sensor/`에서 `secrets.h.example`을 `secrets.h`로 복사하고 WiFi와 해당 보드 MQTT 비밀번호를 설정합니다.
2. **과거 펌웨어 열람:** `firmware/crane_sensor/crane_sensor.ino`는 취소된 프로토타입이며 현재 장치에 업로드하지 않습니다.
3. **환경 설정:** `.env.example`을 `.env`로 복사합니다. 실물 입력은 `DEMO_MODE=false`, 시연은 `DEMO_MODE=true`입니다.
4. **백엔드 가동:** `uvicorn main:app --host 0.0.0.0 --port 8000`
5. **센서/화면 접속:** ESP32는 `mqtt://223.130.128.198:1883`, 웹 대시보드는 `https://223.130.128.198:8000/dashboard` (`/ws`로 Unity·표가 같은 데이터를 받습니다).
6. **Unity WebGL (선택):** Mac 온보딩은 [`docs/mac-m5-unity-onboarding.md`](docs/mac-m5-unity-onboarding.md)입니다. 빌드는 `unity/RailTwinRails/README.md`대로 한 뒤 `scripts/sync_unity_webgl.sh`로 `frontend/unity/Build`에 복사합니다. 빌드 전에는 대시보드가 브라우저 레일 뷰를 씁니다.

## 개발보고서 및 AI 인계

* **ESP32 MQTT 계약:** [`docs/esp32-mqtt-contract.md`](docs/esp32-mqtt-contract.md)
* **공식 PDF 양식 항목표:** [`docs/development-report-template-map.md`](docs/development-report-template-map.md)
* **프로젝트 통합 문맥:** [`docs/notion-project-context.md`](docs/notion-project-context.md)
* **센서 하드웨어 변경 이력:** [`docs/hardware-configuration-history.md`](docs/hardware-configuration-history.md)
* **Cursor·ChatGPT 인계 프롬프트:** [`docs/development-report-ai-handoff.md`](docs/development-report-ai-handoff.md)
