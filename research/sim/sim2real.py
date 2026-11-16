"""가상 → 실물 검증: 가상 2,000회로만 학습한 판별기가 실측 24회를 몇 회 맞추나.

판별기는 단순하게 둔다.
  특징 = (기준선을 뺀 변화 신호를) 결함 모양 파형에 최소제곱으로 맞춘 계수 + 구간 평균 + 몇 가지 통계
  분류기 = RandomForest (종류 4가지: normal / HF / C / E), 회귀기 = GradientBoosting (결함 크기 mm)
학습: 가상 중 단일 결함 회차 1,600회 (겹침 400회는 학습·평가에서 제외)
평가: 실측 24회 (정상 6, 이음부 단차 6, 수직 방향 변형 6, 좌우 높이차 6). 가상 데이터는 평가에 쓰지 않는다.
"""
import glob, json, os
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingRegressor
from sklearn.model_selection import train_test_split
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
BASE = {s: np.array(CAL[f"baseline_{s}"]) for s in ["left", "right"]}
JOINT_EXCL = 20.0
JM = np.zeros_like(GRID, dtype=bool)
for j in rs.JOINTS:
    JM |= np.abs(GRID - j) < JOINT_EXCL
LIMIT = {"HF": 1.0, "C": 1.0, "E": 5.0}
KR = {"normal": "정상", "HF": "이음부 단차", "C": "수직 방향 변형", "E": "좌우 높이차"}


def templates():
    """레일 끝 높이 4개를 단위로 올렸을 때의 현측정 파형. 양 끝(0 mm, 1800 mm)은 0 으로 고정(기준).
    h600m: 1번 파이프 오른쪽 끝, h600p: 2번 파이프 왼쪽 끝, h1200m: 2번 파이프 오른쪽 끝, h1200p: 3번 파이프 왼쪽 끝.
    현측정은 전체 기울기·높이에 둔감하므로 이 4개가 서로 독립인 전부다(최소제곱이 유일하게 풀린다)."""
    T = {}
    for name, (k, e) in {"h600m": (0, 1), "h600p": (1, 0), "h1200m": (1, 1), "h1200p": (2, 0)}.items():
        p = [[21.0, 21.0] for _ in range(3)]
        p[k][e] += 1.0
        T[name] = rs.versine_of_profile(GRID, p)
    M = np.column_stack([T[k] for k in T])
    return list(T.keys()), M


TNAMES, TM = templates()


def to_grid(x, g):
    o = np.argsort(x, kind="stable")
    ux, inv = np.unique(np.round(x[o], 1), return_inverse=True)
    ug = np.bincount(inv, weights=g[o]) / np.bincount(inv)
    gi = np.interp(GRID, ux, ug, left=np.nan, right=np.nan)
    gi[(GRID < ux.min()) | (GRID > ux.max())] = np.nan
    return gi


def features(gL, gR):
    """gL, gR: 기준선을 뺀 좌·우 변화 신호 (GRID 위). NaN 은 0 으로."""
    feats = {}
    chg = {}
    for s, g in [("L", gL), ("R", gR)]:
        g = np.where(np.isfinite(g), g, 0.0); g = np.where(JM, 0.0, g)
        chg[s] = g
        ok = ~JM & np.isfinite(g)
        coef, *_ = np.linalg.lstsq(TM[ok], g[ok], rcond=None)
        for n, c in zip(TNAMES, coef):
            feats[f"{s}_{n}"] = c
        resid = g[ok] - TM[ok] @ coef
        feats[f"{s}_resid_rms"] = float(np.sqrt(np.mean(resid ** 2)))
        feats[f"{s}_std"] = float(np.std(g[ok])); feats[f"{s}_absmax"] = float(np.max(np.abs(g[ok])))
    m = (chg["L"] + chg["R"]) / 2; d = chg["L"] - chg["R"]
    for name, sig in [("m", m), ("d", d)]:
        for k in range(12):
            seg = (GRID >= 300 + 100 * k) & (GRID < 400 + 100 * k) & ~JM
            feats[f"{name}_seg{k}"] = float(np.mean(sig[seg]))
        feats[f"{name}_std"] = float(np.std(sig[~JM])); feats[f"{name}_absmax"] = float(np.max(np.abs(sig[~JM])))
    # 복원한 레일 끝 높이에서 결함 성분을 만든다
    for s in ("L", "R"):
        feats[f"{s}_step600"] = feats[f"{s}_h600p"] - feats[f"{s}_h600m"]
        feats[f"{s}_step1200"] = feats[f"{s}_h1200p"] - feats[f"{s}_h1200m"]
        feats[f"{s}_settle600"] = -(feats[f"{s}_h600p"] + feats[f"{s}_h600m"]) / 2
        feats[f"{s}_settle1200"] = -(feats[f"{s}_h1200p"] + feats[f"{s}_h1200m"]) / 2
        feats[f"{s}_pipe2"] = (feats[f"{s}_h600p"] + feats[f"{s}_h1200m"]) / 2
    for n in TNAMES + ["step600", "step1200", "settle600", "settle1200", "pipe2"]:
        feats[f"m_{n}"] = (feats[f"L_{n}"] + feats[f"R_{n}"]) / 2
        feats[f"d_{n}"] = feats[f"L_{n}"] - feats[f"R_{n}"]
    return feats


