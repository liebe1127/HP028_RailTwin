# Claude Code 인계: ESP32 펌웨어 검토 + 양방향 디지털 트윈 루프

이 파일은 팀원이 **Claude Code**에 그대로 넣거나 `@`로 첨부하기 위한 작업 인계다.  
대화 녹취가 아니라, 2026-09-14 Cursor 채팅에서 확정한 **사실·결정·하지 말 것**만 적는다.

- 저장소: https://github.com/liebe1127/HP028_-ICT
- 검토 당시 브랜치: `feat/c3-demo-drive-firmware` (로컬과 origin 펌웨어가 같았음)
- 펌웨어 마지막 관련 커밋: `d721c38` (2026-08-25) `feat: C3 10초 전진 시연 구동과 단차 충격 시각화`
- **이 대화에서 코드는 수정하지 않았다.** 구현을 시작하라는 뜻이 아니다. 사용자가 명시하기 전에는 패치하지 말 것.

---

## 0. Claude Code가 먼저 할 일

저장소를 클론·체크아웃한 뒤 **아래를 읽고** 답하거나 코딩한다. 삭제된 초기 스케치나 거더 처짐 문서를 현재 설계로 쓰지 말 것.

필수 읽기 순서:

1. `.cursor/rules/rail-deformation-context.mdc`
2. `docs/hardware-configuration-history.md`
3. `docs/esp32-mqtt-contract.md`
4. `firmware/esp32_c3_rail_sensor/README.md`
5. `firmware/esp32_c3_rail_sensor/config.h`
6. `firmware/esp32_c3_rail_sensor/esp32_c3_rail_sensor.ino`
7. `firmware/esp32_c3_rail_sensor/node_profile.left.h.example`
8. `firmware/esp32_c3_rail_sensor/node_profile.right.h.example`
9. `main.py` — MQTT 구독, `update_rail_risk`, `/rail_risk/reset` (명령 다운링크는 없음)
10. `frontend/index.html` — 콘솔 조작은 `rail_risk` 리셋뿐
11. `godot/rail_twin_websocket.gd` — 수신 시각화만, 송신 없음

참고:

- 계약 예시 `firmware_version`은 `0.3.0`일 수 있다. 코드는 `0.4.0`이다. 코드 값을 우선한다.
- `docs/2026_스마트해운물류_개발보고서_초안.md`는 발표 문장과 코드가 어긋날 수 있다. **충돌 시 펌웨어·`esp32-mqtt-contract.md`·사용자 확인을 우선**한다.

---

## 1. 프로젝트 사실 (바꾸지 말 것)

대형 갠트리 크레인 **하부 주행 레일**의 단차·국부 침하·뒤틀림을 예측하는 디지털 트윈이다.

- 예측 식별자: `predict_rail_deform()`, `pred_rail_deform`, `PRED_RAIL_DEFORM`, `rail_deform`
- **금지:** 거더 처짐, `deflection`, `PRED_DEFLECTION`를 새로 쓰지 말 것
- 조립 실물(2026-09-24): ESP32-S3-DevKitC-1 N16R8 1장 + 좌·우 각 MPU-6050, ADS1115, LR18-08U, L298N, JGB37-520 내장 엔코더. 핀맵은 `docs/hardware-configuration-history.md`
- 이 문서 아래의 코드 설명은 저장소 `firmware/esp32_c3_rail_sensor/`이다. 그 펌웨어는 C3 두 노드용이며 조립 보드에 올라가 있지 않다
- 취소된 프로토타입: ESP32-S3-WROOM-1 + ADXL345 + HC-SR04. 그 스케치는 2026-09-27에 저장소에서 삭제했다. 현재 DevKitC-1과 다른 보드이다
- 데이터 경로(현재): ESP32 → Wi-Fi MQTT QoS 1 → Mosquitto → FastAPI → 특징 공학·RBF → InfluxDB + WebSocket → 웹 대시보드·Godot
- 운영 브로커: `mqtt://223.130.128.198:1883` (TLS 꺼짐, 공인 IP)
- 노드: `rail-left-01` / `left`, `rail-right-01` / `right`

