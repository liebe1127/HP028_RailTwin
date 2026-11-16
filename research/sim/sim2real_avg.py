"""가상 → 실물 검증, 두 번째 규칙: 같은 구간을 3회 이상 지난 평균으로 판정 (논문 2.3).

가상 학습: 시나리오 1,600개를 새로 뽑아(생성기 함수 재사용) 각 시나리오마다 레일 모양·다시 놓임은 같고
          잡음·엔코더만 다른 주행 3회를 만들어 평균 → 특징
실측 평가: 구성마다 6회를 3회씩 두 묶음으로 평균(8건), 그리고 6회 평균(4건)
"""
import glob, os, json
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingRegressor

import railsim as rs
import generate_dataset as gd
import sim2real as sr

KR = sr.KR


def synth_avg_features(n_scen=1600, k=3, seed=11):
    rng = np.random.default_rng(seed)
    kinds = ["normal", "HF", "C", "E"]
    nb = {s: np.array(gd.CAL["noise_bank"][s]) for s in ["left", "right"]}
    rsh = {s: np.array(gd.CAL[f"rshape_{s}"]) for s in ["left", "right"]}
    H = {s: gd.CAL[f"H_{s}"] for s in ["left", "right"]}
    rows, ys, ss = [], [], []
    for i in range(n_scen):
        kind = kinds[i % 4]
        pipes, defects = gd.make_scenario(rng, kind)
        pert_rms = float(rng.uniform(0.10, 0.35))
        pert = {s: gd.rail_perturbation(rng, pert_rms) for s in ["left", "right"]}
        speed = float(rng.uniform(30, 100))
        acc = {"left": np.zeros_like(sr.GRID), "right": np.zeros_like(sr.GRID)}
        for rep in range(k):
            x0 = float(rng.uniform(280, 320)); x1 = float(rng.uniform(1500, 1540))
            n = int((x1 - x0) / speed / gd.DT); x = x0 + speed * np.arange(n) * gd.DT
            for s in ["left", "right"]:
                meas, *_ = gd.side_signal(x, pipes[s], pert[s], H[s], rsh[s], nb[s], gd.SPIKE[s], rng)
                acc[s] = acc[s] + np.nan_to_num(sr.to_grid(x, meas) - sr.BASE[s])
        rows.append(sr.features(acc["left"] / k, acc["right"] / k)); ys.append(kind)
        ss.append(defects[0]["size"] if defects else 0.0)
    return pd.DataFrame(rows), np.array(ys), np.array(ss)


def real_avg_features(groups):
    """groups: [(label, [run names])]"""
    lab = {1: "normal", 2: "HF", 3: "C", 4: "E"}
    rows, ys, names = [], [], []
    for cfg, runs in groups:
        acc = {"left": [], "right": []}
        for n in runs:
            d = pd.read_csv(f"../data/{n}.csv")
            w = (d.analysis_window == 1) & (d.sensor_valid == 1)
            x = d.rail_x_mm[w].to_numpy(float)
            for s in ["left", "right"]:
                acc[s].append(sr.to_grid(x, d[f"{s}_sensor_distance_mm"][w].to_numpy(float)) - sr.BASE[s])
        gL = np.nanmean(np.array(acc["left"]), axis=0); gR = np.nanmean(np.array(acc["right"]), axis=0)
        rows.append(sr.features(gL, gR)); ys.append(lab[cfg]); names.append("+".join(r.split("_")[1] for r in runs))
    return pd.DataFrame(rows), np.array(ys), names


def main():
    Xs, ys, ss = synth_avg_features()
    cols = list(Xs.columns)
    clf = RandomForestClassifier(n_estimators=500, random_state=0, min_samples_leaf=2).fit(Xs, ys)
    reg = {k: GradientBoostingRegressor(random_state=0).fit(Xs[ys == k], ss[ys == k]) for k in ["HF", "C", "E"]}
    runs = {c: sorted(os.path.basename(f)[:-4] for f in glob.glob(f"../data/c{c}_r*.csv")) for c in [1, 2, 3, 4]}
    groups3 = [(c, runs[c][:3]) for c in [1, 2, 3, 4]] + [(c, runs[c][3:]) for c in [1, 2, 3, 4]]
    groups6 = [(c, runs[c]) for c in [1, 2, 3, 4]]
    out = []
    for title, groups in [("3회 평균 (8건)", groups3), ("6회 평균 (4건)", groups6)]:
        Xr, yr, names = real_avg_features(groups); Xr = Xr[cols]
        pred = clf.predict(Xr); proba = clf.predict_proba(Xr)
        out.append(f"\n== {title}: {int((pred == yr).sum())}/{len(yr)} 정답")
        for i, n in enumerate(names):
            k = pred[i]; size = float(reg[k].predict(Xr.iloc[[i]])[0]) if k != "normal" else 0.0
            p = proba[i][list(clf.classes_).index(k)]
            out.append(f"  {n:<24s} 정답 {KR[yr[i]]:<9s} 예측 {KR[k]:<9s} {'O' if k == yr[i] else 'X'}  확신 {p:.2f}  크기 {size:.2f} mm  판정 {sr.stage_of(k, size)}")
    txt = "\n".join(out); print(txt); open("sim2real_avg_result.txt", "w").write(txt)


if __name__ == "__main__":
    main()