def load_synth(path="../dataset"):
    man = pd.read_csv(os.path.join(path, "manifest.csv"))
    man = man[man.scenario != "mixed"].reset_index(drop=True)
    rows, y, size = [], [], []
    for r in man.itertuples():
        d = pd.read_csv(os.path.join(path, "runs", r.file), usecols=["rail_x_mm", "left_sensor_distance_mm", "right_sensor_distance_mm"])
        x = d.rail_x_mm.to_numpy()
        gL = to_grid(x, d.left_sensor_distance_mm.to_numpy()) - BASE["left"]
        gR = to_grid(x, d.right_sensor_distance_mm.to_numpy()) - BASE["right"]
        rows.append(features(gL, gR)); y.append(r.scenario); size.append(r.size1_mm)
    return pd.DataFrame(rows), np.array(y), np.array(size), man


def load_real(path="../data"):
    rows, y, names = [], [], []
    lab = {1: "normal", 2: "HF", 3: "C", 4: "E"}
    for f in sorted(glob.glob(os.path.join(path, "c*_r*.csv"))):
        n = os.path.basename(f)[:-4]; cfg = int(n[1])
        d = pd.read_csv(f)
        w = (d.analysis_window == 1) & (d.sensor_valid == 1)
        x = d.rail_x_mm[w].to_numpy(float)
        gL = to_grid(x, d.left_sensor_distance_mm[w].to_numpy(float)) - BASE["left"]
        gR = to_grid(x, d.right_sensor_distance_mm[w].to_numpy(float)) - BASE["right"]
        # 센서 이상(1.2 mm 오프셋) 구간은 실측에서 그대로 둔다 — 실물 조건 그대로 평가
        rows.append(features(gL, gR)); y.append(lab[cfg]); names.append(n)
    return pd.DataFrame(rows), np.array(y), names


def stage_of(kind, size):
    if kind == "normal":
        return "정상"
    lim = LIMIT[kind]
    return "정상" if size < 0.5 * lim else ("주의" if size <= lim else "위험")


