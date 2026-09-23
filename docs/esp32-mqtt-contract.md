# ESP32-C3 MQTT 데이터 계약

## 연결

- 센서 업링크: 운영 `mqtt://223.130.128.198:1883` (로컬 `mqtt://host:1883`)
- 화면 다운링크: 운영 `wss://223.130.128.198:8000/ws` (로컬 `ws://host/ws`)
- 웹 대시보드: 운영 `https://223.130.128.198:8000/dashboard`
- 인증: 장치별 MQTT username/password. username은 `device_id`와 같다.
- 전송 품질: 텔레메트리와 상태 모두 QoS 1
- 계약 버전: `schema_version=1`

좌·우 레일 구동부에는 ESP32-C3가 각각 한 대씩 있다.

- 왼쪽: `device_id=rail-left-01`, `rail_side=left`, MQTT user `rail-left-01`
- 오른쪽: `device_id=rail-right-01`, `rail_side=right`, MQTT user `rail-right-01`

FastAPI는 `railtwin-backend` 계정으로 구독만 한다. 두 장치는 같은 WiFi와 브로커를 사용할 수 있지만 `device_id`, `rail_side`, MQTT 비밀번호는 반드시 달라야 한다.

## 토픽

| 용도 | 토픽 | retain | 비고 |
|---|---|---|---|
| 센서 배치 | `rail/v1/nodes/{device_id}/telemetry` | 아니오 | 10샘플 JSON 배치 |
| 접속 상태 | `rail/v1/nodes/{device_id}/status` | 예 | online 상태와 LWT offline |

## node_status

연결 직후 retained `online`을 발행하고, 예기치 않은 끊김에는 브로커가 LWT `offline`을 발행한다.

```json
{
  "type": "node_status",
  "schema_version": 1,
  "device_id": "rail-left-01",
  "rail_side": "left",
  "boot_id": "a1b2c3d4",
  "firmware_version": "0.3.0",
  "status": "online",
  "status_flags": 0
}
```

## sensor_batch

```json
{
  "type": "sensor_batch",
  "schema_version": 1,
  "device_id": "rail-left-01",
  "rail_side": "left",
  "boot_id": "a1b2c3d4",
  "firmware_version": "0.3.0",
  "batch_seq": 42,
  "dropped_batches": 0,
  "status_flags": 0,
  "samples": [
    {
      "sample_seq": 420,
      "uptime_us": 12503400,
      "position_mm": 1234.5,
      "sensor_distance_mm": 4.21,
      "adc_raw": 16420,
      "adc_voltage_v": 1.02,
      "sensor_voltage_v": 8.07,
      "accel_mps2": [0.02, -0.01, 9.79],
      "gyro_radps": [0.01, 0.00, -0.02]
    }
  ]
}
```

## 필드 원칙

- `device_id`: 영구 장치 식별자. 좌·우 장치가 서로 다른 값을 사용하며 MQTT username과 같다.
- `rail_side`: `left` 또는 `right`.
- `boot_id`: 부팅할 때 생성하는 8자리 16진수. 재부팅 후 배치 순번이 1로 초기화된 새 스트림을 구분한다.
- `batch_seq`, `sample_seq`: 연결이 끊겨도 증가하는 순번. QoS 1 중복과 유실 검출에 사용한다.
- `uptime_us`: ESP32 단조 증가 시간. 서버가 배치 안의 상대 샘플 시각을 복원한다.
- `position_mm`: 엔코더 기반 주행 위치. 교정 전에는 `null`.
- `sensor_distance_mm`: LR18 전압-거리 교정 결과. 교정 전에는 `null`.
- `adc_raw`, `adc_voltage_v`, `sensor_voltage_v`: 교정과 회로 검증용 원시·환산값.
- `accel_mps2`: MPU6050 가속도 X/Y/Z, 단위 m/s².
- `gyro_radps`: MPU6050 자이로 X/Y/Z, 단위 rad/s.
- `status_flags`: MPU6050/ADS1115 연결 실패와 엔코더/LR18 미교정 상태를 나타내는 비트 마스크.

`sensor_distance_mm`는 센서와 금속 사이의 거리이며 곧바로 레일 변형량이 아니다. 서버가 좌·우 간격을 묶어 `m`, `Δ`와 충격 `apeak`, 기울기 `tilt_deg`로 이음부 단차·수직 변형·좌우 높이차를 판정한다.

토픽의 `{device_id}`와 JSON `device_id`가 다르면 FastAPI는 메시지를 버린다.

## 속도 명령

서버는 단계가 바뀌면 `rail/v1/nodes/{device_id}/command`에 QoS 1로 발행한다.

```json
{"motion": "cruise"}
```

`motion`은 `cruise`, `slow`, `stop`이다. ESP32는 이 명령을 받기 전에도 세로 가속도가 중력 대비 4 m/s²를 넘으면 스스로 멈춘다.

## ACK와 유실

MQTT QoS 1의 PUBACK는 브로커 수락을 뜻하며 규칙 판정이나 InfluxDB 저장 완료를 뜻하지 않는다. FastAPI는 `(device_id, rail_side, boot_id)` 단위로 `batch_seq`를 추적해 재전송 중복을 제거한다.

브로커에 연결되지 않은 동안 펌웨어는 미발행 배치를 제한된 RAM Queue에 보관한다. 초과 시 가장 오래된 배치를 버리며 `dropped_batches`를 증가시킨다. 브로커는 FastAPI가 잠시 내려간 동안 QoS 1 메시지를 보관할 수 있다.

## 샘플링

- MPU6050: 100Hz
- ADS1115: 20Hz
- 전송: IMU 10샘플을 한 배치로 묶어 10Hz

서버는 좌·우 샘플을 구간으로 모아 네 분류를 판정한다. 웨이블릿·파고율은 쓰지 않는다. 채널당 200Hz를 넘겨 샘플링해도 LR18 응답은 100Hz이므로 새 정보가 늘지 않는다.
