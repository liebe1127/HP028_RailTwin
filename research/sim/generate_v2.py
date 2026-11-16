"""가상 주행 생성기 v2 — 정상 6회로 맞춘 교정값(calibration.json)을 쓴다.

센서 값 = H + r(x) + 설계 받침 배치의 현측정 값 + 틈 스파이크 + 잡음
  H, r(x)  : 정상 6회 평균에서 (analyze24.py)
  잡음     : 정상 회차 각각이 6회 평균에서 벗어난 양을 그대로 가져와 무작위로 민다 (지어내지 않음)

사용 예
  python3 generate_v2.py            → 구성 2·3·4 를 각 6회 만들어 실측 6회와 나란히 그림 (compare_sim_real.png)
  코드에서 make_run(layout_L, layout_R, ...) 를 불러 임의 배치·크기의 주행을 만들 수 있다.
"""
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

import railsim as rs

for f in font_manager.findSystemFonts():
    if "NotoSansCJK" in f and "Regular" in f:
        font_manager.fontManager.addfont(f)
plt.rcParams["font.family"] = "Noto Sans CJK KR"
plt.rcParams["axes.unicode_minus"] = False

CAL = json.load(open("calibration.json"))
GRID = np.array(CAL["grid_mm"])
SPEED = 52.0
SPIKE = {"left": 1.2, "right": 1.0}   # 틈 스파이크 크기(정상 회차 평균에서 본 값)


def pipes_from(layout=None, pipes=None, joint_offsets=(0.0, 0.0)):
    """받침 배치 문자열 또는 파이프 끝 높이 목록 + 이음부 추가 단차(600, 1200에서 오른쪽 파이프 끝이 더 높은 양)."""
    p = [list(q) for q in (pipes if pipes is not None else rs.support_heights(layout))]
    p[1][0] += joint_offsets[0]
    p[2][0] += joint_offsets[1]
    return p


def make_run(pipes_L, pipes_R, rng, noise=True, label="", speed=SPEED):
    x = GRID
    t = (x - x[0]) / speed
    out = {"t_s": t, "rail_x_mm": x}
    for s, pipes in [("left", pipes_L), ("right", pipes_R)]:
        H = CAL[f"H_{s}"]; r = np.array(CAL[f"rshape_{s}"])
        clean = H + r + rs.versine_of_profile(x, pipes)
        for j in rs.JOINTS:
            clean = clean + SPIKE[s] * np.exp(-0.5 * ((x - j) / 5.0) ** 2)
        n = np.zeros_like(x)
        if noise:
            bank = np.array(CAL["noise_bank"][s])
            k = rng.integers(bank.shape[0])
            n = np.roll(bank[k], rng.integers(len(x)))
        out[f"{s}_sensor_distance_mm"] = clean + n
        out[f"{s}_clean_mm"] = clean
    df = pd.DataFrame(out)
    df["label"] = label
    return df


def real_runs(cfg):
    import glob, os
    A = {"left": [], "right": []}
    for f in sorted(glob.glob(f"../data/c{cfg}_r*.csv")):
        d = pd.read_csv(f)
        w = (d.analysis_window == 1) & (d.sensor_valid == 1)
        x = d.rail_x_mm[w].to_numpy(float)
        for s in A:
            g = d[f"{s}_sensor_distance_mm"][w].to_numpy(float)
            o = np.argsort(x, kind="stable")
            ux, inv = np.unique(np.round(x[o], 1), return_inverse=True)
            ug = np.bincount(inv, weights=g[o]) / np.bincount(inv)
            gi = np.interp(GRID, ux, ug, left=np.nan, right=np.nan)
            A[s].append(gi)
    return {s: np.array(v) for s, v in A.items()}


def main():
    rng = np.random.default_rng(7)
    names = {2: "2 이음부 단차", 3: "3 수직 방향 변형", 4: "4 좌우 높이차"}
    fig, axes = plt.subplots(3, 2, figsize=(15, 11), sharex=True)
    for i, cfg in enumerate([2, 3, 4]):
        cfgL = rs.CONFIGS[names[cfg]]["L"]; cfgR = rs.CONFIGS[names[cfg]]["R"]
        # 구성 4 의 우 레일은 실측에서 확인된 1200 단차 0.7 mm 를 넣는다
        pR = pipes_from(cfgR, joint_offsets=(0.0, 0.7 if cfg == 4 else 0.0))
        pL = pipes_from(cfgL)
        R = real_runs(cfg)
        sims = [make_run(pL, pR, rng, label=names[cfg]) for _ in range(6)]
        for j, (s, kr, c) in enumerate([("left", "좌", "tab:blue"), ("right", "우", "tab:red")]):
            ax = axes[i, j]
            for k in range(R[s].shape[0]):
                ax.plot(GRID, R[s][k], color=c, lw=0.7, alpha=0.6, label="실측 6회" if k == 0 else None)
            for k, df in enumerate(sims):
                ax.plot(GRID, df[f"{s}_sensor_distance_mm"], color="k", lw=0.7, alpha=0.5, ls="--",
                        label="가상 6회" if k == 0 else None)
            ax.set_title(f"{names[cfg]} — {kr} 레일", fontsize=10); ax.grid(alpha=.35); ax.legend(fontsize=8, loc="lower left")
            lo = np.nanpercentile(R[s], 0.5) - 0.3; hi = np.nanpercentile(R[s], 99.5) + 0.5
            ax.set_ylim(lo, hi)
            if j == 0: ax.set_ylabel("센서-레일 거리 mm")
        sims[0].to_csv(f"sim_cfg{cfg}_example.csv", index=False)
    for ax in axes[-1]: ax.set_xlabel("레일 위치 x mm")
    fig.suptitle("가상 주행(검정 점선) vs 실측 주행(색 실선) — 정상 6회로만 교정한 모델", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.97)); fig.savefig("compare_sim_real.png", dpi=110)
    print("saved compare_sim_real.png")


if __name__ == "__main__":
    main()
