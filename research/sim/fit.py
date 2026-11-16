"""실측 주행 한 회차에 가상 모델을 맞추고 오차를 잰다.

맞추는 값(좌·우 각각):
  H        센서 설치 높이(평평한 레일에서의 센서-레일 거리)
  d600     600 mm 이음부에서 2번 파이프 왼쪽 끝이 설계 높이보다 얼마나 높은가(+ 위)
  d1200    1200 mm 이음부에서 3번 파이프 왼쪽 끝이 설계 높이보다 얼마나 높은가
  spike    이음부 틈 위에서 값이 튀는 크기
받침 배치는 논문 표 2 의 구성을 그대로 쓴다. 파이프 자체의 휨은 넣지 않는다(정상 주행 6회 평균이 있어야 분리 가능).
"""
import sys
import numpy as np
from scipy.optimize import least_squares
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from load_run import load_run
import railsim as rs

for f in font_manager.findSystemFonts():
    if "NotoSansCJK" in f and "Regular" in f:
        font_manager.fontManager.addfont(f)
plt.rcParams["font.family"] = "Noto Sans CJK KR"
plt.rcParams["axes.unicode_minus"] = False

JOINT_EXCL = 20.0   # 이음부 ±20 mm 는 오차 계산에서 제외
X_FIT = (350.0, 1500.0)


def model_side(x, layout, H, d600, d1200, spike, gain=1.0):
    pipes = [list(p) for p in rs.support_heights(layout)]
    pipes[1][0] += d600
    pipes[2][0] += d1200
    return rs.sensor_reading(x, pipes, H, gain=gain, spike_amp=spike, spike_sigma=5.0), pipes


def fit_side(x, gap, layout):
    m = (x >= X_FIT[0]) & (x <= X_FIT[1])
    excl = np.zeros_like(x, dtype=bool)
    for j in rs.JOINTS:
        excl |= np.abs(x - j) < JOINT_EXCL
    use = m & ~excl

    def resid(p):
        H, d600, d1200 = p
        y, _ = model_side(x[use], layout, H, d600, d1200, 0.0)
        return y - gap[use]

    p0 = [np.median(gap[use]), 0.0, 0.0]
    r = least_squares(resid, p0)
    H, d600, d1200 = r.x
    # 틈 스파이크 크기는 이음부 ±20 mm 안에서 따로 맞춤
    y0, _ = model_side(x, layout, H, d600, d1200, 0.0)
    spike = float(np.clip(np.nanmax((gap - y0)[excl & m]), 0, 3)) if (excl & m).any() else 0.0
    y, pipes = model_side(x, layout, H, d600, d1200, spike)
    res = (gap - y)[use]
    rmse = float(np.sqrt(np.mean(res ** 2)))
    mae = float(np.mean(np.abs(res)))
    return dict(H=H, d600=d600, d1200=d1200, spike=spike, rmse=rmse, mae=mae,
                y=y, pipes=pipes, use=use, excl=excl)


def peak_stats(x, gap, y, center, half=250.0, base_half=(300.0, 350.0)):
    """이음부 주변 신호의 봉우리 크기(실측 vs 모델). 봉우리 = 중심 ±100 평균 − 바깥 기준 평균."""
    inner = np.abs(x - center) < 100
    inner &= ~(np.abs(x - center) < JOINT_EXCL)
    outer = (np.abs(x - center) > base_half[0]) & (np.abs(x - center) < base_half[1])
    if inner.sum() < 5 or outer.sum() < 5:
        return None
    return (float(np.mean(gap[inner]) - np.mean(gap[outer])),
            float(np.mean(y[inner]) - np.mean(y[outer])))


def step_stats(x, gap, y, center, w=(60.0, 230.0)):
    """이음부 앞 w 구간 평균 − 뒤 w 구간 평균 (단차 신호의 크기)."""
    before = (x > center - w[1]) & (x < center - w[0])
    after = (x > center + w[0]) & (x < center + w[1])
    if before.sum() < 5 or after.sum() < 5:
        return None
    return (float(np.mean(gap[before]) - np.mean(gap[after])),
            float(np.mean(y[before]) - np.mean(y[after])))