GTRIC LR18-08U: DC 15–30V, 0–10V, 1–8mm. ADS1115에 직접 연결하지 않고 분압·보호를 거친다.

---

## 2. 현재 펌웨어가 실제로 하는 일

경로: `firmware/esp32_c3_rail_sensor/`  
버전: `FIRMWARE_VERSION = "0.4.0"`

| 항목 | 값 |
|---|---|
| IMU | 100 Hz |
| ADS1115 | 20 Hz, 최신값을 IMU 샘플에 부착 |
| 업로드 | 10샘플 JSON, 약 10 Hz, QoS 1 |
| 토픽 | `rail/v1/nodes/{device_id}/telemetry`, `/status` |
| 모터 | 부팅 즉시 전진, `MOTOR_FORWARD_MS = 10000`, `MOTOR_PWM_DUTY = 180` |
| 핀 | SDA 8, SCL 9, 엔코더 6·7, L298N IN1/IN2/ENA = 4·5·10 |

잘 된 점: 좌·우 `node_profile` 분리, `secrets.h`/`node_profile.h` Git 제외, `boot_id`+`batch_seq`, LWT, 쿼드러처 ISR, 미발행 배치 RAM 큐(`MAX_PENDING_BATCHES = 64`), `status_flags`.

모터는 `ledcWrite(PIN_MOTOR_ENA, duty)`다. **하드웨어는 주행 중 듀티 변경이 가능하다.** 다만 `updateMotor()`는 10초 후 정지뿐이고, 주행 중 속도를 바꾸지 않는다. MQTT **구독(명령 수신)은 없다.**

위험 판정은 보드가 하지 않는다. FastAPI가 `PRED_RAIL_DEFORM` → 구간 `rail_risk`를 만든다.

---

## 3. 코드 검토에서 찾은 불일치 (구현 시 전제로 둘 것)

### 3.1 계약은 `null`, 코드는 추정값을 보냄

`docs/esp32-mqtt-contract.md`:

- `position_mm`: 엔코더 교정 전 `null`
- `sensor_distance_mm`: LR18 교정 전 `null`

실제 코드:

- `NODE_ENCODER_COUNTS_PER_WHEEL_REV == 0`이면 10초 동안 0→`DEMO_DRIVE_LENGTH_MM`(1000)을 **시계로** 채워 보냄. Godot 시연용. 서버는 이 값을 `distance_x`·`rail_risk` 구간에 사용한다.
- `NODE_ENABLE_LINEAR_DISTANCE_ESTIMATE`는 `status_flags` bit 3만 켠다. ADS가 살아 있으면 `sensor_distance_mm`는 항상 `0–10V → 1–8mm` 직선 환산이다.

프로필 주석(“0이면 null”)과 README(시연용 추정값)가 서로 다르다. **새 기능을 넣을 때 계약을 하나로 고정하고 코드와 문서를 같이 맞춰라.**

### 3.2 분압 기본값 vs 보고서

| 출처 | 분압 | 10V일 때 ADC 측 |
|---|---|---|
| `node_profile.*.h.example` | 470 kΩ / 68 kΩ | 약 1.26 V |
| 개발보고서 초안 | 20 kΩ / 10 kΩ | 약 3.33 V |

실물 저항을 재기 전에는 어느 쪽도 확정하지 말 것. 값이 틀리면 `sensor_voltage_v`가 수 배 틀린다.

### 3.3 정지 노이즈 임계값

문서·보고서: 엣지에서 정지 노이즈를 걸러 보낸다.  
**이전 C3 펌웨어 설명에는 없다.** 임계값은 삭제된 초기 스케치의 `ACCEL_THRESHOLD_G`에만 있었다. C3 설명은 정지/주행 모두 100 Hz를 그대로 발행한다고 적었다.

