import glob, os, numpy as np, pandas as pd
rows=[]
for f in sorted(glob.glob("data/c*_r*.csv")):
    d=pd.read_csv(f)
    w=(d.analysis_window==1)&(d.sensor_valid==1)
    x=d.rail_x_mm[w].to_numpy(); 
    jm=d.joint_marker[w].to_numpy()
    # right spikes in rail_x coords: detect upward spikes in right gap
    g=d.right_sensor_distance_mm[w]; med=g.rolling(25,center=True,min_periods=5).median(); dev=(g-med).to_numpy()
    idx=np.where(dev>0.45)[0]
    cl=[]; cur=[]
    for i in idx:
        if cur and x[i]-x[cur[-1]]>40: cl.append(cur); cur=[]
        cur.append(i)
    if cur: cl.append(cur)
    cents=[round(float(np.average(x[c],weights=dev[c])),0) for c in cl]
    rows.append((os.path.basename(f), int(w.sum()), round(x.min()), round(x.max()), round(d.encoder_scale_left.iloc[0],3), sorted(set(jm[jm>0])), cents[:4]))
for r in rows: print(r)
