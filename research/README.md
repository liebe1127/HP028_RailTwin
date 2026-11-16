# research — 가상 모형, 가상 시운전, AI 연구 코드

> 이 폴더는 배용진 fork(`dydwls315-ops/HP028_RailTwin`)의 `virtual_validation/`(커밋 `de7c9f6`, 2026-11-07)를 그대로 옮긴 것이다. 폴더 이름만 `research/`로 바꿨다. 아래 본문의 `virtual_validation/`은 `research/`로 읽는다.
> 서버(`main.py`)는 이 폴더를 불러오지 않는다. 이 폴더만 바뀐 push 는 NCP 배포를 일으키지 않고(`.github/workflows/deploy-ncp.yml`의 `paths-ignore`), Docker 이미지에도 들어가지 않는다(`.dockerignore`).
> 패키지는 서버와 따로 설치한다: `pip install -r research/requirements.txt` (torch 는 학습에만 필요).

---

# virtual_validation — 가상 모형, 가상 시운전, AI (배용진)

실물 시험 레일을 파이썬 가상 모형으로 옮기고, 가상 주행으로 서버 판정 엔진을 시험하고 고치고, 가상으로만 학습한 AI 를 실측으로 검증해 서버에 붙이기까지의 코드, 결과, 문서. 2026-10-28 ~ 2026-11-05.

전체 흐름은 `docs/연구노트_가상검증과AI.pdf`, AI 부분은 `docs/AI_연구노트_상세.pdf` 에 있다. 코드 설명은 `docs/AI_코드.pdf`.

## 폴더

| 폴더 | 내용 |
|---|---|
| `sim/` | 코드 전부. 가상 모형(railsim.py), 교정·검증(analyze24.py), 데이터 생성(generate_dataset*.py), 가상→실측(sim2real*.py), 가상 시운전(replay_*.py), 엔진 수정안과 비교(rail_judge_v2.py, replay_compare.py), AI(ai_train*.py, rail_ai.py), 재검증(recheck_*.py, overfit_check_*.py), 자체 검사(tests.py), 재적응 도구(correct_runs.py, adapt.py, export_weights.py). 교정값 calibration.json |
| `weights/` | CNN 가중치 .pt 12개 (1차 씨앗 3, 2차 구간 제한 3, 최종 C3 교차검증 5). 서버용 npz 는 레포 루트 `rail_ai_weights.npz` |
| `results/` | 그림, 결과표, 회차별 추정 csv, 엔진 비교 csv, 데이터셋 manifest 7개 |
| `docs/` | 연구노트와 단계별 기록(md), PDF 4개 |

## 레포 루트에 있는 관련 파일

`rail_ai.py`, `rail_ai_weights.npz`, `rail_judge_v2.py`, `docs/ai-judge.md`, `docs/coords-rail-sensor.md`, `가상주행/`(가상 주행 재생용 33회). 서버에서 `RAIL_JUDGE=v2 RAIL_AI=1` 로 켠다.

## 돌리는 법

```
pip install -r requirements.txt
cd virtual_validation/sim
python3 make_data.py          # 실측 보정본 24회를 ../data/ 로 복사
python3 tests.py              # 가상 모형 자체 검사 21개
python3 analyze24.py          # 정상 6회로 교정, 결함 18회 예측
python3 generate_dataset_v2.py --placements 600 --runs 3 --seed 2 --out ../dataset_v2
python3 generate_dataset_v2.py --placements 240 --runs 3 --seed 9 --out ../dataset_v2_seed9
python3 ai_train.py           # 1차, 220초
python3 ai_train_v2.py        # 2차, 650초
```

가상 데이터셋은 크기 때문에 레포에 넣지 않았다. 같은 씨앗이면 같은 데이터가 나온다. sweep 4묶음은 `replay_pert_sweep.py`, 재검증 600회는 `--placements 200 --seed 31 --out ../dataset_recheck`. 서버 코드를 쓰는 스크립트(replay_*.py, recheck_engine.py)는 레포 루트의 pass_analysis.py, rail_defect.py 를 `../server/` 에 복사해 두고 돈다.

## 재적응 — 새 정상 주행으로 AI 다시 맞추기

펌웨어나 대차가 바뀌어 정상 주행의 흔들림 무늬가 달라지면, 새 정상 주행 5회 이상만으로 `rail_ai_weights.npz` 를 다시 만든다. 가상 데이터셋과 학습 방법은 그대로 두고, 기준선·잡음 묶음과 학습 중 더하는 실측 정상 배경만 새 주행으로 바꾼다(ai_train_v2 의 C3 방식, 새 정상 1회씩 빼고 학습). 서버 파일은 고치지 않고 npz 만 바꾼다. 설치 → 데이터셋 생성 → (a) 보정 → (c) 재적응 → (b) 내보내기 순서.