### 3.4 부팅 직후 배치 유실 가능

`setup()`에서 모터를 바로 켠다. Wi-Fi·MQTT는 `loop()`에서 붙는다.  
10초 × 10 Hz = 100배치, 큐는 64. 연결이 약 3.6초보다 늦으면 앞구간이 `dropped_batches`로 버려진다.  
명령으로 감속하려면 **MQTT 연결 후 출발**이 맞다.

### 3.5 기타

- ADS1115 `readADC_SingleEnded()` 기본 128 SPS는 변환만 ~8 ms. 100 Hz 주기와 겹치면 지터.
- 거리 곡선 방향(전압↑ = 멀다)은 실측 전 가정이다. 유도형은 반대일 수 있다.
- `MQTT_USE_TLS = false`. `tls_root_ca.h`는 미사용.
- 모터 핀은 `config.h` 공용. 좌·우 중 어디에 L298N이 있는지는 실물 확인.
- 엔코더 PPR·방향·영점, `NODE_ENABLE_LINEAR_DISTANCE_ESTIMATE`는 기본 미교정(`PPR=0`, 거리 추정 플래그 false).
- 학교 Wi-Fi(엔터프라이즈·캡티브)는 이 펌웨어로 접속 불가. 핫스팟/연구실 공유기.

---

## 4. 팀 대화에서 나온 목표 (아직 미구현)

### 4.1 하고 싶은 기능

레일의 특정 구간을 지날 때 센서·AI가 위험 구간으로 보면 **그 구간에서 모터 속도를 줄인다.**  
콘솔(웹 대시보드 등)에서도 조작하면 **물리 모형이 바뀌고**, 그 결과가 다시 트윈에 보여야 한다.  
발표 포인트: **디지털 트윈 양방향 피드백 루프.**

지금은 단방향이다. 콘솔 `POST /rail_risk/reset`은 서버 히트맵만 지운다. 모터·보드는 그대로다.

### 4.2 기술적으로 가능한가?

**가능하다.** PWM은 이미 동적이다. 없는 것은 콘솔·서버 → ESP32 명령 경로다.

권장 구조:

```
센서 MQTT → FastAPI(특징·RBF·rail_risk) → WebSocket(웹·Godot)
                         ↓
              MQTT command (신규)
                         ↓
              ESP32 subscribe → ledcWrite(duty)
                         ↓
              느려진 position_mm / 충격이 다시 업링크
```

같은 주행에서 방금 감지한 위험에 반응하면 왕복 지연 약 0.2–0.5초(시연 속도 10초/1m면 약 2–5 cm).  
이미 칠해 둔 `rail_risk` 구간이면 진입 **전에** 감속 명령을 보내는 편이 맞다.

보드가 IMU/거리 임계값만으로 혼자 감속하는 안은 빠르지만, 콘솔 개입이 없어 **양방향 강조와 안 맞다.** 1순위가 아니다.

### 4.3 추천안 (이 대화의 결론)

**1순위: 위험 구간 자동 감속 + 콘솔 개입**

| 콘솔 조작 | 물리 | 트윈 |
|---|---|---|
| 자동 | 빨간 구간에서 PWM 하향 | 크레인이 천천히 지나감 |
| 정지 | PWM 0 | 화면 위치 멈춤 |
| 저속 통과 | 낮은 듀티로 재출발 | 같은 구간을 천천히 통과 |
| 정상 속도 | 원래 듀티 | 이후 평속 |

시연 한 사이클:

1. 출발 → (더미/실측) 약 40–50 cm 단차 → 화면 구간 빨강
2. 모형이 저절로 느려짐
3. 콘솔 **정지** → 바퀴·Godot 멈춤
4. **저속 통과** → 같은 구간을 천천히 지나며 CREST·위치가 다시 흐름
5. (선택, 엔코더 교정 후) 빨간 구간 클릭 → 다음 주행에서 진입 전 미리 감속

### 4.4 하지 말라고 한 것

