"""B 변형: 국소 특징만으로 크기 회귀 (완만한 다시 놓임 변형에 강한 특징만 쓴다)."""
import numpy as np, pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
import sim2real_v2 as v2, generate_dataset as gd

Xs, man = v2.load_synth("../dataset_v2")
Xr, truth = v2.load_real()
local_cols = [c for c in Xs.columns if ("steploc" in c or "kink" in c)]
sets = {"국소 특징만 (16개)": local_cols,
        "국소 + 신호 통계 (std, absmax)": local_cols + [c for c in Xs.columns if c.endswith("_std") or c.endswith("_absmax")],
        "전체 특징": list(Xs.columns)}
pids = man.placement_id.to_numpy(); va = pids % 5 == 0
lines = []
for name, cols in sets.items():
    rh = GradientBoostingRegressor(random_state=0, n_estimators=300, max_depth=3).fit(Xs.loc[~va, cols], man.size_HF_mm[~va])
    rc = GradientBoostingRegressor(random_state=0, n_estimators=300, max_depth=3).fit(Xs.loc[~va, cols], man.size_C_mm[~va])
    ph = np.clip(rh.predict(Xs.loc[va, cols]), 0, None); pc = np.clip(rc.predict(Xs.loc[va, cols]), 0, None)
    st_true = man.stage[va].to_numpy(); st_pred = np.array([v2.rule(h, c)[1] for h, c in zip(ph, pc)])
    k_true = np.array([v2.effective_kind(h, c) for h, c in zip(man.size_HF_mm[va], man.size_C_mm[va])])
    k_pred = np.array([v2.rule(h, c)[0] for h, c in zip(ph, pc)])
    lines.append(f"\n### {name} — 가상 검증(배치 120개): 단차 RMS {np.sqrt(np.mean((ph-man.size_HF_mm[va])**2)):.2f}, 처짐 RMS {np.sqrt(np.mean((pc-man.size_C_mm[va])**2)):.2f}, 종류 {np.mean(k_pred==k_true)*100:.1f} %, 단계 {np.mean(st_pred==st_true)*100:.1f} %")
    rh = GradientBoostingRegressor(random_state=0, n_estimators=300, max_depth=3).fit(Xs[cols], man.size_HF_mm)
    rc = GradientBoostingRegressor(random_state=0, n_estimators=300, max_depth=3).fit(Xs[cols], man.size_C_mm)
    pH = np.clip(rh.predict(Xr[cols]), 0, None); pC = np.clip(rc.predict(Xr[cols]), 0, None)
    v2.evaluate(f"실측 18회 — {name}", pH, pC, truth, lines)
txt="\n".join(lines); print(txt); open("sim2real_v2b_result.txt","w").write(txt)
