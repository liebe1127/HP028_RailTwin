"""24회 주행으로 가상 모델을 제대로 검증한다.

순서
 1. 정상 6회 → 기준선(좌·우 평균 신호)과 잡음(회차 간 흔들림)
 2. 기준선 − 설치 높이 = 레일 본래의 굴곡 r(x)  (파이프 휨, 센서 장착 차이)
 3. 구성 2~4 예측 = 설치 높이 + r(x) + 설계 받침 배치의 현측정 값   ← 결함 회차는 전혀 안 본다
 4. 예측을 각 구성의 6회 평균 및 개별 회차와 비교해 오차를 잰다
 5. 변화 신호(평균 − 기준선)에 설계 파형을 배율로 맞춰 결함 크기를 추정 → 논문 표 2와 대조
"""
import glob, os, json
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

DATA = "../data"
GRID = np.arange(300.0, 1500.0 + 1e-9, 2.0)
JOINT_EXCL = 20.0
SIDES = [("left", "L", "좌", "tab:blue"), ("right", "R", "우", "tab:red")]
CFG_NAME = {1: "1 정상", 2: "2 이음부 단차", 3: "3 수직 방향 변형", 4: "4 좌우 높이차"}
CFG_PAPER = {2: "D S> <S D", 3: "S> D D <S", 4: None}


def joint_mask(x):
    m = np.zeros_like(x, dtype=bool)
    for j in rs.JOINTS:
        m |= np.abs(x - j) < JOINT_EXCL
    return m


def load_all():
    runs = {}
    for f in sorted(glob.glob(os.path.join(DATA, "c*_r*.csv"))):
        name = os.path.basename(f)[:-4]
        cfg = int(name[1]); run = int(name.split("_r")[1])
        d = pd.read_csv(f)
        w = (d.analysis_window == 1) & (d.sensor_valid == 1)
        x = d.rail_x_mm[w].to_numpy(float)
        rec = {"cfg": cfg, "run": run}
        for s, _, _, _ in SIDES:
            g = d[f"{s}_sensor_distance_mm"][w].to_numpy(float)
            # 같은 x 가 중복되면 평균, 단조 증가 보장
            order = np.argsort(x, kind="stable")
            xs, gs = x[order], g[order]
            ux, inv = np.unique(np.round(xs, 1), return_inverse=True)
            ug = np.bincount(inv, weights=gs) / np.bincount(inv)
            gi = np.interp(GRID, ux, ug, left=np.nan, right=np.nan)
            gi[(GRID < ux.min()) | (GRID > ux.max())] = np.nan
            rec[s] = gi
        runs[name] = rec
    return runs


def stack(runs, cfg, side):
    arr = np.array([r[side] for r in runs.values() if r["cfg"] == cfg])
    return arr


