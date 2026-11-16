import numpy as np, pandas as pd, matplotlib, os
matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib import font_manager
for f in font_manager.findSystemFonts():
    if "NotoSansCJK" in f and "Regular" in f: font_manager.fontManager.addfont(f)
plt.rcParams["font.family"]="Noto Sans CJK KR"; plt.rcParams["axes.unicode_minus"]=False
D="../dataset"; m=pd.read_csv(f"{D}/manifest.csv")
print(m.scenario.value_counts().to_dict()); print(m.stage.value_counts().to_dict())
print(pd.crosstab(m.scenario, m.stage))
print("samples total", m.n_samples.sum(), "speed", m.speed_mm_s.min(), m.speed_mm_s.max())
KR={"normal":"정상","HF":"이음부 단차","C":"수직 방향 변형","E":"좌우 높이차","mixed":"겹침"}
ST={"normal":"정상","caution":"주의","danger":"위험"}; SC={"normal":"#2ca02c","caution":"#ffbf00","danger":"#d62728"}
fig,axes=plt.subplots(5,1,figsize=(14,15),sharex=True)
for ax,k in zip(axes,["normal","HF","C","E","mixed"]):
    row=m[m.scenario==k].iloc[1]
    d=pd.read_csv(f"{D}/runs/{row.file}")
    for s,c in [("left","tab:blue"),("right","tab:red")]:
        ax.plot(d.rail_x_mm,d[f"{s}_sensor_distance_mm"],color=c,lw=.8,label=f"{'좌' if s=='left' else '우'} 센서(잡음 포함)")
        ax.plot(d.rail_x_mm,d[f"{s}_clean_mm"],color=c,lw=1.2,ls="--",alpha=.7,label=f"{'좌' if s=='left' else '우'} 잡음 없는 값")
    # stage shading
    st=d.label_stage.to_numpy(); x=d.rail_x_mm.to_numpy()
    for lab in ["caution","danger"]:
        mm=st==lab
        if mm.any():
            edges=np.where(np.diff(np.r_[0,mm.astype(int),0])!=0)[0]
            for a,b in zip(edges[::2],edges[1::2]):
                ax.axvspan(x[a],x[min(b,len(x)-1)],color=SC[lab],alpha=.15,lw=0)
    ax.set_title(f"{row.file}  {KR[k]} — {row.defects if row.defects==row.defects else '결함 없음'}  | 속도 {row.speed_mm_s} mm/s | 회차 판정 {ST[row.stage]}",fontsize=10)
    ax.grid(alpha=.35); ax.legend(fontsize=8,loc="lower left",ncol=4); ax.set_ylabel("mm")
axes[-1].set_xlabel("레일 위치 x mm   (노랑 띠 = 주의 구간, 빨강 띠 = 위험 구간 정답)")
fig.suptitle("가상 데이터셋 예시 — 시나리오별 한 회차씩 (HF 이음부 단차, C 수직 방향 변형, E 좌우 높이차)",fontsize=13)
fig.tight_layout(rect=(0,0,1,.97)); fig.savefig("dataset_examples.png",dpi=110)
fig2,ax2=plt.subplots(1,3,figsize=(15,4))
for k,c in [("HF","tab:orange"),("C","tab:green"),("E","tab:purple")]:
    sz=pd.concat([m.loc[m.kind1==k,"size1_mm"],m.loc[m.kind2==k,"size2_mm"]])
    ax2[0].hist(sz,bins=30,alpha=.6,label=f"{KR[k]} ({len(sz)}개)",color=c)
ax2[0].set_title("결함 크기 분포 (mm)"); ax2[0].legend(fontsize=8); ax2[0].grid(alpha=.3)
ct=pd.crosstab(m.scenario,m.stage).reindex(["normal","HF","C","E","mixed"])[["normal","caution","danger"]]
ct.index=[KR[i] for i in ct.index]; ct.columns=[ST[c] for c in ct.columns]
ct.plot.bar(ax=ax2[1],stacked=True,color=[SC["normal"],SC["caution"],SC["danger"]],rot=0); ax2[1].set_title("시나리오별 회차 판정 (회차 수)"); ax2[1].grid(alpha=.3,axis="y")
ax2[2].hist(m.speed_mm_s,bins=20,color="0.5"); ax2[2].set_title("주행 속도 분포 (mm/s)"); ax2[2].grid(alpha=.3)
fig2.tight_layout(); fig2.savefig("dataset_stats.png",dpi=110)
