"""9/28 실측(정상 6회, 이음부 단차 6회)과 가상 모형의 세로 가속도 비교.

사용 (research/dyn 에서):  python3 check_0928.py
출력: ../results/dyn_check_0928.md, ../results/dyn_check_0928.png

보는 것
  1. 바퀴 위치: 단차 주행에서 거리·가속도가 변하는 위치로 센서 → 바퀴 거리를 추정
  2. 충격 크기: 바퀴가 이음부를 넘는 네 위치에서의 |세로 가속도| 최댓값을 실측과 가상에서 같은 방법으로 계산
  3. 맞추기: 고유 진동수·감쇠비를 거친 격자로 바꿔 가며 실측과의 차이가 가장 작은 값을 찾음
  4. 표본 속도를 올리면 같은 충격이 얼마나 크게 보이는지 (측정 설정 결정용)
9/28 표본은 50 Hz 라 충격 모양이 거의 남지 않는다. 여기서 맞춘 값은 크기 자릿수 확인용이다.
"""
from __future__ import annotations

import csv
import glob
import os
import unicodedata

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import raildyn as rd
import railsim as rs

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "배준호_전달", "레일측정데이터", "보정")
OUT = os.path.join(HERE, "..", "results")
FOLDERS = {"정상": "1. 정상", "단차": "2. 단차"}
PIPES = {"정상": rd.flat_pipes(), "단차": rs.support_heights(rs.CONFIGS["2 이음부 단차"]["L"])}
EVENTS = {"앞바퀴 600": 330.0, "뒷바퀴 600": 870.0, "앞바퀴 1200": 930.0, "뒷바퀴 1200": 1470.0}
HALF = 35.0          # 사건 위치 ± 이 범위에서 최댓값을 본다
X_MAX = 1500.0       # 그 뒤는 레일 끝 충격(5~10 m/s²)이라 뺀다

