"""RailTwin 가상 모형 확장 (1차) — 바퀴 궤적 + 대차 동역학 + 센서 모형.

sim/railsim.py(배용진)는 준정적 기하 모형이다: 바퀴는 점 접촉, 속도는 표본 간격만 바꾸고,
가속도는 만들지 않는다. 이 모듈은 같은 레일 모양에서 거리와 세로 가속도를 함께 만든다.

  1. 바퀴 중심 궤적  wheel_path()   반지름 R 인 원이 파이프 윗면과 끝 모서리를 타고 넘는 높이
  2. 대차 동역학     simulate_side() 한쪽 레일 위의 강체 보(세로 z, 앞뒤 기울기 θ)를 앞·뒤 바퀴의
                                      스프링·감쇠로 받친 모형. 좌·우는 railsim 처럼 따로 계산한다
  3. 센서 모형       measure()       칩 내부 저역 필터 → 표본 추출 → 잡음

단위: 길이 mm, 시간 s, 가속도 출력만 m/s². 좌표는 레일 0 mm 표시 기준, x 는 거리 센서 위치.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import numpy as np
from scipy import signal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sim"))
import railsim as rs  # noqa: E402

G_MM = 9806.65  # mm/s²


@dataclass
class Cart:
    """대차 한쪽. 값의 출처는 README 의 '변수와 근거' 표."""
    front_mm: float = 270.0      # 센서 → 앞(구동)바퀴 축. 9/28 단차 주행의 거리·가속도 변화 위치로 추정
    rear_mm: float = 270.0       # 센서 → 뒷바퀴 축. 같은 방법
    r_front_mm: float = 23.5     # 구동륜 답면 지름 47 mm (인수인계 도면)
    r_rear_mm: float = 23.5      # 뒤 롤러 반지름. 실측 없음, 구동륜과 같다고 둠
    f_bounce_hz: float = 40.0    # 세로 흔들림 고유 진동수. 실측 없음
    zeta: float = 0.15           # 감쇠비. 실측 없음
    gyration_mm: float = 200.0   # 앞뒤 기울기 회전 반지름 (관성 = 질량 × 이 값²). 실측 없음
    cg_mm: float = 0.0           # 무게중심 위치 (센서 기준, 앞이 +). 실측 없음
    imu_mm: float = 0.0          # 가속도 센서 위치 (센서 기준, 앞이 +). 실측 없음


@dataclass
class Imu:
    """MPU-6050 읽기 설정. 9/28 펌웨어(0.6.7-draft)는 50 Hz 표본, 내부 필터 44 Hz."""
    fs_hz: float = 50.0
    dlpf_hz: float = 44.0
    noise_mps2: float = 0.15     # 9/28 정상 주행의 세로 가속도 표준편차


def wheel_path(xw, pipes, radius, pert=None):
    """바퀴 축이 xw(배열)에 있을 때 바퀴 중심 높이 (바퀴 반지름을 뺀 값, 평평한 레일이면 레일 높이와 같다).

    파이프 윗면 위에서는 레일 높이를 따르고, 파이프 끝 모서리 근처에서는 모서리를 중심으로 한 원호를 그린다.
    이음부 틈(3 mm)과 단차를 넘는 모양이 여기서 나온다. 파이프 기울기는 작아 접점을 바로 아래로 본다.
    pert: 레일 본래 굴곡·다시 놓임 높이 함수 (x → mm). 윗면과 모서리에 같이 더한다.
    """
    xw = np.asarray(xw, dtype=float)
    z = np.full(xw.shape, -np.inf)
    half = rs.GAP / 2.0
    for k, (a, b) in enumerate(pipes):
        x0 = k * rs.PIPE + (half if k > 0 else 0.0)
        x1 = (k + 1) * rs.PIPE - (half if k < rs.N_PIPE - 1 else 0.0)
        on = (xw >= x0) & (xw <= x1)
        z[on] = np.maximum(z[on], a + (b - a) * (xw[on] - k * rs.PIPE) / rs.PIPE)
        for xc in (x0, x1):
            hc = a + (b - a) * (xc - k * rs.PIPE) / rs.PIPE
            d = xw - xc
            near = np.abs(d) < radius
            z[near] = np.maximum(z[near], hc + np.sqrt(radius ** 2 - d[near] ** 2) - radius)
    hole = ~np.isfinite(z)          # 바퀴가 틈보다 작아 받칠 곳이 없는 자리(점 접촉 검사용): 양옆 높이로 잇는다
    if hole.any() and not hole.all():
        z[hole] = np.interp(xw[hole], xw[~hole], z[~hole])
    if pert is not None:
        z = z + pert(xw)
    return z


def _system(cart: Cart):
    """상태 [z, ż, θ, θ̇], 입력 [uf, ur, u̇f, u̇r] 의 연속 시간 행렬과 출력 행렬.

    z, θ 는 무게중심의 높이와 앞뒤 기울기. 출력: 센서 자리 높이, 가속도 센서 자리의 세로 가속도,
    앞·뒤 바퀴가 받는 동적 힘(질량으로 나눈 값).
    """
    lf = cart.front_mm - cart.cg_mm
    lr = cart.rear_mm + cart.cg_mm
    wb = 2.0 * np.pi * cart.f_bounce_hz
    km = wb ** 2 / 2.0                 # 바퀴 하나의 강성 / 질량
    cm = cart.zeta * wb                # 바퀴 하나의 감쇠 / 질량
    rho2 = cart.gyration_mm ** 2
    A = np.array([
        [0.0, 1.0, 0.0, 0.0],
        [-2 * km, -2 * cm, -km * (lf - lr), -cm * (lf - lr)],
        [0.0, 0.0, 0.0, 1.0],
        [-km * (lf - lr) / rho2, -cm * (lf - lr) / rho2, -km * (lf ** 2 + lr ** 2) / rho2, -cm * (lf ** 2 + lr ** 2) / rho2],
    ])
    B = np.array([
        [0.0, 0.0, 0.0, 0.0],
        [km, km, cm, cm],
        [0.0, 0.0, 0.0, 0.0],
        [km * lf / rho2, -km * lr / rho2, cm * lf / rho2, -cm * lr / rho2],
    ])
    arm = cart.imu_mm - cart.cg_mm
    C = np.array([
        [1.0, 0.0, -cart.cg_mm, 0.0],                 # 센서 자리 높이 (센서는 x = 0)
        A[1] + arm * A[3],                            # 가속도 센서 자리 세로 가속도
        [-km, -cm, -km * lf, -cm * lf],               # 앞바퀴 동적 힘 / 질량
        [-km, -cm, km * lr, cm * lr],                 # 뒷바퀴 동적 힘 / 질량
    ])
    D = np.array([
        [0.0, 0.0, 0.0, 0.0],
        B[1] + arm * B[3],
        [km, 0.0, cm, 0.0],
        [0.0, km, 0.0, cm],
    ])
    return A, B, C, D, lf, lr


def simulate_side(pipes, cart: Cart | None = None, *, x0=285.0, x1=1505.0, speed=50.0,
                  dt=2.5e-4, pert=None):
    """한쪽 레일 위를 일정 속도로 달릴 때의 바퀴 궤적과 대차 응답.

    반환 dict: t, x(센서 위치), uf, ur(앞·뒤 바퀴 중심 높이), zs(센서 자리 대차 높이),
               az(가속도 센서 자리 세로 가속도, m/s², 중력 제외), load_min(바퀴 하중 최솟값 / 정지 하중).
    load_min 이 0 이하면 바퀴가 떴다는 뜻이고, 그 구간은 이 선형 모형이 맞지 않는다.
    """
    cart = cart or Cart()
    n = int((x1 - x0) / speed / dt)
    t = np.arange(n) * dt
    x = x0 + speed * t
    uf = wheel_path(x + cart.front_mm, pipes, cart.r_front_mm, pert)
    ur = wheel_path(x - cart.rear_mm, pipes, cart.r_rear_mm, pert)
    A, B, C, D, lf, lr = _system(cart)
    # 처음 자세(정지 평형)를 빼고 풀어 시작 과도 응답을 없앤다
    th0 = (uf[0] - ur[0]) / (lf + lr)
    z0 = uf[0] - lf * th0
    duf, dur = uf - uf[0], ur - ur[0]
    U = np.column_stack([duf, dur, np.gradient(duf, dt), np.gradient(dur, dt)])
    Ad, Bd, Cd, Dd, _ = signal.cont2discrete((A, B, C, D), dt, method="bilinear")
    Y = np.zeros((n, C.shape[0]))
    for j in range(U.shape[1]):
        num, den = signal.ss2tf(Ad, Bd, Cd, Dd, input=j)
        for i in range(C.shape[0]):
            Y[:, i] += signal.lfilter(num[i], den, U[:, j])
    # Y 는 처음 자세에서 벗어난 양이므로 처음 자세의 센서 자리 높이를 더한다
    zs = Y[:, 0] + (z0 - cart.cg_mm * th0)
    static_f = G_MM * lr / (lf + lr)
    static_r = G_MM * lf / (lf + lr)
    load_min = float(min((static_f + Y[:, 2]).min() / static_f, (static_r + Y[:, 3]).min() / static_r))
    return {"t": t, "x": x, "uf": uf, "ur": ur, "zs": zs, "az": Y[:, 1] / 1000.0,
            "load_min": load_min, "dt": dt, "speed": speed}


def measure(run, imu: Imu | None = None, rng=None, phase=None):
    """가속도 센서가 읽는 값. 내부 저역 필터(2차 버터워스로 근사) → 표본 추출 → 잡음.

    반환: t, x, az (m/s², 중력 제외). 실제 칩의 필터 모양과는 다를 수 있다.
    """
    imu = imu or Imu()
    rng = rng or np.random.default_rng(0)
    dt = run["dt"]
    a = run["az"]
    if imu.dlpf_hz and imu.dlpf_hz < 0.45 / dt:
        b, c = signal.butter(2, imu.dlpf_hz, fs=1.0 / dt)
        a = signal.lfilter(b, c, a)
    step = max(int(round(1.0 / (imu.fs_hz * dt))), 1)
    start = int(rng.integers(step)) if phase is None else int(phase) % step
    idx = np.arange(start, len(a), step)
    noise = rng.normal(0.0, imu.noise_mps2, len(idx)) if imu.noise_mps2 else 0.0
    return {"t": run["t"][idx], "x": run["x"][idx], "az": a[idx] + noise}


def distance(run, pipes, mount=0.0, pert=None, spike_amp=0.0, spike_sigma=6.0):
    """거리 센서가 읽는 값 = 설치 높이 + 센서 자리 대차 높이 − 센서 바로 아래 레일 높이.

    railsim.sensor_reading 과 같은 정의이고, 현(앞뒤 바퀴를 잇는 선) 대신 동역학으로 구한 대차 높이를 쓴다.
    """
    x = run["x"]
    h = rs.rail_height(x, pipes)
    if pert is not None:
        h = h + pert(x)
    v = mount + run["zs"] - h
    if spike_amp:
        for j in rs.JOINTS:
            v = v + spike_amp * np.exp(-0.5 * ((x - j) / spike_sigma) ** 2)
    return v


def flat_pipes(height=rs.SUPPORT_H["D"]):
    return [(height, height)] * rs.N_PIPE


def step_velocity_jump(radius, step_mm, speed):
    """높이 step_mm 인 단차 모서리에 바퀴가 닿는 순간 바퀴 중심 세로 속도의 뜀 (mm/s). 검사용 닫힌 식."""
    d = np.sqrt(2 * radius * step_mm - step_mm ** 2)
    return speed * d / (radius - step_mm)
