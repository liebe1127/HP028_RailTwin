import numpy as np, pandas as pd
pd.set_option("display.width", 220)
df = pd.read_csv("replay_virtual_result.csv")
L = []
def p(s=""): L.append(s)
p(f"재생 {len(df)}회 (배치 {df.placement_id.nunique()}개), 결과 없음 {int((df.srv_type=='none').sum())}회")
# 엔코더 보정
e = df.dropna(subset=["enc_srv"]); err = (e.enc_srv - e.enc_true) / e.enc_true * 100
p(f"엔코더 배율 복원: {len(e)}/{len(df)}회 성공, 오차 중앙값 {err.abs().median():.2f} %, 95% 이내 {np.percentile(err.abs(),95):.2f} %, 5 % 넘는 회차 {int((err.abs()>5).sum())}")
# 변형 분류
def variant(r):
    if r.scenario == "normal": return "정상"
    parts = str(r.defects).split(";")
    tags = []
    for d in parts:
        k, side, where, size, var = d.split(":")
        if k == "HF": tags.append(f"단차 {'파이프전체' if var=='pipe' else '끝만'} {'양쪽' if side=='both' else '한쪽'}")
        if k == "C": tags.append(f"침하 {'600·1200' if where=='[1, 2]' else ('600' if where=='[1]' else '1200')}")
    return " + ".join(tags)
df["변형"] = df.apply(variant, axis=1)
# 종류 정답 (1회 단위)
def type_ok(r):
    if r.scenario == "normal": return r.srv_type == "normal"
    present = []
    if r.true_HF >= 0.5: present.append("joint_step")
    if r.true_C >= 0.5: present.append("vertical")
    if not present: return r.srv_type == "normal"
    return r.srv_type in present
df["종류정답"] = df.apply(type_ok, axis=1)
# 단계 정답 (3회째)
d3 = df[df.rep == 3].copy()
d3["단계정답"] = d3.srv_stage == d3.true_stage
p("\n== 시나리오별 (종류 정답 = 1회 단위 1,800회, 단계 정답 = 3회째 600배치)")
g = df.groupby("scenario").agg(회수=("종류정답","size"), 종류정답률=("종류정답","mean"))
g3 = d3.groupby("scenario").agg(배치=("단계정답","size"), 단계정답률=("단계정답","mean"))
t = g.join(g3); t["종류정답률"]=(t.종류정답률*100).round(1); t["단계정답률"]=(t.단계정답률*100).round(1)
p(t.to_string())
p("\n== 결함 모양별 (서버 템플릿은 '가운데 파이프 전체 단차'와 '600~1200 처짐' 두 가지뿐)")
g = df.groupby("변형").agg(회수=("종류정답","size"), 종류정답률=("종류정답","mean"))
g3 = d3.groupby("변형").agg(단계정답률=("단계정답","mean"))
t = g.join(g3); t["종류정답률"]=(t.종류정답률*100).round(1); t["단계정답률"]=(t.단계정답률*100).round(1)
p(t.sort_values("종류정답률").to_string())
# 크기: 단일 결함만
p("\n== 크기 추정 (서버 크기 vs 정답, 단일 결함·종류 맞춘 회차)")
for kind, col_true, col_srv, srv_name in [("HF","true_HF","srv_HF","joint_step"),("C","true_C","srv_C","vertical")]:
    m = (df.scenario==kind)&(df.srv_type==srv_name)
    err = (df.loc[m,col_srv].abs()-df.loc[m,col_true])
    p(f"  {kind}: n={m.sum()}, 오차 평균 {err.mean():+.2f} mm, RMS {np.sqrt((err**2).mean()):.2f} mm")
    for v, mm in df[m].groupby("변형"):
        e2 = (mm[col_srv].abs()-mm[col_true]); p(f"     {v:<22s} n={len(mm):3d} 오차 평균 {e2.mean():+.2f}, RMS {np.sqrt((e2**2).mean()):.2f}, 비율(서버/정답) {np.median(mm[col_srv].abs()/mm[col_true]):.2f}")
# 정상 오경보
mn = df[df.scenario=="normal"]
p(f"\n== 정상 레일 오경보: 1회 단위 {int((mn.srv_type!='normal').sum())}/{len(mn)}회 ({(mn.srv_type!='normal').mean()*100:.1f} %), 3회째 단계가 주의 이상 {int((d3[d3.scenario=='normal'].srv_stage!='normal').sum())}/{len(d3[d3.scenario=='normal'])}배치")
p("   오경보 때 서버가 본 종류: " + str(mn[mn.srv_type!='normal'].srv_type.value_counts().to_dict()))
# 단계 혼동
p("\n== 3회째 단계 혼동 행렬 (행 정답, 열 서버)")
p(pd.crosstab(d3.true_stage, d3.srv_stage).to_string())
# 크기 구간별 단계 정답
p("\n== 결함 크기 구간별 3회째 단계 정답률 (단일 결함)")
for kind,col in [("HF","true_HF"),("C","true_C")]:
    s = d3[d3.scenario==kind].copy(); s["bin"]=pd.cut(s[col],[0,0.5,1.0,2.0,4.0])
    p(f"  {kind}: " + str({str(k): f"{v*100:.0f}% (n={n})" for (k,v),n in zip(s.groupby('bin',observed=True)['단계정답'].mean().items(), s.groupby('bin',observed=True).size())}))
# 속도
p("\n== 속도별 종류 정답률")
df["속도"]=pd.cut(df.speed,[29,50,75,101]); p(str({str(k): f"{v*100:.1f}%" for k,v in df.groupby("속도",observed=True)["종류정답"].mean().items()}))
# 감속/정지
mo = df[(df.rep>=2)]
p(f"\n== 감속·정지 신호 (2·3회째, 직전 주행 결과가 있을 때): 신호 나온 회차 {int(mo.motion_first.notna().sum())}/{len(mo)}")
p("   종류별: " + str(mo.motion_first.value_counts(dropna=False).to_dict()))
mx = mo.dropna(subset=["motion_x"])
p(f"   처음 신호 위치(센서 기준 rail_x) 중앙값 {mx.motion_x.median():.0f} mm, 범위 {mx.motion_x.min():.0f}~{mx.motion_x.max():.0f} mm  (서버는 결함 구간을 항상 600~1200 으로 보고)")
p(f"   정상 배치에서 신호 나온 회차: {int(mo[mo.scenario=='normal'].motion_first.notna().sum())}/{len(mo[mo.scenario=='normal'])}")
txt="\n".join(L); print(txt); open("replay_virtual_report.txt","w").write(txt)
