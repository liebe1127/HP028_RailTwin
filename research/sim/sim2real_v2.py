"""1단계: 가상 v2(배치별 다시 놓임, 실측 범위 잡음)로만 학습 → 실측 18회(정상·단차·처짐) 평가.

세 가지를 같이 돌린다.
  A. 규칙만 (학습 없음): 복원한 레일 끝 높이에서 단차·침하 크기를 바로 읽고 논문 규칙으로 판별·판정
  B. 크기 회귀 → 규칙: 가상으로 단차 크기·침하 크기를 회귀 학습, 예측 크기에 논문 규칙 적용 (주 방법)
  C. 종류 분류기 (참고): 0.5 mm 아래 성분은 '없음'으로 바꾼 정답으로 RandomForest 학습
"""
import glob, os
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestClassifier
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

import railsim as rs
import sim2real as sr
import generate_dataset as gd

for f in font_manager.findSystemFonts():
    if "NotoSansCJK" in f and "Regular" in f:
        font_manager.fontManager.addfont(f)
plt.rcParams["font.family"] = "Noto Sans CJK KR"; plt.rcParams["axes.unicode_minus"] = False

GRID = sr.GRID; JM = sr.JM
LIMIT = gd.LIMIT
KR = {"normal": "정상", "HF": "이음부 단차", "C": "수직 방향 변형", "HF+C": "단차+처짐"}
ST = {"normal": "정상", "caution": "주의", "danger": "위험"}


def local_features(gL, gR):
    """이음부 주변만 보는 국소 특징 — 완만한 다시 놓임 변형에 덜 흔들린다."""
    out = {}
    sig = {"L": np.where(np.isfinite(gL), gL, 0.0), "R": np.where(np.isfinite(gR), gR, 0.0)}
    for s, g in sig.items():
        g = np.where(JM, np.nan, g)
        for j in rs.JOINTS:
            before = (GRID > j - 230) & (GRID < j - 60); after = (GRID > j + 60) & (GRID < j + 230)
            inner = (np.abs(GRID - j) < 100); flats = ((GRID > j - 350) & (GRID < j - 260)) | ((GRID > j + 260) & (GRID < j + 350))
            out[f"{s}_steploc{j:.0f}"] = float(np.nanmean(g[before]) - np.nanmean(g[after]))
            out[f"{s}_kink{j:.0f}"] = float(np.nanmean(g[inner]) - np.nanmean(g[flats]))
    for j in rs.JOINTS:
        for n in (f"steploc{j:.0f}", f"kink{j:.0f}"):
            out[f"m_{n}"] = (out[f"L_{n}"] + out[f"R_{n}"]) / 2; out[f"d_{n}"] = out[f"L_{n}"] - out[f"R_{n}"]
    return out


def feats(gL, gR):
    f = sr.features(gL, gR); f.update(local_features(gL, gR)); return f


def load_synth(path):
    man = pd.read_csv(os.path.join(path, "manifest.csv"))
    rows = []
    for r in man.itertuples():
        d = pd.read_csv(os.path.join(path, "runs", r.file), usecols=["rail_x_mm", "left_sensor_distance_mm", "right_sensor_distance_mm"])
        x = d.rail_x_mm.to_numpy()
        gL = sr.to_grid(x, d.left_sensor_distance_mm.to_numpy()) - sr.BASE["left"]
        gR = sr.to_grid(x, d.right_sensor_distance_mm.to_numpy()) - sr.BASE["right"]
        rows.append(feats(gL, gR))
    return pd.DataFrame(rows), man


def load_real():
    rows, truth = [], []
    for f in sorted(glob.glob("../data/c[123]_r*.csv")):
        n = os.path.basename(f)[:-4]; cfg = int(n[1])
        d = pd.read_csv(f); w = (d.analysis_window == 1) & (d.sensor_valid == 1)
        x = d.rail_x_mm[w].to_numpy(float)
        gL = sr.to_grid(x, d.left_sensor_distance_mm[w].to_numpy(float)) - sr.BASE["left"]
        gR = sr.to_grid(x, d.right_sensor_distance_mm[w].to_numpy(float)) - sr.BASE["right"]
        rows.append(feats(gL, gR))
        truth.append(dict(run=n, sHF=2.0 if cfg == 2 else 0.0, sC=2.0 if cfg == 3 else 0.0,
                          kind={1: "normal", 2: "HF", 3: "C"}[cfg], stage={1: "normal", 2: "danger", 3: "danger"}[cfg]))
    return pd.DataFrame(rows), pd.DataFrame(truth)


def rule(sHF, sC):
    hf = sHF >= 0.5 * LIMIT["HF"]; c = sC >= 0.5 * LIMIT["C"]
    kind = "HF+C" if hf and c else ("HF" if hf else ("C" if c else "normal"))
    st = max([gd.stage_of("HF", sHF) if hf else "normal", gd.stage_of("C", sC) if c else "normal"], key=lambda v: gd.STAGE_RANK[v])
    return kind, st


def effective_kind(sHF, sC):
    return rule(sHF, sC)[0]