for font in ("NanumGothic", "Noto Sans CJK KR", "AppleGothic", "Malgun Gothic"):
    if any(font in f.name for f in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = font
        break
plt.rcParams["axes.unicode_minus"] = False


def _col(rows, key):
    return np.array([float(r[key]) if r.get(key) not in (None, "") else np.nan for r in rows])


def load_real(folder):
    runs = []
    for path in sorted(glob.glob(os.path.join(DATA, folder, "*.csv"))):
        rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
        x = _col(rows, "rail_x_mm")
        ok = (_col(rows, "analysis_window") == 1) & np.isfinite(x)
        run = {"name": unicodedata.normalize("NFC", os.path.basename(path))[:11], "x": x[ok]}
        for side in ("left", "right"):
            az = _col(rows, f"{side}_mpu_accel_z")[ok]
            run[f"az_{side}"] = az - np.nanmedian(az)
            run[f"gap_{side}"] = _col(rows, f"{side}_sensor_distance_mm")[ok]
            run[f"valid_{side}"] = _col(rows, "sensor_valid")[ok] == 1
        runs.append(run)
    return runs


def event_peaks(x, az):
    """네 사건 위치의 |az| 최댓값과, 사건에서 먼 곳의 95 백분위(평소 흔들림)."""
    d = np.abs(az)
    keep = np.isfinite(d) & (x < X_MAX)
    far = keep.copy()
    out = {}
    for name, c in EVENTS.items():
        near = keep & (np.abs(x - c) <= HALF)
        out[name] = float(d[near].max()) if near.any() else np.nan
        far &= np.abs(x - c) > HALF + 25
    out["평소"] = float(np.percentile(d[far], 95))
    return out


def real_stats(runs):
    rows = [event_peaks(r["x"], r[f"az_{s}"]) for r in runs for s in ("left", "right")]
    return {k: float(np.nanmedian([row[k] for row in rows])) for k in rows[0]}


def sim_stats(pipes, cart, imu, n=40, seed=1, speed=50.5):
    rng = np.random.default_rng(seed)
    run = rd.simulate_side(pipes, cart, speed=speed)
    rows = []
    for _ in range(n):
        m = rd.measure(run, imu, rng)
        rows.append(event_peaks(m["x"], m["az"]))
    return {k: float(np.nanmedian([row[k] for row in rows])) for k in rows[0]}, run


def wheel_offsets(runs_step, runs_normal):
    """단차 − 정상 거리 신호가 가장 급하게 변하는 위치 → 센서에서 바퀴까지 거리."""
    grid = np.arange(280.0, 1541.0, 4.0)

    def median_profile(runs, side, skip_first=False):
        prof = []
        for r in runs[1:] if skip_first else runs:      # 정상 첫 회차(31차)는 센서 어긋남이 있어 뺀다
            ok = r[f"valid_{side}"] & np.isfinite(r[f"gap_{side}"])
            order = np.argsort(r["x"][ok])
            prof.append(np.interp(grid, r["x"][ok][order], r[f"gap_{side}"][ok][order]))
        return np.median(prof, axis=0)

    found = {}
    for side in ("left", "right"):
        diff = median_profile(runs_step, side) - median_profile(runs_normal, side, skip_first=True)
        slope = np.gradient(np.convolve(diff, np.ones(5) / 5, mode="same"), grid)
        for name, (lo, hi) in {"앞바퀴 600": (300, 420), "뒷바퀴 600": (800, 900),
                               "앞바퀴 1200": (900, 1000), "뒷바퀴 1200": (1400, 1500)}.items():
            m = (grid >= lo) & (grid <= hi)
            found[(side, name)] = float(grid[m][np.argmax(np.abs(slope[m]))])
    return found


def chord_fit(runs_step, runs_normal):
    """단차 − 정상 거리 신호를 railsim 현측정 파형과 비교해, 바퀴 간격을 바꿔 가며 오차(RMSE, mm)를 본다."""
    grid = np.arange(350.0, 1501.0, 4.0)
    keep = np.ones(len(grid), bool)
    for j in rs.JOINTS:
        keep &= np.abs(grid - j) > 20
    out = {}
    for side in ("left", "right"):
        prof = {}
        for key, runs in (("s", runs_step), ("n", runs_normal[1:])):
            rows = []
            for r in runs:
                ok = r[f"valid_{side}"] & np.isfinite(r[f"gap_{side}"])
                order = np.argsort(r["x"][ok])
                rows.append(np.interp(grid, r["x"][ok][order], r[f"gap_{side}"][ok][order]))
            prof[key] = np.median(rows, axis=0)
        diff = prof["s"] - prof["n"]
        for wb in range(460, 601, 20):
            model = rs.versine_of_profile(grid, PIPES["단차"], wheelbase=float(wb)) - rs.versine_of_profile(grid, PIPES["정상"], wheelbase=float(wb))
            resid = (diff - model)[keep]
            out[(side, wb)] = float(np.sqrt(np.mean((resid - resid.mean()) ** 2)))
    return out


def fit(real):
    """고유 진동수·감쇠비 격자 탐색. 단차·정상 두 구성의 사건 네 곳 충격 크기(로그)를 맞춘다."""
    imu = rd.Imu()
    best = None
    table = []
    for f in (15, 20, 30, 40, 60, 80, 120):
        for zeta in (0.05, 0.1, 0.2, 0.4):
            cart = rd.Cart(f_bounce_hz=f, zeta=zeta)
            loss = 0.0
            lift = 1.0
            for cfg in ("단차", "정상"):
                s, run = sim_stats(PIPES[cfg], cart, imu, n=24)
                lift = min(lift, run["load_min"])
                loss += sum((np.log(s[e]) - np.log(real[cfg][e])) ** 2 for e in EVENTS)
            table.append((f, zeta, loss, lift))
            if best is None or loss < best[2]:
                best = (f, zeta, loss, lift)
    return best, table


def main():
    os.makedirs(OUT, exist_ok=True)
    runs = {name: load_real(folder) for name, folder in FOLDERS.items()}
    real = {name: real_stats(r) for name, r in runs.items()}
    offs = wheel_offsets(runs["단차"], runs["정상"])
    chord = chord_fit(runs["단차"], runs["정상"])
    best, table = fit(real)
    cart = rd.Cart(f_bounce_hz=best[0], zeta=best[1])
    sim = {}
    sim_run = {}
    for cfg in FOLDERS:
        sim[cfg], sim_run[cfg] = sim_stats(PIPES[cfg], cart, rd.Imu(), n=200)
    rates = [("50 Hz, 필터 44 Hz (9/28 설정)", rd.Imu(50, 44)), ("50 Hz, 필터 21 Hz", rd.Imu(50, 21)),
             ("200 Hz, 필터 44 Hz", rd.Imu(200, 44)), ("200 Hz, 필터 94 Hz", rd.Imu(200, 94)),
             ("500 Hz, 필터 184 Hz", rd.Imu(500, 184)), ("1000 Hz, 필터 없음", rd.Imu(1000, 0))]
    # 고유 진동수 대역별로 실측과 가장 가까운 후보 세 가지 (9/28 자료로는 이 중 어느 것인지 가릴 수 없다)
    cands = []
    for lo, hi in ((0, 25), (25, 70), (70, 999)):
        cands.append(min((t for t in table if lo < t[0] <= hi and t[3] > 0), key=lambda t: t[2]))
    rate_rows = []
    for label, imu in rates:
        cells = []
        for f, zeta, _, _ in cands:
            c = rd.Cart(f_bounce_hz=f, zeta=zeta)
            a, _ = sim_stats(PIPES["단차"], c, imu, n=120)
            b, _ = sim_stats(PIPES["정상"], c, imu, n=120)
            cells.append((np.mean([a[e] for e in EVENTS]), np.mean([b[e] for e in EVENTS])))
        rate_rows.append((label, cells))

    # ── 그림 ──
    fig, axes = plt.subplots(3, 1, figsize=(10, 10))
    ax = axes[0]
    xw = np.arange(570.0, 640.0, 0.02)
    ax.plot(xw, rd.wheel_path(xw, PIPES["단차"], cart.r_front_mm) - 21.0, label="바퀴 중심 (반지름 23.5 mm)")
    ax.plot(xw, rs.rail_height(xw, PIPES["단차"]) - 21.0, "k--", lw=1, label="레일 윗면")
    ax.set_xlabel("바퀴 축 위치 (mm)"); ax.set_ylabel("높이 (mm)"); ax.set_title("2 mm 단차를 넘는 바퀴 중심 궤적 (가상)"); ax.legend()
    ax = axes[1]
    r = sim_run["단차"]
    ax.plot(r["x"], r["az"], color="0.75", lw=0.6, label="가상, 필터·표본 전 (4 kHz)")
    m = rd.measure(r, rd.Imu(), np.random.default_rng(3))
    ax.plot(m["x"], m["az"], "C0.-", lw=0.8, ms=3, label="가상, 50 Hz 표본")
    real_run = runs["단차"][1]
    keep = real_run["x"] < X_MAX
    ax.plot(real_run["x"][keep], real_run["az_left"][keep], "C3.-", lw=0.8, ms=3, alpha=0.8, label=f"실측 {real_run['name']} 좌")
    for c in EVENTS.values():
        ax.axvline(c, color="k", lw=0.5, ls=":")
    ax.set_xlim(280, 1500); ax.set_ylim(-3, 3)
    ax.set_xlabel("센서 위치 (mm)"); ax.set_ylabel("세로 가속도 (m/s²)")
    ax.set_title(f"이음부 단차 주행의 세로 가속도 (가상: {best[0]} Hz, 감쇠비 {best[1]})"); ax.legend(loc="upper right", fontsize=8)
    ax = axes[2]
    names = list(EVENTS) + ["평소"]
    pos = np.arange(len(names)); w = 0.2
    for i, (cfg, color) in enumerate((("단차", "C3"), ("정상", "C2"))):
        ax.bar(pos + (2 * i - 1.5) * w, [real[cfg][k] for k in names], w, color=color, label=f"실측 {cfg}")
        ax.bar(pos + (2 * i - 0.5) * w, [sim[cfg][k] for k in names], w, color=color, alpha=0.45, label=f"가상 {cfg}")
    ax.set_xticks(pos); ax.set_xticklabels(names); ax.set_ylabel("|세로 가속도| 최댓값 (m/s²)")
    ax.set_title("바퀴가 이음부를 넘는 위치의 충격 크기 (주행별 최댓값의 중앙값)"); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "dyn_check_0928.png"), dpi=130)

    # ── 보고서 ──
    L = []
    L.append("# 가상 모형 확장 1차 — 9/28 실측과의 비교\n")
    L.append("`research/dyn/check_0928.py` 가 만든 파일. 9/28 정상 6회·이음부 단차 6회, 좌·우 센서 12개 기록.\n")
    L.append("## 1. 센서에서 바퀴까지 거리 (단차 − 정상 거리 신호가 가장 급하게 변하는 위치)\n")
    L.append("| 사건 | 이음부 | 좌 센서 위치 | 우 센서 위치 | 센서 → 바퀴 (좌 / 우) |\n|---|---|---|---|---|")
    for name in EVENTS:
        joint = 600.0 if "600" in name else 1200.0
        l, r_ = offs[("left", name)], offs[("right", name)]
        L.append(f"| {name} | {joint:.0f} | {l:.0f} | {r_:.0f} | {abs(joint - l):.0f} / {abs(joint - r_):.0f} mm |")
    inner = [abs(600 - offs[(s, '뒷바퀴 600')]) for s in ("left", "right")] + [abs(1200 - offs[(s, '앞바퀴 1200')]) for s in ("left", "right")]
    L.append(f"\n이음부 사이(600~1200 mm)에 있어 위치 보정이 가장 믿을 만한 두 사건의 평균은 {np.mean(inner):.0f} mm 다. "
             "가상 모형과 서버 판정은 250 mm(바퀴 간격 500 mm)를 쓴다. 변화 구간의 폭(바퀴가 모서리를 넘는 약 ±10 mm)과 "
             "4 mm 격자 때문에 ±10 mm 정도의 오차가 있다. **줄자로 앞뒤 바퀴 축 간격과 센서 위치를 재서 확인해야 한다.**\n")
    L.append("### 바퀴 간격을 바꿔 가며 본 거리 신호 오차 (단차 − 정상, railsim 현측정 파형과의 RMSE, mm)\n")
    L.append("| 바퀴 간격 | " + " | ".join(str(wb) for wb in range(460, 601, 20)) + " |\n|---|" + "---|" * 8)
    for side, label in (("left", "좌"), ("right", "우")):
        L.append(f"| {label} | " + " | ".join(f"{chord[(side, wb)]:.3f}" for wb in range(460, 601, 20)) + " |")
    L.append("")
    L.append("## 2. 충격 크기: 실측과 가상 (m/s², 주행별 최댓값의 중앙값)\n")
    L.append(f"가상 모형 변수: 고유 진동수 {best[0]} Hz, 감쇠비 {best[1]} (격자 탐색으로 고른 값), 나머지는 `raildyn.Cart` 기본값. "
             "표본 50 Hz, 필터 44 Hz, 잡음 0.15 m/s².\n")
    L.append("| 위치 | 실측 단차 | 가상 단차 | 실측 정상 | 가상 정상 |\n|---|---|---|---|---|")
    for k in list(EVENTS) + ["평소"]:
        L.append(f"| {k} | {real['단차'][k]:.2f} | {sim['단차'][k]:.2f} | {real['정상'][k]:.2f} | {sim['정상'][k]:.2f} |")
    L.append("\n## 3. 고유 진동수·감쇠비를 바꿨을 때의 차이 (작을수록 실측에 가깝다)\n")
    L.append("| 고유 진동수 \\ 감쇠비 | 0.05 | 0.1 | 0.2 | 0.4 |\n|---|---|---|---|---|")
    for f in (15, 20, 30, 40, 60, 80, 120):
        cells = []
        for zeta in (0.05, 0.1, 0.2, 0.4):
            row = next(t for t in table if t[0] == f and t[1] == zeta)
            cells.append(f"{row[2]:.2f}" + (" (바퀴 뜸)" if row[3] <= 0 else ""))
        L.append(f"| {f} Hz | " + " | ".join(cells) + " |")
    L.append("\n9/28 표본(50 Hz)으로는 고유 진동수와 감쇠비를 정할 수 없다. 15 Hz·40 Hz·120 Hz 대역에 비슷한 정도로 맞는 값이 따로 있다.\n")
    L.append("## 4. 표본 속도에 따라 같은 충격이 얼마나 보이나 (가상, 사건 네 곳 평균, m/s²)\n")
    head = " | ".join(f"{f} Hz·감쇠 {z} (단차 / 정상 이음부)" for f, z, _, _ in cands)
    L.append(f"| 설정 | {head} |\n|---|" + "---|" * len(cands))
    for label, cells in rate_rows:
        L.append(f"| {label} | " + " | ".join(f"{a:.2f} / {b:.2f}" for a, b in cells) + " |")
    L.append("\n세 열은 3절에서 대역별로 실측과 가장 가까웠던 후보다. 표본 하나당 잡음은 0.15 m/s² 로 같게 두었다. "
             "실제로는 필터를 넓히면 모터·롤러 진동이 더 들어와 평소 흔들림도 커질 수 있다.\n")
    open(os.path.join(OUT, "dyn_check_0928.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
