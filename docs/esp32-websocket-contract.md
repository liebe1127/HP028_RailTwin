# ESP32-C3 WebSocket 데이터 계약

## 연결

- 센서 업링크: `ws://host/ws/sensor` 또는 운영 `wss://host/ws/sensor`
- 화면 다운링크: `ws://host/ws` 또는 운영 `wss://host/ws`
- 인증: 센서 연결의 `Authorization: Bearer <SENSOR_AUTH_TOKEN>` 헤더
- 계약 버전: `schema_version=1`

ESP32는 연결 후 `hello`를 보내고 서버의 `hello_ack`를 확인한다. 센서 배치는 서버가 Queue에 수락한 뒤 `ack`를 반환한다.

## hello

```json
{
  "type": "hello",
  "schema_version": 1,
  "device_id": "rail-sensor-01",
  "rail_side": "left",
  "firmware_version": "0.1.0",
  "sample_interval_us": 10000,
  "samples_per_batch": 10
}
```

## sensor_batch

```json
{
  "type": "sensor_batch",
  "schema_version": 1,
  "device_id": "rail-sensor-01",
  "rail_side": "left",
  "firmware_version": "0.1.0",
  "batch_seq": 42,
  "dropped_batches": 0,
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

- `device_id`: 영구 장치 식별자. 좌·우 의미를 문자열에 합치지 않는다.
- `rail_side`: `left` 또는 `right`.
- `batch_seq`, `sample_seq`: 연결이 끊겨도 증가하는 순번. 중복과 유실 검출에 사용한다.
- `uptime_us`: ESP32 단조 증가 시간. 서버가 배치 안의 상대 샘플 시각을 복원한다.
- `position_mm`: 엔코더 기반 주행 위치. 교정 전에는 `null`.
- `sensor_distance_mm`: LR18 전압-거리 교정 결과. 교정 전에는 `null`.
- `adc_raw`, `adc_voltage_v`, `sensor_voltage_v`: 교정과 회로 검증용 원시·환산값.
- `accel_mps2`: MPU6050 가속도 X/Y/Z, 단위 m/s².
- `gyro_radps`: MPU6050 자이로 X/Y/Z, 단위 rad/s.

`sensor_distance_mm`는 센서와 금속 사이의 거리이며 곧바로 레일 변형 예측값을 뜻하지 않는다. 기준 거리와 설치 오차를 교정하고 특징 공학·RBF 추론을 거친 출력은 `PRED_RAIL_DEFORM`이다.

## ACK와 유실

정상 수락:

```json
{"type":"ack","batch_seq":42,"accepted_samples":10}
```

재접속 후 이미 처리한 배치를 다시 보낸 경우:

```json
{"type":"ack","batch_seq":42,"duplicate":true}
```

WebSocket/TCP는 연결 중 순서를 보장하지만 WiFi 단절, 장치 재부팅, RAM 버퍼 초과까지 무손실로 만들지는 않는다. 펌웨어는 미확인 배치를 제한된 RAM Queue에 보관하고, 초과 시 가장 오래된 배치를 버리며 `dropped_batches`를 증가시킨다.

## 샘플링

- MPU6050: 100Hz
- ADS1115: 20Hz
- 전송: IMU 10샘플을 한 배치로 묶어 10Hz

서버는 32샘플 롤링 창에서 웨이블릿 디노이징, RMS, Peak-to-Peak, 파고율, 자이로 특징, LR18 거리 변화, 엔코더 속도를 계산한다.
