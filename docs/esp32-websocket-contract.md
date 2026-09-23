# 화면 다운링크 WebSocket 계약

센서 업링크는 MQTTS QoS 1이다. 계약은 [`docs/esp32-mqtt-contract.md`](esp32-mqtt-contract.md).

화면(웹 대시보드·Unity WebGL)은 `wss://host/ws` (로컬 `ws://host/ws`)만 구독한다.

## 페이로드

최신 좌·우 스냅샷이다. 분류는 좌·우를 한 구간으로 묶어 양쪽에 같은 `defects`를 넣는다.

```json
{
  "source": "mqtt",
  "simulation": false,
  "motion": "slow",
  "left": {
    "distance_x": 50.0,
    "position_mm": 500.0,
    "sensor_distance_mm": 4.8,
    "m_mm": 0.6,
    "delta_mm": 0.05,
    "dm_dx": 0.004,
    "ddelta_dx": 0.0,
    "apeak": 0.2,
    "tilt_deg": 0.1,
    "defect_type": "vertical",
    "stage": "caution",
    "motion": "slow",
    "magnitude_mm": 1.3,
    "limit_mm": 2.0,
    "remaining_s": null,
    "pass_count": 1,
    "defects": [
      {
        "side": "both",
        "from_mm": 450,
        "to_mm": 500,
        "defect_type": "vertical",
        "stage": "caution",
        "m_mm": 0.6,
        "delta_mm": 0.05,
        "apeak": 0.2,
        "tilt_deg": 0.1
      }
    ],
    "rail_risk": [0, 0, 0.6],
    "rail_length_cm": 100,
    "segment_count": 20
  },
  "right": {}
}
```

- `defect_type`: `joint_step`(이음부 단차), `vertical`(수직 변형), `cross_level`(좌우 높이차).
- `stage`: `ok` 한계선 50% 이하, `caution` 50%~한계선, `danger` 한계선 초과.
- `motion`: `cruise` 평속, `slow` 감속, `stop` 위험 구간 진입 전 정지.
- `rail_risk`: 0 정상, 0.6 주의, 1 위험. 좌우 높이차는 낮은 쪽 레일만 칠한다.
- `simulation: true`이면 더미·가속 열화 화면이다. 정확도 숫자로 쓰지 않는다.
- `PRED_RAIL_DEFORM`, `CREST`는 보내지 않는다.
