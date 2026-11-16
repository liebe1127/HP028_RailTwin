"""재검증 1: 한 번도 안 쓴 가상 주행(seed 31, 200배치×3회)에서 규칙 A 와 최종 AI(C3, numpy 모듈) 직접 비교."""
import numpy as np, pandas as pd
import ai_train as at, sim2real_v2 as v2, rail_ai
Xs, Fs, man = at.load_synth(["../dataset_recheck"])
ai = rail_ai.RailAI()
rH, rC = at.rule_sizes(Fs)
P = np.array([[ai.predict(x[0], x[1])[k] for k in ("joint_step", "vertical")] for x in Xs])
Y = np.stack([man.size_HF_mm, man.size_C_mm], 1)
L = [f"재검증 가상 {len(Xs)}회 (seed 31, 학습·검증 어디에도 없음)", "| 방법 | 종류 | 단계(1회) | 단차 RMSE | 처짐 RMSE | 정상 오경보 |", "|---|---|---|---|---|---|"]
for name, pH, pC in (("A 규칙", rH, rC), ("C3 AI (rail_ai)", P[:, 0], P[:, 1])):
    s = at.score(pH, pC, Y[:, 0], Y[:, 1], man.stage)
    nm = man.scenario == "normal"; fa = np.mean([v2.rule(h, c)[0] != "normal" for h, c in zip(pH[nm], pC[nm])])
    L.append(f"| {name} | {s['type_acc']*100:.0f} % | {s['stage_acc']*100:.0f} % | {s['rmse_HF']:.2f} | {s['rmse_C']:.2f} | {fa*100:.0f} % |")
# 3회 평균 단계
L.append("\n3회 평균 단계 정답 (배치 200개):")
for name, pH, pC in (("A 규칙", rH, rC), ("C3 AI", P[:, 0], P[:, 1])):
    ok = 0
    for pid, g in man.groupby("placement_id"):
        i = g.index.to_numpy(); k, st = v2.rule(pH[i].mean(), pC[i].mean()); ok += st == g.stage.iloc[0]
    L.append(f"  {name}: {ok}/{man.placement_id.nunique()}")
txt = "\n".join(L); print(txt); open("recheck_ai.md", "w").write(txt)
