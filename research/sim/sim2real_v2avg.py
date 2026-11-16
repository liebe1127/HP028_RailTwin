"""1단계 보조: 같은 배치 3회 평균으로 판정 (논문 2.3 규칙). 가상 v2 는 배치마다 3회가 있으니 그대로 평균."""
import glob, os, numpy as np, pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
import sim2real as sr, sim2real_v2 as v2, generate_dataset as gd

def synth_avg(path):
    man = pd.read_csv(os.path.join(path, "manifest.csv")); rows=[]; meta=[]
    for pid, g in man.groupby("placement_id"):
        acc={"left":[], "right":[]}
        for r in g.itertuples():
            d=pd.read_csv(os.path.join(path,"runs",r.file),usecols=["rail_x_mm","left_sensor_distance_mm","right_sensor_distance_mm"])
            x=d.rail_x_mm.to_numpy()
            for s in acc: acc[s].append(np.nan_to_num(sr.to_grid(x,d[f"{s}_sensor_distance_mm"].to_numpy())-sr.BASE[s]))
        rows.append(v2.feats(np.mean(acc["left"],0),np.mean(acc["right"],0)))
        meta.append(dict(pid=pid,sHF=g.size_HF_mm.iloc[0],sC=g.size_C_mm.iloc[0],stage=g.stage.iloc[0],kind=g.scenario.iloc[0]))
    return pd.DataFrame(rows), pd.DataFrame(meta)

def real_avg():
    rows=[];truth=[]
    for cfg in [1,2,3]:
        runs=sorted(glob.glob(f"../data/c{cfg}_r*.csv"))
        for grp in (runs[:3],runs[3:]):
            acc={"left":[], "right":[]}
            for f in grp:
                d=pd.read_csv(f); w=(d.analysis_window==1)&(d.sensor_valid==1); x=d.rail_x_mm[w].to_numpy(float)
                for s in acc: acc[s].append(sr.to_grid(x,d[f"{s}_sensor_distance_mm"][w].to_numpy(float))-sr.BASE[s])
            rows.append(v2.feats(np.nanmean(acc["left"],0),np.nanmean(acc["right"],0)))
            truth.append(dict(run="+".join(os.path.basename(f)[3:-4] for f in grp),sHF=2.0 if cfg==2 else 0.0,sC=2.0 if cfg==3 else 0.0,
                              kind={1:"normal",2:"HF",3:"C"}[cfg],stage={1:"normal",2:"danger",3:"danger"}[cfg]))
    return pd.DataFrame(rows), pd.DataFrame(truth)

Xs,meta=synth_avg("../dataset_v2"); Xr,truth=real_avg(); cols=list(Xs.columns); Xr=Xr[cols]
lines=[f"3회 평균 판정 — 가상 배치 {len(Xs)}개로 학습, 실측 6묶음(정상 2, 단차 2, 처짐 2) 평가"]
# 규칙 A
sHF=np.maximum(np.abs(Xr["m_steploc600"]),np.abs(Xr["m_steploc1200"])).to_numpy(); sC=(np.maximum(Xr["m_kink600"],Xr["m_kink1200"])/0.333).clip(lower=0).to_numpy()
# evaluate expects 18 rows in text; write a small one
def ev(name,pH,pC):
    ks=[v2.rule(h,c) for h,c in zip(pH,pC)]
    okk=sum(k==t for (k,_),t in zip(ks,truth.kind)); oks=sum(s==t for (_,s),t in zip(ks,truth.stage))
    lines.append(f"\n== {name}: 종류 {okk}/6, 단계 {oks}/6")
    for i,(k,s) in enumerate(ks):
        lines.append(f"  {truth.run[i]:<14s} 정답 {v2.KR[truth.kind[i]]:<9s} 예측 {v2.KR[k]:<9s} 단차 {pH[i]:.2f} 처짐 {pC[i]:.2f} 판정 {v2.ST[s]} (정답 {v2.ST[truth.stage[i]]})")
ev("규칙 A (국소)",sHF,sC)
sHFg=np.maximum(np.abs(Xr["m_step600"]),np.abs(Xr["m_step1200"])).to_numpy(); sCg=np.maximum(Xr["m_settle600"],Xr["m_settle1200"]).clip(lower=0).to_numpy()
ev("규칙 A' (전구간 복원)",sHFg,sCg)
rh=GradientBoostingRegressor(random_state=0,n_estimators=300,max_depth=3).fit(Xs,meta.sHF); rc=GradientBoostingRegressor(random_state=0,n_estimators=300,max_depth=3).fit(Xs,meta.sC)
ev("회귀 B (전체 특징, 3회 평균 학습)",np.clip(rh.predict(Xr),0,None),np.clip(rc.predict(Xr),0,None))
txt="\n".join(lines); print(txt); open("sim2real_v2avg_result.txt","w").write(txt)
