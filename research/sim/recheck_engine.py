import os, sys, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import replay_compare as rc
tag = "ai" if os.getenv("RAIL_AI") == "1" else "rule"
r = rc.run_dataset("after", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dataset_recheck"), "recheck"); r["engine"] = tag
r.to_csv(f"cmp_recheck_{tag}.csv", index=False, encoding="utf-8-sig"); print("done", tag)
