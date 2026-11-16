"""시뮬레이터 코드 검증 — 손으로 계산할 수 있는 경우와 코드 결과를 대조한다.

실행: python3 tests.py   (모두 PASS 가 나와야 한다)
"""
import numpy as np
import railsim as rs
import generate_dataset as gd
from load_run import find_spikes

X = np.arange(260.0, 1541.0, 1.0)
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


# 1. 받침 배치 읽기 (화살표 = S 의 23 mm 쪽)
p = rs.support_heights("<S D D S>")
check("배치 '<S D D S>' → 세 파이프 모두 21 (평평한 정상)", p == [(21, 21), (21, 21), (21, 21)], str(p))
p = rs.support_heights("S> D D <S")
check("배치 'S> D D <S' → 1번 왼쪽 끝 23, 3번 오른쪽 끝 23, 나머지 21 (가운데 처짐)", p == [(23, 21), (21, 21), (21, 23)], str(p))
p = rs.support_heights("D S> <S D")
check("배치 'D S> <S D' → 2번 파이프 양 끝 23, 나머지 21 (이음부 단차)", p == [(21, 21), (23, 23), (21, 21)], str(p))
p = rs.support_heights("S> N N <S")
check("배치 'S> N N <S' → 전부 23 (평평)", p == [(23, 23), (23, 23), (23, 23)], str(p))

# 2. 평평한 레일 → 센서 값 = 설치 높이, 틈 스파이크 없으면 어디서나 같다
flat = [(21, 21)] * 3
v = rs.sensor_reading(X, flat, 6.0)
check("평평한 레일 → 센서 값 = H 어디서나 (최대 편차 < 1e-9)", np.nanmax(np.abs(v - 6.0)) < 1e-9, f"{np.nanmax(np.abs(v-6.0)):.2e}")

# 3. 레일 전체가 기울어도(0→1800 에서 0→5 mm) 현측정은 0 (바퀴 두 점의 현과 센서 아래 높이가 같이 움직임)
tilt = [(21 + 5 * 0 / 3, 21 + 5 * 1 / 3), (21 + 5 * 1 / 3, 21 + 5 * 2 / 3), (21 + 5 * 2 / 3, 21 + 5 * 3 / 3)]
v = rs.versine_of_profile(X, tilt)
check("레일 전체 기울기 5 mm → 현측정 값 0 (< 1e-9)", np.nanmax(np.abs(v)) < 1e-9, f"{np.nanmax(np.abs(v)):.2e}")

# 4. 이음부 단차: 2번 파이프 전체 +s → 손 계산 (+s/2, -s/2, 0, -s/2, +s/2)
s = 2.0
step = [(21, 21), (21 + s, 21 + s), (21, 21)]
v = rs.versine_of_profile(X, step)
expect = np.zeros_like(X)
expect[(X > 350) & (X < 600)] = +s / 2
expect[(X > 600) & (X < 850)] = -s / 2
expect[(X > 950) & (X < 1200)] = -s / 2
expect[(X > 1200) & (X < 1450)] = +s / 2
m = ~np.isin(X, [350, 600, 850, 950, 1200, 1450])
check("이음부 단차 2 mm → 앞 250 mm +1.0, 뒤 250 mm −1.0, 사이 0 (손 계산과 일치)", np.nanmax(np.abs(v[m] - expect[m])) < 1e-9, f"{np.nanmax(np.abs(v[m]-expect[m])):.2e}")

# 5. 가운데 처짐 2 mm (S> D D <S) → 600, 1200 에서 삼각 봉우리 0.4167, 폭 ±250 (논문의 '약 0.4 mm')
sag = rs.support_heights("S> D D <S")
v = rs.versine_of_profile(X, sag)
peak = 2.0 * 250 / 600 / 2  # = 0.41667
tri = np.zeros_like(X)
for j in (600, 1200):
    w = np.abs(X - j) <= 250
    tri[w] = peak * (1 - np.abs(X[w] - j) / 250)
check("처짐 2 mm → 꺾임점 봉우리 0.4167 mm 삼각형 (손 계산과 일치)", np.nanmax(np.abs(v - tri)) < 1e-9, f"peak={np.nanmax(v):.4f}, err={np.nanmax(np.abs(v-tri)):.2e}")

# 6. 선형성: 결함 두 개를 합친 레일의 현측정 = 각각의 합, 크기 2배 → 값 2배
both = [(21, 21), (23, 23), (21, 23)]
v_both = rs.versine_of_profile(X, both)
v_a = rs.versine_of_profile(X, [(21, 21), (23, 23), (21, 21)])
v_b = rs.versine_of_profile(X, [(21, 21), (21, 21), (21, 23)])
check("선형성: 두 결함을 겹친 값 = 각각의 합", np.nanmax(np.abs(v_both - (v_a + v_b))) < 1e-9)
v2 = rs.versine_of_profile(X, [(21, 21), (25, 25), (21, 21)])
check("선형성: 단차 4 mm = 단차 2 mm 의 2배", np.nanmax(np.abs(v2 - 2 * v_a)) < 1e-9)