```
pip install -r requirements.txt
cd virtual_validation/sim
python3 make_data.py "../../배준호_전달/레일측정데이터/보정"                       # 9/28 보정본 24회 → ../data (참고 판정에 쓴다)
python3 generate_dataset_v2.py --placements 600 --runs 3 --seed 2 --out ../dataset_v2
python3 generate_dataset_v2.py --placements 240 --runs 3 --seed 9 --out ../dataset_v2_seed9
python3 correct_runs.py <새 정상 주행 csv 폴더> --out ../normal_new                  # (a) 위치 보정 열 붙이기 + 보정_기록.csv
python3 adapt.py --normal-dir ../normal_new --out ../adapt_out                     # (c) 재적응, 보고서 ../adapt_out/adapt_report.md
python3 export_weights.py ../adapt_out/ai_cnn_adapt_hold_*.pt --out ../../rail_ai_weights.npz   # (b) 레포 루트로 내보내고 torch·numpy 차이 확인
```

- (a) `correct_runs.py`: 서버 `/runs/{boot_id}.csv` 와 같은 열의 주행 CSV(파일 또는 폴더)에 rail_x_mm, rear_wheel_x_mm, encoder_scale_left/right, sensor_valid, analysis_window, joint_marker 를 붙인다. 규칙은 `배준호_전달/레일측정데이터/보정/README.txt` 와 같다. 이음부 스파이크 두 개를 못 찾거나 좌 배율이 0.8~1.2 밖이면 실패로 적고 건너뛴다. 엔코더가 0 으로 되돌아간(충격 정지 후 재출발) 회차는 재출발 뒤 이전 위치를 넘어선 행부터 analysis_window 1. `--compare <기존 보정본 폴더>` 로 기존 보정본과 rail_x_mm 차이를 찍는다. 9/28 원본 24회: 최대 차이 1.5 mm(14차 이음부 한 행 차이, 나머지 23회 0.0 mm), 37차 공회전은 실패 처리 (`results/correct_runs_check_0928.csv`).
- (c) `adapt.py`: 새 정상으로 `calibration_new.json`(원본 calibration.json 은 그대로)을 만들고, 센서 점검에 걸린 회차는 빼고, 1회씩 빼 가며 학습해 `.pt` 와 `rail_ai_weights.npz` 를 낸다. 보고서에 ① 뺀 회차의 AI 추정 최댓값(합격 ≤ 0.25 mm) ② 정상의 센서 점검 표시 수(합격 0) ③ 가상 검증 종류·단계 % ④ 9/28 실측 18회 판정(참고) ⑤ 걸린 시간을 적는다. 기본은 CPU(`--device mps` 를 주면 끝에 CPU 와 추론 차이를 찍는다). 정상 5회 기준 CPU 2코어에서 약 6분.
- (b) `export_weights.py`: `.pt` 여러 개 → `rail_ai.RailAI` 가 읽는 npz. 내보낸 뒤 실측 18회(`--data` 로 다른 폴더)에서 torch 와 numpy 출력 최대 차이를 찍고 1e-5 아래면 통과. adapt.py 가 같은 함수로 npz 를 이미 만들므로, (b)는 레포 루트로 내보내며 한 번 더 확인하는 단계다.
- 묶음 확인: 9/28 정상 32~36차를 새 정상으로 넣고 (a)→(c)→(b)를 끝까지 돌린 결과가 `results/adapt_check_0928_32-36.md`. 뺀 회차 추정 최댓값 단차 0.07 / 처짐 0.23 mm, 센서 점검 0회, 가상 검증 종류 80 % 단계 81 %, 실측 18회 종류 17/18 단계 17/18(센서 검사 뒤 18/18), 5.8분 → 통과. 같은 확인을 돌리려면:

```
python3 correct_runs.py "../../배준호_전달/레일측정데이터/1. 정상" --out ../check_a --compare "../../배준호_전달/레일측정데이터/보정"
mkdir -p ../check_normal && cp ../check_a/*3[2-6]차*_보정.csv ../check_normal/
python3 adapt.py --normal-dir ../check_normal --out ../check_c
```

새 npz 를 서버에 쓰려면 레포 루트 `rail_ai_weights.npz` 를 바꾸고 `RAIL_AI=1` 로 켠다. 가상 데이터셋과 `.pt` 는 커밋하지 않는다.

## 결과 요약

- 가상 모형: 정상 6회로만 교정해 결함 18회 예측 오차 0.14~0.36 mm, 단차 크기 1.95 / 1.74 (논문 1.84)
- 가상 시운전: 팀 엔진 그대로 1,800회 재생 → 실측으로 못 찾던 문제 4건. 수정 후 종류 정답 35 → 66 %, 정지 신호 결함 앞 100 %
- AI: 가상으로만 학습한 1D CNN, 실측 18회 종류 17/18, 단계 17/18, 센서 어긋남 검사 더하면 18/18
- 학습에 안 쓴 가상 1,440회에서 엔진 + AI: 종류 80 %, 3회째 단계 82 %, 정상 오경보 9 %
