"""raildyn 자체 검사. python3 tests.py"""
import numpy as np
from scipy import signal

import raildyn as rd
import railsim as rs

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail else ""))


flat = rd.flat_pipes()
step = rs.support_heights(rs.CONFIGS["2 이음부 단차"]["L"])

# 1. 바퀴 궤적
x = np.arange(100.0, 1700.0, 0.01)
z = rd.wheel_path(x, flat, 23.5)
sink = 21.0 - z.min()
check("틈 3 mm 에서 바퀴가 내려앉는 양", abs(sink - (23.5 - np.sqrt(23.5 ** 2 - 1.5 ** 2))) < 1e-6, f"{sink:.4f} mm (식 0.0479)")
check("틈에서 먼 곳은 레일 높이", abs(rd.wheel_path(np.array([300.0]), flat, 23.5)[0] - 21.0) < 1e-12)
zs = rd.wheel_path(x, step, 23.5)
lead = 601.5 - x[np.argmax(zs > 21.0 + 1e-9)]      # 높은 파이프의 모서리는 틈 건너편 601.5 mm
check("2 mm 단차를 오르기 시작하는 위치", abs(lead - np.sqrt(2 * 23.5 * 2 - 4)) < 0.05, f"모서리 앞 {lead:.2f} mm (식 9.49)")
dv = np.max(np.diff(zs) / 0.01) * 50.0
check("단차 모서리에서 세로 속도 뜀", abs(dv - rd.step_velocity_jump(23.5, 2.0, 50.0)) < 0.2, f"{dv:.2f} mm/s (식 {rd.step_velocity_jump(23.5, 2.0, 50.0):.2f})")
check("단차를 다 오른 뒤 높이 +2 mm", abs(rd.wheel_path(np.array([700.0]), step, 23.5)[0] - 23.0) < 1e-12)

# 2. 동역학
run = rd.simulate_side(flat, rd.Cart(r_front_mm=1e-6, r_rear_mm=1e-6), x0=300, x1=560)
check("평평한 레일(틈 없음)에서 가속도 0", np.abs(run["az"]).max() < 1e-9, f"{np.abs(run['az']).max():.1e}")
cart = rd.Cart()
run = rd.simulate_side(step, cart)
# 같은 계를 scipy dlsim 으로 풀어 비교
A, B, C, D, lf, lr = rd._system(cart)
duf, dur = run["uf"] - run["uf"][0], run["ur"] - run["ur"][0]
U = np.column_stack([duf, dur, np.gradient(duf, run["dt"]), np.gradient(dur, run["dt"])])
n = 20000
_, Y, _ = signal.dlsim(signal.cont2discrete((A, B, C, D), run["dt"], method="bilinear"), U[:n])
check("전달함수 계산이 상태공간 계산과 같음", np.abs(Y[:, 1] / 1000 - run["az"][:n]).max() < 1e-6, f"최대 차 {np.abs(Y[:, 1] / 1000 - run['az'][:n]).max():.1e} m/s²")
# 매우 단단한 대차는 준정적 현측정과 같아야 한다
stiff = rd.simulate_side(step, rd.Cart(front_mm=250, rear_mm=250, f_bounce_hz=400, zeta=0.7, r_front_mm=1e-6, r_rear_mm=1e-6))
d_dyn = rd.distance(stiff, step)
d_ref = rs.versine_of_profile(stiff["x"], step)
far = np.ones(len(d_dyn), bool)
for c in (350, 600, 850, 950, 1200, 1450):
    far &= np.abs(stiff["x"] - c) > 15
check("단단한 대차·점 접촉이면 railsim 현측정과 같음", np.abs(d_dyn - d_ref)[far].max() < 0.01, f"최대 차 {np.abs(d_dyn - d_ref)[far].max():.4f} mm")
# 충격 뒤 흔들림 주기 = 고유 진동수
lone = rd.simulate_side(step, rd.Cart(zeta=0.02, f_bounce_hz=40.0, gyration_mm=270.0), x0=300, x1=560)
seg = lone["az"][(lone["x"] > 322) & (lone["x"] < 345)]
f, p = signal.periodogram(seg - seg.mean(), fs=1 / lone["dt"])
check("충격 뒤 흔들림이 고유 진동수 근처", abs(f[np.argmax(p)] - 40.0) < 6.0, f"{f[np.argmax(p)]:.1f} Hz")
check("기본값에서 바퀴가 뜨지 않음", run["load_min"] > 0, f"최소 하중 비 {run['load_min']:.2f}")

# 3. 센서 모형
m = rd.measure(run, rd.Imu(fs_hz=50, dlpf_hz=44, noise_mps2=0.0), phase=0)
check("50 Hz 표본 간격", abs(np.diff(m["t"]).mean() - 0.02) < 1e-9)
m2 = rd.measure(run, rd.Imu(fs_hz=1000, dlpf_hz=0, noise_mps2=0.0), phase=0)
check("빠르게 재면 충격이 더 크게 보임", np.abs(m2["az"]).max() > np.abs(m["az"]).max(), f"{np.abs(m2['az']).max():.2f} > {np.abs(m['az']).max():.2f} m/s²")

print(f"\n{sum(results)}/{len(results)} 통과")
raise SystemExit(0 if all(results) else 1)