# 7. 부호: 받침이 내려앉으면(레일이 현보다 낮아지면) 센서-레일 거리는 커진다 (+)
pipes = [[21, 21], [21, 21], [21, 21]]
gd.apply_settle(pipes, [1], 2.0)
check("apply_settle: 600 받침 2 mm 침하 → 1번 오른쪽 끝·2번 왼쪽 끝 = 19", pipes[0][1] == 19 and pipes[1][0] == 19, str(pipes))
v = rs.versine_of_profile(np.array([600.0]), pipes)
check("침하 꺾임점에서 센서 값 증가 (+0.833 = 2 mm × 250/600)", abs(v[0] - 2.0 * 250 / 600) < 1e-9, f"{v[0]:.4f}")

# 8. 틈 스파이크: 이음부 정중앙에서 정확히 spike_amp 만큼 커진다
v = rs.sensor_reading(np.array([600.0, 1200.0, 900.0]), flat, 6.0, spike_amp=1.2, spike_sigma=5.0)
check("틈 스파이크: 600·1200 에서 +1.2, 900 에서 0", abs(v[0] - 7.2) < 1e-9 and abs(v[1] - 7.2) < 1e-9 and abs(v[2] - 6.0) < 1e-9, str(np.round(v, 4)))

# 9. 위치 보정 왕복: 엔코더를 일부러 0.88 배로 세게 한 가상 주행을 틈 스파이크로 되돌리면 원래 위치가 나온다
rng = np.random.default_rng(0)
x = np.arange(300.0, 1500.0, 1.0)
meas = rs.sensor_reading(x, flat, 6.0, spike_amp=1.2, spike_sigma=5.0) + rng.normal(0, 0.05, len(x))
enc = (x - 300.0) / 0.88
sp = sorted(find_spikes(enc, meas), key=lambda c: -c[1])[:2]
sp = sorted(sp)
scale = 600.0 / (sp[1][0] - sp[0][0])
x_rec = 600.0 + (enc - sp[0][0]) * scale
check("위치 보정 왕복: 복원 위치 오차 < 3 mm, 배율 0.88 ±0.01", np.max(np.abs(x_rec - x)) < 3 and abs(scale - 0.88) < 0.01, f"scale={scale:.4f}, maxerr={np.max(np.abs(x_rec-x)):.2f}")

# 10. 정답 구간: 이음부 단차(600) 는 센서가 350~850 에서 영향, 받침 침하(600) 는 0~1450
check("affected_range HF@600 = (350, 850)", gd.affected_range("HF", 1) == (350.0, 850.0), str(gd.affected_range("HF", 1)))
check("affected_range 침하@600 = (0, 1450)", gd.affected_range("C", [1]) == (0.0, 1450.0), str(gd.affected_range("C", [1])))

# 11. 판정 규칙 (논문 2.3): E 2.0 → 정상, 2.5 → 주의, 5.1 → 위험 / HF 0.49 정상, 0.5 주의, 1.01 위험
check("판정 규칙 E: 2.0 정상, 2.5 주의, 5.1 위험",
      (gd.stage_of("E", 2.0), gd.stage_of("E", 2.5), gd.stage_of("E", 5.1)) == ("normal", "caution", "danger"))
check("판정 규칙 HF: 0.49 정상, 0.5 주의, 1.01 위험",
      (gd.stage_of("HF", 0.49), gd.stage_of("HF", 0.5), gd.stage_of("HF", 1.01)) == ("normal", "caution", "danger"))

# 12. 잡음 은행: 평균이 0 근처, 크기가 실측 흔들림과 같다 (좌 ≈ 0.135, 우 ≈ 0.089)
for s, target in [("left", 0.135), ("right", 0.089)]:
    B = np.array(gd.CAL["noise_bank"][s])
    rms = float(np.sqrt(np.mean(B ** 2)))
    check(f"잡음 은행 {s}: 평균 |{np.mean(B):.3f}| < 0.02, RMS {rms:.3f} ≈ {target}", abs(np.mean(B)) < 0.02 and abs(rms - target) < 0.03)

# 13. 레일 다시 놓임 변형: 요청한 RMS 가 그대로 나오고, 결함 없는 레일에 더해도 평균은 0 근처
pert = gd.rail_perturbation(np.random.default_rng(3), 0.2)
xx = np.arange(300, 1500, 2.0)
vv = (pert(xx + 250) + pert(xx - 250)) / 2 - pert(xx)
check("다시 놓임 변형: 현측정 RMS = 0.2 (요청값)", abs(np.sqrt(np.mean(vv ** 2)) - 0.2) < 1e-6, f"{np.sqrt(np.mean(vv**2)):.4f}")

ok = sum(1 for _, c, _ in results if c)
for name, c, d in results:
    print(("PASS " if c else "FAIL ") + name + (f"   [{d}]" if d and not c else ""))
print(f"\n{ok}/{len(results)} 통과")
