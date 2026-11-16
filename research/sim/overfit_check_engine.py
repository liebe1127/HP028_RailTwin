"""과적합 검사 1: 수정안을 설계할 때 본 적 없는 새 seed 데이터로 수정 전/후를 다시 잰다."""
import os, sys, numpy as np, pandas as pd
import replay_compare as rc
d_after = rc.run_dataset("after", "../dataset_v2_seed9", "seed9")
d_before = rc.run_dataset("before", "../dataset_v2_seed9", "seed9")
df = pd.concat([d_before, d_after])
def type_ok(r):
    if r.scenario=="normal": return r.srv_type=="normal"
    present=[]
    if r.true_HF>=0.5: present.append("joint_step")
    if r.true_C>=0.5: present.append("vertical")
    if not present: return r.srv_type=="normal"
    return r.srv_type in present
df["종류정답"]=df.apply(type_ok,axis=1)
rows=[]
for w,name in [("before","수정 전"),("after","수정 후")]:
    d=df[df.engine==w]; d3=d[d.rep==3]; mn=d[d.scenario=="normal"]
    sd=d3[d3.scenario.isin(["HF","C"])]; cau=sd[sd.true_stage=="caution"]; dan=sd[sd.true_stage=="danger"]
    hf=d[(d.scenario=="HF")&(d.srv_type=="joint_step")]
    rows.append({"엔진":name,"종류 정답(1회)":f"{d.종류정답.mean()*100:.0f}%","위험→위험":f"{(dan.srv_stage=='danger').mean()*100:.0f}% (n={len(dan)})",
                 "주의→주의":f"{(cau.srv_stage=='caution').mean()*100:.0f}% (n={len(cau)})","정상 오경보(1회)":f"{(mn.srv_type!='normal').mean()*100:.0f}%",
                 "단차 크기 비율":f"{(hf.srv_HF.abs()/hf.true_HF).median():.2f}"})
t=pd.DataFrame(rows).set_index("엔진").T
print("== 새 seed(9) 240배치×3회 — 설계 때 안 본 데이터"); print(t.to_string())
t.to_csv("overfit_check_engine.csv",encoding="utf-8-sig")