- 조이스틱식 전진/후진/속도만 넣기 → 레일 변형 AI와 끊긴 RC카
- 트윈에서 크레인을 드래그해 모형이 따라가게 → 엔코더·제어 부담, 시연 실패 쉽음
- 경광등·버저 추가 → 모터 감속보다 설득력 약함, 부품 없음
- ESP32 안에서 RBF를 돌려 혼자 감속 → 콘솔 개입 사라짐
- 엔코더 미교정 상태에서 구간 클릭 위치 제어를 1차로 넣기

---

## 5. 구현을 요청받으면 (아직 요청 없음)

사용자가 “넣어”라고 하기 전에는 코딩하지 말 것. 요청이 오면 **최소 슬라이스**만:

1. MQTT 명령 계약 추가. 예: `rail/v1/nodes/{device_id}/command`  
   필드 초안: `schema_version`, `device_id`, `action` = `stop` \| `slow` \| `normal` \| `auto`, `duty`(0–255, 선택)
2. 펌웨어: 해당 토픽 subscribe, `ledcWrite`만 변경. 부팅 즉시 모터 대신 **MQTT 연결 후 출발**을 검토
3. FastAPI: `rail_risk` 임계 초과 시 자동 `slow` 발행 + 대시보드용 POST
4. `frontend/index.html`: 정지 / 저속 통과 / 정상 속도 버튼
5. `docs/esp32-mqtt-contract.md`를 코드와 동시에 수정

좌·우 중 어느 노드의 `rail_risk`가 어느 모터를 줄일지는 실물 배선 확인 후 정한다. 추측으로 양쪽 모터를 동시에 돌리지 말 것.

교정 전 `position_mm`/`sensor_distance_mm`을 `null`로 바꿀지, 시연 추정값을 유지할지는 **별도 결정**이다. 감속 기능과  bundling하지 말고 먼저 물어라.

---

## 6. Claude Code용 시작 프롬프트 (복붙)

팀원이 새 Claude Code 세션에서 아래를 넣고, 이 파일을 `@`로 첨부한다.

```text
@docs/claude-code-handoff-firmware-bidirectional-loop.md
@docs/esp32-mqtt-contract.md
@firmware/esp32_c3_rail_sensor/README.md
@.cursor/rules/rail-deformation-context.mdc

우리 팀 GitHub(liebe1127/HP028_-ICT) 기준으로 작업한다.
방금 첨부한 인계 문서는 2026-09-14 다른 팀원–Cursor 대화의 결론이다. 코드를 추정하지 말고 저장소 파일을 직접 읽어라.

핵심:
- 예측 대상은 하부 주행 레일 단차·침하·뒤틀림이다. 거더 처짐/deflection을 쓰지 마라.
- 조립 실물 펌웨어는 firmware/esp32_s3_rail_node/ 다. 취소된 초기 스케치는 저장소에서 삭제했다.
- 모터는 10초·듀티 180으로 하드코딩되어 있지만 ledcWrite는 런타임에 바꿀 수 있다. MQTT 명령 구독은 아직 없다.
- 인계 문서의 코드 수정은 아직 하지 않았다.

지금은 코드를 바꾸지 말고, 인계 문서와 저장소를 대조해서
1) 현재 단방향 루프
2) 양방향(콘솔·rail_risk → 모터 감속)을 넣으려면 어떤 파일을 어떻게 바꿀지
를 짧게 계획만 제시해라.
구현은 내가 다음 메시지로 지시할 때만 시작한다.
```

구현을 시킬 때는 마지막 두 문단을 지우고 예를 들어 이렇게 바꾼다.

```text
인계 문서 5절의 최소 슬라이스대로 MQTT command 계약, ESP32 구독, FastAPI 자동 감속, 대시보드 버튼까지 구현해라.
엔코더 구간 클릭과 거리 null 정책 변경은 이번 범위에서 빼라.
거더 처짐 용어를 쓰지 마라.
```
