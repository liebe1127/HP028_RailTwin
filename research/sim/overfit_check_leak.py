"""과적합 검사 2: 잡음 은행·기준선을 정상 3회(31~33)로만 만들고, 나머지 정상 3회(34~36)를 '본 적 없는' 실측으로 평가.
가상 학습 데이터가 실측 정상 회차의 잔차를 재사용하므로 생기는 누수(leakage)가 결과를 부풀렸는지 본다."""
import os, sys, json, glob, numpy as np, pandas as pd
import analyze24 as a24, railsim as rs
from sklearn.ensemble import GradientBoostingRegressor

# 1) 정상 31~33 만으로 교정값 만들기
runs = a24.load_all(); GRID = a24.GRID; jm = a24.joint_mask(GRID); use = ~jm
sub = {k: v for k, v in runs.items() if v["cfg"] == 1 and v["run"] in (31, 32, 33)}
cal = {"grid_mm": GRID.tolist()}
for s in ["left", "right"]:
    A = np.array([r[s] for r in sub.values()]).copy()
    med = np.nanmedian(A, axis=0); A[np.abs(A - med) > 0.8] = np.nan
    mean = np.nanmean(A, axis=0); H = float(np.nanmean(mean[use]))
    dev = A - mean; dev[:, jm] = np.nan
    for k in range(dev.shape[0]):
        ok = np.isfinite(dev[k]); dev[k] = np.interp(GRID, GRID[ok], dev[k][ok])
    cal[f"baseline_{s}"] = np.nan_to_num(mean).tolist(); cal[f"H_{s}"] = H
    cal[f"rshape_{s}"] = np.nan_to_num(mean - H).tolist(); cal.setdefault("noise_bank", {})[s] = dev.tolist()
json.dump(cal, open("calibration_sub.json", "w"))

# 2) 그 교정값으로 가상 v2 데이터 생성 (monkeypatch)
import generate_dataset as gd, generate_dataset_v2 as g2
gd.CAL = cal
sys.argv = ["x", "--placements", "300", "--runs", "3", "--seed", "21", "--out", "../dataset_v2_sub"]
g2.main()

# 3) 특징·학습·평가 (기준선도 subset 것으로)
import sim2real as sr, sim2real_v2 as v2
sr.CAL = cal; sr.BASE = {s: np.array(cal[f"baseline_{s}"]) for s in ["left", "right"]}
Xs, man = v2.load_synth("../dataset_v2_sub")
Xr, truth = v2.load_real(); cols = list(Xs.columns); Xr = Xr[cols]
rh = GradientBoostingRegressor(random_state=0, n_estimators=300, max_depth=3).fit(Xs, man.size_HF_mm)
rc_ = GradientBoostingRegressor(random_state=0, n_estimators=300, max_depth=3).fit(Xs, man.size_C_mm)
pH = np.clip(rh.predict(Xr), 0, None); pC = np.clip(rc_.predict(Xr), 0, None)
kinds = [v2.rule(h, c) for h, c in zip(pH, pC)]
out = pd.DataFrame(dict(run=truth.run, 정답=truth.kind, 예측=[k for k, _ in kinds], 단계=[s for _, s in kinds], 정답단계=truth.stage, 단차=np.round(pH, 2), 처짐=np.round(pC, 2)))
out["잡음은행"] = out.run.apply(lambda n: "포함(31~33)" if n in ("c1_r31", "c1_r32", "c1_r33") else ("제외(34~36)" if n.startswith("c1") else "결함 회차"))
lines = ["== 잡음 은행을 정상 31~33 으로만 만든 경우 — 회귀 B 실측 18회"]
for grp, g in out.groupby("잡음은행"):
    lines.append(f"  {grp}: 종류 {int((g.예측==g.정답).sum())}/{len(g)}, 단계 {int((g.단계==g.정답단계).sum())}/{len(g)}")
lines.append(out.to_string(index=False))
# 규칙 A (학습 없음, 기준선만 subset)
sHF = np.maximum(np.abs(Xr["m_steploc600"]), np.abs(Xr["m_steploc1200"])).to_numpy(); sC = (np.maximum(Xr["m_kink600"], Xr["m_kink1200"]) / 0.333).clip(lower=0).to_numpy()
ka = [v2.rule(h, c) for h, c in zip(sHF, sC)]
oa = pd.DataFrame(dict(run=truth.run, 정답=truth.kind, 예측=[k for k, _ in ka], 단계=[s for _, s in ka], 정답단계=truth.stage))
oa["잡음은행"] = out["잡음은행"]
lines.append("\n== 규칙 A (기준선만 31~33) 실측 18회")
for grp, g in oa.groupby("잡음은행"):
    lines.append(f"  {grp}: 종류 {int((g.예측==g.정답).sum())}/{len(g)}, 단계 {int((g.단계==g.정답단계).sum())}/{len(g)}")
txt = "\n".join(lines); print(txt); open("overfit_check_leak.txt", "w").write(txt)