def main():
    runs = load_all()
    jm = joint_mask(GRID)
    use = ~jm
    out = {"grid_mm": GRID.tolist()}
    report = []

    # 1. 기준선과 잡음
    base, H, rshape, noise_bank = {}, {}, {}, {}
    for s, key, kr, c in SIDES:
        A = stack(runs, 1, s).copy()
        # 센서 이상 구간 제거: 6회 중앙값에서 0.8 mm 넘게 벗어난 점(논문이 언급한 우 센서 1.2 mm 오프셋 회차)
        med = np.nanmedian(A, axis=0)
        bad = np.abs(A - med) > 0.8
        n_bad = int(bad.sum())
        A[bad] = np.nan
        mean = np.nanmean(A, axis=0); std = np.nanstd(A, axis=0, ddof=1)
        base[s] = mean
        H[s] = float(np.nanmean(mean[use]))
        rshape[s] = mean - H[s]
        dev = A - mean
        noise_bank[s] = dev
        if n_bad:
            report.append(f"[정상 6회 {kr}] 센서 이상으로 제외한 점 {n_bad}개 (중앙값에서 0.8 mm 초과)")
        sig_run = float(np.sqrt(np.nanmean(dev[:, use] ** 2)))
        sig_x = float(np.nanmean(std[use]))
        report.append(f"[정상 6회 {kr}] 설치 높이 H = {H[s]:.3f} mm, 레일 본래 굴곡 r(x) 범위 "
                      f"{np.nanmin(rshape[s][use]):+.2f} ~ {np.nanmax(rshape[s][use]):+.2f} mm, "
                      f"회차 간 흔들림(1회 RMS) {sig_run:.3f} mm, 6회 평균의 불확실도 약 {sig_run/np.sqrt(6):.3f} mm")
        out[f"baseline_{s}"] = mean.tolist(); out[f"baseline_std_{s}"] = std.tolist()
        out[f"H_{s}"] = H[s]
    report.append("")

    # 2. 구성 2~4 예측과 비교
    results = []
    fig, axes = plt.subplots(3, 2, figsize=(15, 12), sharex=True)
    figc, axc = plt.subplots(3, 2, figsize=(15, 12), sharex=True)
    for i, cfg in enumerate([2, 3, 4]):
        for j, (s, key, kr, c) in enumerate(SIDES):
            layout = rs.CONFIGS[CFG_NAME[cfg]][key]
            pipes = rs.support_heights(layout)
            v_design = rs.versine_of_profile(GRID, pipes)       # 결함 성분(설계 2 mm)
            pred = H[s] + rshape[s] + v_design                   # 결함 회차는 안 보고 만든 예측
            A = stack(runs, cfg, s)
            mean = np.nanmean(A, axis=0); std = np.nanstd(A, axis=0, ddof=1)
            change = mean - base[s]
            m = use & np.isfinite(mean) & np.isfinite(pred)
            rmse_mean = float(np.sqrt(np.mean((mean - pred)[m] ** 2)))
            rmse_runs = [float(np.sqrt(np.nanmean(((A[k] - pred)[m]) ** 2))) for k in range(A.shape[0])]
            # 결함 크기 추정: change ≈ a * v_design (최소제곱)
            vv = v_design[m]; cc = change[m]
            a = float(np.dot(vv, cc) / np.dot(vv, vv)) if np.dot(vv, vv) > 1e-9 else np.nan
            size_est = 2.0 * a if np.isfinite(a) else np.nan
            # 우 레일(구성 4): 설계는 평평. 1200 단차 크기를 따로 추정
            step_est = np.nan
            if cfg == 4 and s == "right":
                p = [list(q) for q in pipes]; p[2][0] += 1.0
                v_step = rs.versine_of_profile(GRID, p)
                vs = v_step[m]
                step_est = float(np.dot(vs, cc) / np.dot(vs, vs))
            # 봉우리 높이로 본 결함 크기 (처짐 구성: 600·1200 꺾임의 삼각 봉우리)
            peak_size = np.nan
            if layout == "S> D D <S":
                flat = ((GRID < 340) | ((GRID > 860) & (GRID < 940)) | (GRID > 1460)) & m
                pk = np.zeros_like(GRID, dtype=bool)
                for jn in rs.JOINTS:
                    pk |= (np.abs(GRID - jn) >= JOINT_EXCL) & (np.abs(GRID - jn) <= 40)
                pk &= m
                real_pk = np.mean(change[pk]) - np.mean(change[flat])
                model_pk = np.mean(v_design[pk]) - np.mean(v_design[flat])
                peak_size = 2.0 * real_pk / model_pk
            res = dict(cfg=CFG_NAME[cfg], side=kr, layout=layout, rmse_6avg=rmse_mean, size_peak_mm=peak_size,
                       rmse_1run_mean=float(np.mean(rmse_runs)), rmse_1run_max=float(np.max(rmse_runs)),
                       size_est_mm=size_est, step1200_est_mm=step_est)
            results.append(res)
            # 그림: 원 신호
            ax = axes[i, j]
            for k in range(A.shape[0]):
                ax.plot(GRID, A[k], color=c, lw=0.5, alpha=0.35)
            ax.plot(GRID, mean, color=c, lw=1.6, label=f"실측 6회 평균 ({kr})")
            ax.fill_between(GRID, mean - std, mean + std, color=c, alpha=0.15, lw=0)
            ax.plot(GRID, pred, "k--", lw=1.3, label="가상 모델 예측 (정상 6회로만 만든 것)")
            ax.plot(GRID, base[s], color="0.5", lw=0.8, ls=":", label="정상 기준선")
            for jn in rs.JOINTS:
                ax.axvspan(jn - JOINT_EXCL, jn + JOINT_EXCL, color="0.88", lw=0)
            ax.set_title(f"{CFG_NAME[cfg]} — {kr} 레일 [{layout}]   6회 평균 대비 RMSE {rmse_mean:.3f} mm, 1회 평균 {np.mean(rmse_runs):.3f} mm", fontsize=10)
            ax.grid(alpha=.35); ax.legend(fontsize=8, loc="lower left")
            ax.set_ylim(np.nanpercentile(A, 0.5) - 0.3, np.nanpercentile(A, 99.5) + 0.5)
            # 그림: 변화 신호 vs 설계 파형
            axx = axc[i, j]
            axx.plot(GRID, change, color=c, lw=1.6, label=f"실측 변화 = 6회 평균 − 정상 기준선 ({kr})")
            axx.fill_between(GRID, change - std, change + std, color=c, alpha=0.15, lw=0)
            axx.plot(GRID, v_design, "k--", lw=1.3, label="설계 2 mm 결함의 모델 파형")
            if np.isfinite(size_est):
                axx.plot(GRID, a * v_design, color="tab:green", lw=1.1, ls="-.", label=f"배율 맞춤 → 결함 크기 {size_est:.2f} mm")
            if np.isfinite(step_est):
                axx.plot(GRID, step_est * v_step, color="tab:purple", lw=1.1, ls="-.", label=f"1200 단차 맞춤 → {step_est:.2f} mm")
            for jn in rs.JOINTS:
                axx.axvspan(jn - JOINT_EXCL, jn + JOINT_EXCL, color="0.88", lw=0)
            axx.axhline(0, color="0.6", lw=0.6)
            axx.set_title(f"{CFG_NAME[cfg]} — {kr} 레일 [{layout}]", fontsize=10)
            axx.grid(alpha=.35); axx.legend(fontsize=8, loc="lower left")
            axx.set_ylim(-1.8, 1.8)
    for ax in axes[-1]: ax.set_xlabel("레일 위치 x mm")
    for ax in axc[-1]: ax.set_xlabel("레일 위치 x mm")
    for ax in axes[:, 0]: ax.set_ylabel("센서-레일 거리 mm")
    for ax in axc[:, 0]: ax.set_ylabel("기준선 대비 변화 mm")
    fig.suptitle("가상 모델 검증 — 정상 6회로 만든 모델이 결함 구성 18회를 얼마나 맞추나", fontsize=13)
    figc.suptitle("변화 신호와 설계 파형 — 결함 크기 추정 (논문 그림 3과 같은 비교)", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.97)); figc.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig("validate24.png", dpi=110); figc.savefig("validate24_change.png", dpi=110)

    # 기준선 그림
    fb, axb = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    for s, key, kr, c in SIDES:
        A = stack(runs, 1, s)
        for k in range(A.shape[0]):
            axb[0].plot(GRID, A[k], color=c, lw=0.5, alpha=0.4)
        axb[0].plot(GRID, base[s], color=c, lw=1.8, label=f"정상 6회 평균 ({kr})")
        axb[0].axhline(H[s], color=c, lw=0.8, ls="--", label=f"설치 높이 H {kr} = {H[s]:.2f} mm (평평한 레일 모델)")
        axb[1].plot(GRID, rshape[s], color=c, lw=1.5, label=f"레일 본래의 굴곡 r(x) {kr} = 기준선 − H")
    for jn in rs.JOINTS:
        for ax in axb: ax.axvspan(jn - JOINT_EXCL, jn + JOINT_EXCL, color="0.88", lw=0)
    axb[1].axhline(0, color="0.6", lw=0.6)
    axb[0].set_title("정상 구성 6회 — 기준선과 평평한 레일 모델"); axb[1].set_title("모델에 더해 줄 레일 본래의 굴곡 (파이프 휨 + 센서 장착 차이)")
    for ax in axb: ax.grid(alpha=.35); ax.legend(fontsize=9)
    axb[1].set_xlabel("레일 위치 x mm"); axb[0].set_ylabel("센서-레일 거리 mm"); axb[1].set_ylabel("mm")
    fb.tight_layout(); fb.savefig("baseline.png", dpi=110)

    df = pd.DataFrame(results)
    df.to_csv("validate24_results.csv", index=False, encoding="utf-8-sig")
    for r in results:
        line = (f"[{r['cfg']} {r['side']}] 배치 {r['layout']} | 6회 평균 대비 RMSE {r['rmse_6avg']:.3f} mm | "
                f"1회 대비 RMSE 평균 {r['rmse_1run_mean']:.3f} (최대 {r['rmse_1run_max']:.3f}) mm")
        if np.isfinite(r["size_est_mm"]):
            line += f" | 결함 크기 추정 {r['size_est_mm']:.2f} mm (정답 2)"
        if np.isfinite(r.get("size_peak_mm", np.nan)):
            line += f" | 봉우리 높이로 본 크기 {r['size_peak_mm']:.2f} mm"
        if np.isfinite(r["step1200_est_mm"]):
            line += f" | 1200 단차 추정 {r['step1200_est_mm']:.2f} mm"
        report.append(line)
    # 잡음 은행 저장
    # 잡음 은행: 이음부 틈 구간의 잔차는 스파이크 잔재이므로 양옆을 직선으로 이어 채운다
    nb = {}
    for s in ["left", "right"]:
        B = noise_bank[s].copy()
        B[:, jm] = np.nan
        for k in range(B.shape[0]):
            ok = np.isfinite(B[k])
            B[k] = np.interp(GRID, GRID[ok], B[k][ok]) if ok.sum() > 10 else 0.0
        nb[s] = B.tolist()
    out["rshape_left"] = np.nan_to_num(rshape["left"]).tolist(); out["rshape_right"] = np.nan_to_num(rshape["right"]).tolist()
    out["noise_bank"] = nb
    with open("calibration.json", "w") as fp:
        json.dump(out, fp)
    print("\n".join(report))


if __name__ == "__main__":
    main()
