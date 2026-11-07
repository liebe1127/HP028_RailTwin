# 좌표계 통일: 센서 기준 레일 mm (2026-11-03)

## 왜
- 서버의 결함 구간(from_mm/to_mm)과 rail_risk 는 주행 분석(pass_analysis)이 이음부 틈을 600·1200 mm 에 맞춘 **센서 기준 레일 좌표**다.
- 그런데 서버가 보내던 distance_x 는 **엔코더 원시값**(출발점 0, 뒷바퀴)이었고, 대시보드·Unity 는 실시간이면 58 cm 를 더했다.
- 결과: 실시간에서는 결함 구간이 화면에 58 cm 밀려 칠해지고(54~126 → 112~180 cm), 실측 재생에서는 대차가 센서보다 25~30 cm 뒤에 그려졌다. 가상 시운전(가상 주행 1,800회 재생)에서 발견.

## 무엇을 바꿨나
- pass_analysis.py: 주행 결과에 `joint_raw_mm`(이음부 틈의 엔코더 원시 위치) 추가.
- rail_defect.py
  - `DefectRuleEngine.rail_x_mm(raw)`: 직전 주행의 이음부 위치·배율로 원시값 → 레일 좌표(미끄러짐 보정 포함). 결과가 없을 때는 `RAIL_ENCODER_ZERO_MM`(출발 시 뒷바퀴 레일 위치, 기본 0) + 센서 오프셋 250.
  - 구간 번호(`_segment_index`)를 레일 좌표로 매긴다 → rail_risk 가 항상 같은 좌표계.
  - 감속·정지(motion)를 주행 분석 결과의 rail_risk 에서 내고, 진행 방향 앞 `RAIL_MOTION_LOOKAHEAD`(기본 2)구간을 미리 본다. 이전에는 옛 구간 규칙이 냈고 정지 신호가 나오지 않았다.
  - `RAIL_JUDGE=v2` 환경 변수를 주면 수정안 판정기(rail_judge_v2.py)를 쓴다. 기본은 논문 검증본(v1).
- main.py: 페이로드에 `rail_x_mm`, `coords: "rail_sensor"` 추가. distance_x 는 호환용으로 그대로.
- frontend/index.html: `rail_x_mm` 가 있으면 58 cm 보정 없이 그대로 쓰고(대차 위치·결함 구간·위험도 띠), Unity 에는 `wheel: 0` 으로 보내 센서 위치를 대차 중심으로 놓게 한다. 없으면 옛 방식 그대로.
- Unity: 변경 없음 (wheel=0 경로가 이미 x 를 대차 중심으로 처리).

## 확인
- 실측 24회 재생(replay_csv.py): 판별 18/18 유지.
- 가상 주행 재생: 감속·정지 신호가 결함 앞(중앙값 −299 mm)에서 나옴. 자세한 수치는 프로젝트 문서 "3단계_수정후_재검증".
