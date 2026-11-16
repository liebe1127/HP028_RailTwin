"""다시 놓임 크기만 바꿔 가며 서버 오경보율·판정 정답률이 어떻게 변하는지 본다 (원인 확인용)."""
import os, sys, subprocess, numpy as np, pandas as pd
import generate_dataset_v2 as g2
import replay_virtual as rv
sys.path.insert(0, "../server"); import rail_defect
rows=[]
for lo,hi in [(0.0,0.0),(0.03,0.06),(0.08,0.12),(0.15,0.25)]:
    out=f"../sweep_{lo}_{hi}"
    g2.PERT_RMS=(lo,hi) if hi>0 else (1e-9,2e-9)
    sys.argv=["x","--placements","120","--runs","3","--seed","5","--out",out]
    g2.main()
    man=pd.read_csv(f"{out}/manifest.csv")
    os.environ["RAIL_BASELINE_FILE"]=f"../server/sweep_baseline.json"
    if os.path.exists(os.environ["RAIL_BASELINE_FILE"]): os.remove(os.environ["RAIL_BASELINE_FILE"])
    eng=rail_defect.DefectRuleEngine(segment_count=20, rail_length_cm=180.0); eng.baseline_mode=True
    for pid in man[man.scenario=="normal"].placement_id.unique()[:6]:
        rv.feed(eng, f"{out}/runs/"+man[(man.placement_id==pid)&(man.rep==1)].file.iloc[0])
    eng.baseline_mode=False
    rec=[]
    for pid,g in man.groupby("placement_id"):
        eng.pass_analyzer.history.clear(); eng.pass_result=None
        for r in g.sort_values("rep").itertuples():
            res,_=rv.feed(eng, f"{out}/runs/{r.file}")
            rec.append(dict(scenario=r.scenario,rep=r.rep,true_stage=r.stage,tHF=r.size_HF_mm,tC=r.size_C_mm,
                            srv=res["defect_type"] if res else "none", st={"ok":"normal"}.get(res["stage"],res["stage"]) if res else "none", E=res["sizes_mm"]["cross_level"] if res else np.nan))
    d=pd.DataFrame(rec); mn=d[d.scenario=="normal"]; d3=d[d.rep==3]
    big=d3[(d3.scenario.isin(["HF","C"]))&((d3.tHF>1.0)|(d3.tC>1.0))]
    rows.append(dict(다시놓임RMS=f"{lo}~{hi}", 정상오경보_1회=f"{(mn.srv!='normal').mean()*100:.0f}%", 정상_3회째_주의이상=f"{(d3[d3.scenario=='normal'].st!='normal').mean()*100:.0f}%",
                     정상회차_E크기중앙값=f"{mn.E.abs().median():.2f}", 위험결함_3회째_위험판정=f"{(big.st=='danger').mean()*100:.0f}% (n={len(big)})"))
    print(rows[-1], flush=True)
t=pd.DataFrame(rows); print(t.to_string(index=False)); t.to_csv("replay_pert_sweep.csv",index=False,encoding="utf-8-sig")