def main(path, config_name, out_png, out_csv):
    r = load_run(path)
    cfg = rs.CONFIGS[config_name]
    fig, axes = plt.subplots(3, 1, figsize=(13, 11), sharex=True,
                             gridspec_kw=dict(height_ratios=[1, 2, 2]))
    report = [f"파일: {path}", f"구성: {config_name}  (좌 {cfg['L']} / 우 {cfg['R']})", ""]
    rows = []
    for ax, (s, key, c) in zip(axes[1:], [("left", "L", "tab:blue"), ("right", "R", "tab:red")]):
        v = r[s]
        x, gap = v["x"], v["gap"]
        f = fit_side(x, gap, cfg[key])
        y = f["y"]
        # 가상 레일 높이 선
        xx = np.linspace(0, rs.RAIL_LEN, 1801)
        hh = rs.rail_height(xx, f["pipes"])
        axes[0].plot(xx, hh, c, lw=1.4, label=f"{'좌' if s=='left' else '우'} 레일 높이(모델)")
        ax.plot(x, gap, c, lw=0.9, alpha=0.9, label=f"실측 {'좌' if s=='left' else '우'} 센서")
        ax.plot(x, y, "k--", lw=1.2, label="가상 모델")
        for j in rs.JOINTS:
            ax.axvspan(j - JOINT_EXCL, j - JOINT_EXCL + 2 * JOINT_EXCL, color="0.85", lw=0)
        ax.axvspan(0, X_FIT[0], color="0.95", lw=0); ax.axvspan(X_FIT[1], rs.RAIL_LEN, color="0.95", lw=0)
        ax.set_ylabel("센서-레일 거리 mm"); ax.grid(alpha=.4); ax.legend(loc="lower left", fontsize=9)
        ax.set_ylim(np.nanpercentile(gap, 0.5) - 0.3, np.nanpercentile(gap, 99.5) + 0.6)
        side_kr = "좌" if s == "left" else "우"
        report += [f"[{side_kr}] 설치 높이 H = {f['H']:.2f} mm, 600 이음부 높이차 = {f['d600']:+.2f} mm, "
                   f"1200 이음부 높이차 = {f['d1200']:+.2f} mm, 틈 스파이크 = {f['spike']:.2f} mm",
                   f"[{side_kr}] 실측-모델 오차: RMSE {f['rmse']:.3f} mm, 평균 절대 오차 {f['mae']:.3f} mm "
                   f"(x {X_FIT[0]:.0f}~{X_FIT[1]:.0f} mm, 이음부 ±{JOINT_EXCL:.0f} mm 제외)"]
        for j in rs.JOINTS:
            pk = peak_stats(x, gap, y, j)
            st = step_stats(x, gap, y, j)
            if pk:
                report.append(f"[{side_kr}] {j:.0f} mm 봉우리 크기: 실측 {pk[0]:+.2f} / 모델 {pk[1]:+.2f} mm")
            if st:
                report.append(f"[{side_kr}] {j:.0f} mm 앞뒤 단차 신호: 실측 {st[0]:+.2f} / 모델 {st[1]:+.2f} mm")
        report.append("")
        for xi, gi, yi, ti in zip(x, gap, y, v["t"]):
            rows.append((s, ti, xi, gi, yi))
    axes[0].set_ylabel("레일 높이 mm"); axes[0].grid(alpha=.4); axes[0].legend(fontsize=9)
    axes[0].set_title(f"가상 레일 모델과 실측 주행 비교 — 구성 {config_name}")
    axes[-1].set_xlabel("레일 위치 x  mm  (이음부 600, 1200 / 회색 띠 = 오차 계산 제외)")
    plt.tight_layout(); plt.savefig(out_png, dpi=110)
    import csv
    with open(out_csv, "w", newline="") as fp:
        w = csv.writer(fp); w.writerow(["side", "t_s", "rail_x_mm", "real_gap_mm", "model_gap_mm"])
        w.writerows(rows)
    print("\n".join(report))
    return report


if __name__ == "__main__":
    path = sys.argv[1]
    cfg = sys.argv[2] if len(sys.argv) > 2 else "4 좌우 높이차"
    main(path, cfg, sys.argv[3] if len(sys.argv) > 3 else "fit.png",
         sys.argv[4] if len(sys.argv) > 4 else "fit.csv")
