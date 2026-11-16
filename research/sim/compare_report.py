import numpy as np, pandas as pd
pd.set_option("display.width",220)
L=[]; p=lambda s="": L.append(s)
v=pd.read_csv("cmp_v2.csv"); sw=pd.read_csv("cmp_sweep.csv"); real=pd.read_csv("cmp_real.csv")
def type_ok(r):
    if r.scenario=="normal": return r.srv_type=="normal"
    present=[]
    if r.true_HF>=0.5: present.append("joint_step")
    if r.true_C>=0.5: present.append("vertical")
    if not present: return r.srv_type=="normal"
    return r.srv_type in present
def variant(r):
    if r.scenario=="normal": return "정상"
    tags=[]
    for x in str(r.defects).split(";"):
        k,side,where,size,var=x.split(":")
        if k=="HF": tags.append(f"단차 {'파이프전체' if var=='pipe' else '끝만'} {'양쪽' if side=='both' else '한쪽'}")
        if k=="C": tags.append(f"침하 {'600·1200' if where=='[1, 2]' else '받침하나'}")
    return " + ".join(tags)
for d in (v,sw):
    d["종류정답"]=d.apply(type_ok,axis=1); d["변형"]=d.apply(variant,axis=1)
rows=[]
for w,name in [("before","수정 전"),("after","수정 후")]:
    d=v[v.engine==w]; d3=d[d.rep==3]
    mn=d[d.scenario=="normal"]; mn3=d3[d3.scenario=="normal"]
    sd=d3[d3.scenario.isin(["HF","C"])]
    cau=sd[sd.true_stage=="caution"]; dan=sd[sd.true_stage=="danger"]
    hf=d[(d.scenario=="HF")&(d.srv_type=="joint_step")]; c=d[(d.scenario=="C")&(d.srv_type=="vertical")]
    mo=d[d.rep>=2]; mx=mo.dropna(subset=["motion_x"])
    rows.append({"엔진":name,
        "종류 정답(1회)":f"{d.종류정답.mean()*100:.0f}%",
        "3회째 단계 정답(전체)":f"{(d3.srv_stage==d3.true_stage).mean()*100:.0f}%",
        "정답 '주의' 결함 → 주의":f"{(cau.srv_stage=='caution').mean()*100:.0f}% (n={len(cau)})",
        "정답 '위험' 결함 → 위험":f"{(dan.srv_stage=='danger').mean()*100:.0f}% (n={len(dan)})",
        "정상 오경보(1회)":f"{(mn.srv_type!='normal').mean()*100:.0f}%",
        "정상 3회째 주의 이상":f"{(mn3.srv_stage!='normal').mean()*100:.0f}%",
        "단차 크기 비율 중앙값":f"{(hf.srv_HF.abs()/hf.true_HF).median():.2f}",
        "처짐 크기 비율 중앙값":f"{(c.srv_C.abs()/c.true_C).median():.2f}",
        "정지 신호 있음":f"{(mo.motion_first=='stop').sum()}회", "감속 신호 있음":f"{(mo.motion_first=='slow').sum()}회",
        "첫 신호 위치 중앙값":f"{mx.motion_x.median():.0f} mm" if len(mx) else "-"})
t=pd.DataFrame(rows).set_index("엔진").T
p("== 가상 v2 1,800회 (600배치×3회, 다시 놓임 0.08~0.25) — 수정 전 / 후"); p(t.to_string())
p("\n== 결함 모양별 크기 비율(서버/정답, 중앙값) — 다시 놓임 0 데이터")
z=sw[sw.dataset=="0.0_0.0"]
for w,name in [("before","수정 전"),("after","수정 후")]:
    d=z[z.engine==w]; out={}
    for var,g in d[d.scenario=="HF"].groupby("변형"): out[var]=round((g.srv_HF.abs()/g.true_HF).median(),2)
    for var,g in d[d.scenario=="C"].groupby("변형"): out[var]=round((g.srv_C.abs()/g.true_C).median(),2)
    p(f"  {name}: {out}")
p("\n== 다시 놓임 크기별 정상 오경보(1회) / 정상 3회째 주의 이상 / 위험 결함 3회째 위험 판정 — 수정 전 → 후")
for lab,g in sw.groupby("dataset"):
    cells=[]
    for w in ("before","after"):
        d=g[g.engine==w]; mn=d[d.scenario=="normal"]; d3=d[d.rep==3]; mn3=d3[d3.scenario=="normal"]
        dan=d3[(d3.scenario.isin(["HF","C"]))&(d3.true_stage=="danger")]
        cells.append(f"{(mn.srv_type!='normal').mean()*100:.0f}% / {(mn3.srv_stage!='normal').mean()*100:.0f}% / {(dan.srv_stage=='danger').mean()*100:.0f}%")
    p(f"  {lab:<10s}  수정 전 {cells[0]:<22s} → 수정 후 {cells[1]}")
p("\n== 수정 후 결함 위치 보고 (가상 v2, 단일 단차 회차): 서버가 보고한 구간이 실제 이음부를 포함하는 비율")
a=v[(v.engine=="after")&(v.scenario=="HF")&(v.srv_type=="joint_step")].copy()
def joint_of(s):
    for x in str(s).split(";"):
        k,side,where,size,var=x.split(":")
        if k=="HF": return 600.0 if where=="1" else 1200.0
a["j"]=a.defects.apply(joint_of); ok=((a.srv_from<=a.j)&(a.srv_to>=a.j)).mean()
p(f"  {ok*100:.0f}% (수정 전은 항상 600~1200 고정)")
p("\n== 실측 24회 — 수정 전 / 후 (종류/단계/크기)")
for w in ("before","after"):
    d=real[real.engine==w]; p(f"  [{w}]")
    for cfg,g in d.groupby("cfg",sort=False): p(f"    {cfg}: "+", ".join(f"{r.srv[:6]}/{r.stage[:4]}/{r.mag:.2f}" for r in g.itertuples()))
txt="\n".join(L); print(txt); open("compare_report.txt","w").write(txt)
