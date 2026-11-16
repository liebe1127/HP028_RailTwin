import numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
from load_run import load_run
import railsim as rs
r=load_run("run_0928_1.csv")
fig,ax=plt.subplots(2,1,figsize=(14,9),sharex=True)
for i,(s,c) in enumerate([("left","tab:blue"),("right","tab:red")]):
    v=r[s]; ax[i].plot(v["x"],v["gap"],c,lw=.8,label=f"real {s}")
    x=np.linspace(260,1560,1301)
    for name,cfg in rs.CONFIGS.items():
        pipes=rs.support_heights(cfg["L" if s=="left" else "R"])
        y=rs.versine_of_profile(x,pipes)
        H=np.nanmedian(v["gap"])
        ax[i].plot(x,H+y,lw=1,ls="--",label=f"model {name}")
    for j in (600,1200): ax[i].axvline(j,color="k",lw=.5)
    ax[i].grid(); ax[i].legend(fontsize=8,ncol=3); ax[i].set_ylim(5.2,8)
ax[1].set_xlabel("rail x mm")
plt.tight_layout(); plt.savefig("aligned.png",dpi=90)
