"""RailTwin 가상 레일·대차 모델 (1차)

실물 시험 장치 그대로:
  - 레일: 600 mm 각파이프 3개를 이어 1800 mm. 받침은 0, 600, 1200, 1800 mm.
          파이프는 강체로 보고, 양 끝 받침 높이 사이를 직선으로 잇는다.
          이음부 두 곳(600, 1200)에 3 mm 틈.
  - 받침: N 23 mm, D 21 mm, S 는 한쪽 23 / 다른 쪽 21 (화살표 쪽이 23).
  - 대차: 앞뒤 바퀴 간격 500 mm, 변위센서는 그 한가운데(현측정).
  - 센서 값 = 센서 설치 높이 + (앞뒤 바퀴가 닿은 두 점을 잇는 현의 높이) - (센서 바로 아래 레일 높이)

좌표는 레일 0 mm 표시 기준. 모든 길이 mm.
"""
import numpy as np

PIPE = 600.0
N_PIPE = 3
RAIL_LEN = PIPE * N_PIPE
JOINTS = [PIPE * k for k in range(1, N_PIPE)]  # 600, 1200
GAP = 3.0
WHEELBASE = 500.0
SUPPORT_H = {"N": 23.0, "D": 21.0}
S_HI, S_LO = 23.0, 21.0


def support_heights(layout):
    """받침 배치 문자열 -> 각 파이프의 (왼쪽 끝 높이, 오른쪽 끝 높이) 목록.

    layout 예: "S> D D <S"   (논문 표 2 표기. 화살표는 S 받침의 23 mm 쪽 방향)
      0 mm   : 'S>'  -> 23 쪽이 오른쪽(파이프 쪽) -> 파이프 1 왼쪽 끝 23
      600 mm : 'D'   -> 양쪽 21
      1800 mm: '<S'  -> 23 쪽이 왼쪽(파이프 쪽) -> 파이프 3 오른쪽 끝 23
    받침 하나가 양쪽 파이프 끝을 받칠 때, 화살표 쪽 파이프 끝이 23, 반대쪽이 21.
    """
    toks = layout.replace("←", "<").replace("→", ">").split()
    assert len(toks) == N_PIPE + 1, layout
    # 각 받침에서 (왼쪽 파이프 끝 높이, 오른쪽 파이프 끝 높이)
    lr = []
    for t in toks:
        if t in SUPPORT_H:
            lr.append((SUPPORT_H[t], SUPPORT_H[t]))
        elif t == "S>":
            lr.append((S_LO, S_HI))
        elif t == "<S":
            lr.append((S_HI, S_LO))
        else:
            raise ValueError(t)
    pipes = []
    for k in range(N_PIPE):
        left_end = lr[k][1]      # k번째 받침의 오른쪽 자리
        right_end = lr[k + 1][0]  # k+1번째 받침의 왼쪽 자리
        pipes.append((left_end, right_end))
    return pipes


def rail_height(x, pipes, bow=None):
    """위치 x(배열)에서 레일 윗면 높이. bow[k] = k번째 파이프 가운데 처짐(아래로 +)."""
    x = np.asarray(x, dtype=float)
    h = np.full_like(x, np.nan)
    for k, (a, b) in enumerate(pipes):
        x0, x1 = k * PIPE, (k + 1) * PIPE
        m = (x >= x0) & (x <= x1)
        s = (x[m] - x0) / PIPE
        hk = a + (b - a) * s
        if bow is not None and bow[k]:
            hk = hk - bow[k] * 4 * s * (1 - s)  # 포물선 처짐
        h[m] = hk
    return h


def over_gap(x, half=GAP / 2):
    x = np.asarray(x, dtype=float)
    m = np.zeros_like(x, dtype=bool)
    for j in JOINTS:
        m |= np.abs(x - j) < half
    return m


def sensor_reading(x, pipes, mount, bow=None, gain=1.0, wheelbase=WHEELBASE,
                   spike_amp=0.0, spike_sigma=6.0):
    """센서 위치 x(배열)에서 센서가 읽는 거리(mm).

    mount : 결함 없는 평평한 레일에서의 센서-레일 거리(설치 높이)
    gain  : 센서 mm 환산 배율(교정 오차 보정용, 기본 1)
    spike : 이음부 틈 위에서 금속이 없어 값이 튀는 것을 종 모양으로 흉내
    """
    x = np.asarray(x, dtype=float)
    h_s = rail_height(x, pipes, bow)
    h_f = rail_height(x + wheelbase / 2, pipes, bow)
    h_r = rail_height(x - wheelbase / 2, pipes, bow)
    chord = (h_f + h_r) / 2
    v = mount + gain * (chord - h_s)
    if spike_amp:
        for j in JOINTS:
            v = v + spike_amp * np.exp(-0.5 * ((x - j) / spike_sigma) ** 2)
    return v


# 논문 표 2 의 네 가지 구성 (좌·우 레일 각각)
CONFIGS = {
    "1 정상":        {"L": "<S D D S>", "R": "<S D D S>"},
    "2 이음부 단차":  {"L": "D S> <S D", "R": "D S> <S D"},
    "3 수직 방향 변형": {"L": "S> D D <S", "R": "S> D D <S"},
    "4 좌우 높이차":  {"L": "S> D D <S", "R": "S> N N <S"},
}


def versine_of_profile(x, pipes, bow=None, wheelbase=WHEELBASE):
    """설치 높이 0, gain 1 일 때의 현측정 값(결함 성분만)."""
    return sensor_reading(x, pipes, 0.0, bow, 1.0, wheelbase)
