"""수정 후 엔진(v2)에서 AI 끔/켬을 학습에 안 쓴 가상 데이터(sweep 4단계 × 120배치 × 3회)로 비교."""
import os, sys, glob, pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay_compare as rc
HERE = os.path.dirname(os.path.abspath(__file__))
out = []
for d in sorted(glob.glob(os.path.join(HERE, "..", "sweep_*"))):
    label = os.path.basename(d).replace("sweep_", "")
    r = rc.run_dataset("after", d, label); r["engine"] = "ai" if os.getenv("RAIL_AI") == "1" else "rule"
    out.append(r); print(label, "done", flush=True)
pd.concat(out).to_csv(os.path.join(HERE, f"cmp_sweep_{'ai' if os.getenv('RAIL_AI')=='1' else 'rule'}.csv"), index=False, encoding="utf-8-sig")