def main():
    Xs, ys, ss, man = load_synth()
    Xr, yr, names = load_real()
    cols = list(Xs.columns); Xr = Xr[cols]
    # 가상 안에서의 참고용 정확도 (학습 8 : 검증 2)
    Xtr, Xva, ytr, yva, str_, sva = train_test_split(Xs, ys, ss, test_size=0.2, random_state=0, stratify=ys)
    clf = RandomForestClassifier(n_estimators=500, random_state=0, min_samples_leaf=2).fit(Xtr, ytr)
    acc_va = float(np.mean(clf.predict(Xva) == yva))
    # 본 모델: 가상 1,600회 전부로 학습
    clf = RandomForestClassifier(n_estimators=500, random_state=0, min_samples_leaf=2).fit(Xs, ys)
    reg = {}
    for k in ["HF", "C", "E"]:
        m = ys == k
        reg[k] = GradientBoostingRegressor(random_state=0).fit(Xs[m], ss[m])
    pred = clf.predict(Xr); proba = clf.predict_proba(Xr)
    acc = float(np.mean(pred == yr))
    lines = [f"가상 검증 정확도(참고, 가상 320회): {acc_va*100:.1f} %",
             f"실측 24회 정확도: {int((pred == yr).sum())}/24 = {acc*100:.1f} %", ""]
    rows = []
    for i, n in enumerate(names):
        k = pred[i]
        size = float(reg[k].predict(Xr.iloc[[i]])[0]) if k != "normal" else 0.0
        st = stage_of(k, size)
        p = proba[i][list(clf.classes_).index(k)]
        rows.append(dict(run=n, 정답=KR[yr[i]], 예측=KR[k], 맞음="O" if k == yr[i] else "X", 확신=round(p, 2),
                         크기_mm=round(size, 2), 판정=st))
    df = pd.DataFrame(rows)
    lines.append(df.to_string(index=False))
    cm = pd.crosstab(pd.Series([KR[v] for v in yr], name="정답"), pd.Series([KR[v] for v in pred], name="예측"))
    lines += ["", "혼동 행렬:", cm.to_string(), ""]
    for k in ["HF", "C", "E"]:
        m = (yr == k) & (pred == k)
        if m.any():
            sz = df.loc[m, "크기_mm"]
            lines.append(f"{KR[k]} 크기 추정 (정답 2 mm, 맞춘 회차만): 평균 {sz.mean():.2f} ± {sz.std(ddof=1) if len(sz)>1 else 0:.2f} mm")
    imp = pd.Series(clf.feature_importances_, index=cols).sort_values(ascending=False).head(10)
    lines += ["", "판별에 많이 쓴 특징 10개:", imp.round(3).to_string()]
    txt = "\n".join(lines)
    print(txt)
    open("sim2real_result.txt", "w").write(txt)
    df.to_csv("sim2real_result.csv", index=False, encoding="utf-8-sig")
    # 그림: 실측 24회를 가상 학습 특징 공간에서 — 주요 계수 2개 산점도
    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    colors = {"normal": "0.4", "HF": "tab:orange", "C": "tab:green", "E": "tab:purple"}
    for k in ["normal", "HF", "C", "E"]:
        m = ys == k
        ax[0].scatter(np.abs(Xs.loc[m, "m_step600"]) + np.abs(Xs.loc[m, "m_step1200"]), Xs.loc[m, "d_settle600"] + Xs.loc[m, "d_settle1200"], s=6, alpha=.35, color=colors[k], label=f"가상 {KR[k]}")
        mr = yr == k
        ax[0].scatter(np.abs(Xr.loc[mr, "m_step600"]) + np.abs(Xr.loc[mr, "m_step1200"]), Xr.loc[mr, "d_settle600"] + Xr.loc[mr, "d_settle1200"], s=60, marker="*", edgecolor="k", color=colors[k], label=f"실측 {KR[k]}", zorder=5)
    ax[0].set_xlabel("이음부 단차 크기 합 |600|+|1200| (좌우 평균, mm)"); ax[0].set_ylabel("받침 침하 (좌−우, mm)"); ax[0].grid(alpha=.3); ax[0].legend(fontsize=7, ncol=2)
    ax[0].set_title("가상 학습 데이터 위에 놓인 실측 24회 (별표)")
    for k in ["normal", "HF", "C", "E"]:
        m = ys == k
        ax[1].scatter(Xs.loc[m, "m_settle600"] + Xs.loc[m, "m_settle1200"], Xs.loc[m, "L_resid_rms"], s=6, alpha=.35, color=colors[k])
        mr = yr == k
        ax[1].scatter(Xr.loc[mr, "m_settle600"] + Xr.loc[mr, "m_settle1200"], Xr.loc[mr, "L_resid_rms"], s=60, marker="*", edgecolor="k", color=colors[k], zorder=5)
    ax[1].set_xlabel("받침 침하 합 (좌우 평균, mm)"); ax[1].set_ylabel("좌 잔차 RMS (mm)"); ax[1].grid(alpha=.3)
    ax[1].set_title("수직 방향 변형 축 — 실측이 가상 분포 안에 있는지")
    fig.suptitle(f"가상 2,000회로만 학습한 판별기의 실측 24회 결과: {int((pred == yr).sum())}/24", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.95)); fig.savefig("sim2real.png", dpi=110)


if __name__ == "__main__":
    main()