def evaluate(name, pred_HF, pred_C, truth, lines):
    kinds, stages = [], []
    for h, c in zip(pred_HF, pred_C):
        k, s = rule(h, c); kinds.append(k); stages.append(s)
    ok_k = np.array(kinds) == truth.kind.to_numpy(); ok_s = np.array(stages) == truth.stage.to_numpy()
    lines.append(f"\n== {name}: 종류 {ok_k.sum()}/18, 판정 단계 {ok_s.sum()}/18")
    df = pd.DataFrame(dict(run=truth.run, 정답=[KR[k] for k in truth.kind], 예측=[KR[k] for k in kinds],
                           단차_mm=np.round(pred_HF, 2), 처짐_mm=np.round(pred_C, 2),
                           판정=[ST[s] for s in stages], 정답판정=[ST[s] for s in truth.stage]))
    df["종류"] = np.where(ok_k, "O", "X"); df["단계"] = np.where(ok_s, "O", "X")
    lines.append(df.to_string(index=False))
    for k, col in [("HF", "단차_mm"), ("C", "처짐_mm")]:
        m = truth.kind == k
        lines.append(f"   {KR[k]} 회차의 {col} 추정: 평균 {df.loc[m, col].mean():.2f} ± {df.loc[m, col].std(ddof=1):.2f} (정답 2.0)")
    m = truth.kind == "normal"
    lines.append(f"   정상 회차의 추정: 단차 {df.loc[m, '단차_mm'].abs().max():.2f} 이하, 처짐 {df.loc[m, '처짐_mm'].max():.2f} 이하")
    return df


def main():
    Xs, man = load_synth("../dataset_v2")
    Xr, truth = load_real(); cols = list(Xs.columns); Xr = Xr[cols]
    lines = [f"가상 v2 학습 {len(Xs)}회 (배치 {man.placement_id.nunique()}개), 실측 평가 18회"]

    # A. 규칙만
    sHF_rule = np.maximum(np.abs(Xr["m_steploc600"]), np.abs(Xr["m_steploc1200"])).to_numpy()
    sC_rule = (np.maximum(Xr["m_kink600"], Xr["m_kink1200"]) / 0.333).clip(lower=0).to_numpy()
    evaluate("A. 규칙만 (국소 특징, 학습 없음)", sHF_rule, sC_rule, truth, lines)
    sHF_rule_g = np.maximum(np.abs(Xr["m_step600"]), np.abs(Xr["m_step1200"])).to_numpy()
    sC_rule_g = np.maximum(Xr["m_settle600"], Xr["m_settle1200"]).clip(lower=0).to_numpy()
    evaluate("A'. 규칙만 (전구간 복원 높이)", sHF_rule_g, sC_rule_g, truth, lines)

    # B. 크기 회귀 → 규칙
    regHF = GradientBoostingRegressor(random_state=0, n_estimators=300, max_depth=3).fit(Xs, man.size_HF_mm)
    regC = GradientBoostingRegressor(random_state=0, n_estimators=300, max_depth=3).fit(Xs, man.size_C_mm)
    pHF = np.clip(regHF.predict(Xr), 0, None); pC = np.clip(regC.predict(Xr), 0, None)
    dfB = evaluate("B. 가상 학습 크기 회귀 → 규칙 (주 방법)", pHF, pC, truth, lines)

    # C. 종류 분류기 (참고)
    y_eff = np.array([effective_kind(h, c) for h, c in zip(man.size_HF_mm, man.size_C_mm)])
    clf = RandomForestClassifier(n_estimators=500, random_state=0, min_samples_leaf=2).fit(Xs, y_eff)
    pk = clf.predict(Xr); okc = (pk == truth.kind.to_numpy()).sum()
    lines.append(f"\n== C. 종류 분류기 (참고): {okc}/18  예측 = {[KR[k] for k in pk]}")

    # 가상 안 참고 정확도 (배치 단위로 나눠서)
    pids = man.placement_id.to_numpy(); va = pids % 5 == 0
    rh = GradientBoostingRegressor(random_state=0, n_estimators=300, max_depth=3).fit(Xs[~va], man.size_HF_mm[~va])
    rc = GradientBoostingRegressor(random_state=0, n_estimators=300, max_depth=3).fit(Xs[~va], man.size_C_mm[~va])
    ph = np.clip(rh.predict(Xs[va]), 0, None); pc = np.clip(rc.predict(Xs[va]), 0, None)
    st_true = man.stage[va].to_numpy(); st_pred = np.array([rule(h, c)[1] for h, c in zip(ph, pc)])
    lines.append(f"\n가상 검증(참고, 배치 {va.sum()//3}개): 단차 크기 오차 RMS {np.sqrt(np.mean((ph-man.size_HF_mm[va])**2)):.2f} mm, "
                 f"처짐 크기 오차 RMS {np.sqrt(np.mean((pc-man.size_C_mm[va])**2)):.2f} mm, 판정 단계 정확도 {np.mean(st_pred==st_true)*100:.1f} %")
    txt = "\n".join(lines); print(txt); open("sim2real_v2_result.txt", "w").write(txt)
    dfB.to_csv("sim2real_v2_result.csv", index=False, encoding="utf-8-sig")

    # 그림: 실측 18회의 예측 크기
    fig, ax = plt.subplots(figsize=(10, 4.5))
    xpos = np.arange(18)
    ax.bar(xpos - 0.2, dfB["단차_mm"], 0.4, label="예측 단차 크기", color="tab:orange")
    ax.bar(xpos + 0.2, dfB["처짐_mm"], 0.4, label="예측 처짐 크기", color="tab:green")
    ax.axhline(2.0, color="k", ls="--", lw=0.8, label="정답 2 mm (단차·처짐 회차)")
    ax.axhline(1.0, color="tab:red", ls=":", lw=0.8, label="허용 한계 1.0 (위험)"); ax.axhline(0.5, color="tab:olive", ls=":", lw=0.8, label="주의 0.5")
    ax.set_xticks(xpos); ax.set_xticklabels(dfB.run, rotation=60, fontsize=8); ax.set_ylabel("mm"); ax.grid(alpha=.3, axis="y")
    ax.set_title("가상 v2 로만 학습한 크기 회귀 — 실측 18회 (정상 6 / 단차 6 / 처짐 6)"); ax.legend(fontsize=8, ncol=3)
    fig.tight_layout(); fig.savefig("sim2real_v2.png", dpi=110)


if __name__ == "__main__":
    main()
