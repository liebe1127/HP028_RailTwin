"""맞춘 모델로 가상 주행을 만들어 보는 맛보기.

- 결함 크기를 바꿔가며 센서 신호를 만들고 CSV 로 저장한다.
- 잡음은 지어내지 않고, 실측에서 모델을 뺀 나머지(레일 본래의 굴곡 + 센서 흔들림)를
  무작위로 밀어서(circular shift) 다시 쓴다. 정상 주행 6회 평균이 생기면 그걸로 바꿔야 한다.
"""
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

import railsim as rs
from load_run import load_run
from fit import fit_side, X_FIT

for f in font_manager.findSystemFonts():
    if "NotoSansCJK" in f and "Regular" in f:
        font_manager.fontManager.addfont(f)
plt.rcParams["font.family"] = "Noto Sans CJK KR"
plt.rcParams["axes.unicode_minus"] = False

SPEED = 52.0      # mm/s (논문 3.1)
DT = 0.020        # s (센서 모듈 20 ms)


def residual_bank(path, config_name):
    """실측 회차에서 좌·우 잔차(실측-모델)를 꺼내 잡음 은행으로 쓴다."""
    r = load_run(path)
    cfg = rs.CONFIGS[config_name]
    bank = {}
    for s, key in [("left", "L"), ("right", "R")]:
        f = fit_side(r[s]["x"], r[s]["gap"], cfg[key])
        res = (r[s]["gap"] - f["y"])[f["use"]]
        bank[s] = dict(res=res, H=f["H"], spike=f["spike"])
    return bank


def make_run(pipes_L, pipes_R, bank, rng, x0=300.0, x1=1500.0, label=""):
    n = int((x1 - x0) / SPEED / DT)
    t = np.arange(n) * DT
    x = x0 + SPEED * t
    out = {"t_s": t, "rail_x_mm": x}
    for s, pipes in [("left", pipes_L), ("right", pipes_R)]:
        b = bank[s]
        clean = rs.sensor_reading(x, pipes, b["H"], spike_amp=b["spike"], spike_sigma=5.0)
        res = b["res"]
        k = rng.integers(len(res))
        noise = np.roll(res, k)
        noise = np.resize(noise, n)
        out[f"{s}_sensor_distance_mm"] = clean + noise
        out[f"{s}_clean_mm"] = clean
    out["label"] = label
    return pd.DataFrame(out)


def main(path, config_name="4 좌우 높이차", out_png="demo_scenarios.png"):
    bank = residual_bank(path, config_name)
    rng = np.random.default_rng(1)
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    base = rs.support_heights("<S D D S>")        # 평평한 정상 레일
    # 시나리오 1: 1200 이음부 단차(3번 파이프 왼쪽 끝) 크기를 바꿔가며
    for step, c in zip([0.5, 1.0, 2.0, 3.0], ["0.6", "tab:green", "tab:orange", "tab:red"]):
        p = [list(q) for q in base]
        p[2][0] += step
        df = make_run(p, base, bank, rng, label=f"step{step}")
        axes[0].plot(df.rail_x_mm, df.left_sensor_distance_mm, color=c, lw=.9, label=f"이음부 단차 {step} mm")
        df.to_csv(f"demo_step_{step}mm.csv", index=False)
    axes[0].set_title("가상 주행 맛보기 — 1200 mm 이음부 단차 크기를 바꿔가며 (좌 센서, 실측 잡음 포함)")
    axes[0].grid(alpha=.4); axes[0].legend(fontsize=9); axes[0].set_ylabel("센서-레일 거리 mm")
    # 시나리오 2: 가운데 파이프 처짐(수직 방향 변형) 크기를 바꿔가며
    for sag, c in zip([0.5, 1.0, 2.0, 4.0], ["0.6", "tab:green", "tab:orange", "tab:red"]):
        p = [[23.0, 23.0 - sag], [23.0 - sag, 23.0 - sag], [23.0 - sag, 23.0]]
        df = make_run(p, base, bank, rng, label=f"sag{sag}")
        axes[1].plot(df.rail_x_mm, df.left_sensor_distance_mm, color=c, lw=.9, label=f"수직 방향 변형 {sag} mm")
        df.to_csv(f"demo_sag_{sag}mm.csv", index=False)
    axes[1].set_title("가상 주행 맛보기 — 가운데 600 mm 구간 처짐 크기를 바꿔가며 (좌 센서)")
    axes[1].grid(alpha=.4); axes[1].legend(fontsize=9); axes[1].set_ylabel("센서-레일 거리 mm")
    axes[1].set_xlabel("레일 위치 x mm")
    plt.tight_layout(); plt.savefig(out_png, dpi=110)
    print("saved", out_png)


if __name__ == "__main__":
    main(sys.argv[1])
