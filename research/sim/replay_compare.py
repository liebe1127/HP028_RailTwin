"""수정 전(팀 엔진) / 수정 후(rail_judge_v2) 를 같은 재생 장치로 돌려 비교한다.

  1. 실측 24회 (기준선 정상 6회 → 정상 6, 단차 6, 처짐 6, 좌우 6 재생)
  2. 가상 v2 1,800회 (수정 전 결과는 replay_virtual_result.csv 재사용)
  3. 다시 놓임 실험 4단계 × 120배치 (../sweep_*)
"""
import glob, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
os.environ.setdefault("RAIL_BASELINE_FILE", os.path.join(HERE, "..", "server", "cmp_baseline.json"))
import rail_defect                      # 수정 전
import rail_judge_v2                    # 수정 후
import replay_virtual as rv

ST = {"ok": "normal", "caution": "caution", "danger": "danger"}


def make_engine(which):
    bl = os.environ["RAIL_BASELINE_FILE"]
    if os.path.exists(bl):
        os.remove(bl)
    if which == "before":
        return rail_defect.DefectRuleEngine(segment_count=20, rail_length_cm=180.0)
    return rail_judge_v2.DefectRuleEngineV2(segment_count=20, rail_length_cm=180.0)


def run_real(which):
    eng = make_engine(which)
    eng.baseline_mode = True
    for f in sorted(glob.glob(os.path.join(HERE, "..", "realdata", "1. 정상", "*.csv"))):
        rv.feed(eng, f)
    eng.baseline_mode = False
    rows = []
    for cfg, truth in [("1. 정상", "normal"), ("2. 단차", "joint_step"), ("3. 상하침하", "vertical"), ("4. 좌우 높이차", "cross_level")]:
        eng.pass_analyzer.history.clear(); eng.pass_result = None
        for i, f in enumerate(sorted(glob.glob(os.path.join(HERE, "..", "realdata", cfg, "*.csv"))), 1):
            res, _ = rv.feed(eng, f)
            rows.append(dict(engine=which, cfg=cfg, rep=i, truth=truth, srv=res["defect_type"] if res else "none",
                             stage=ST.get(res["stage"], res["stage"]) if res else "none", mag=res["magnitude_mm"] if res else np.nan,
                             side=res.get("side") if res else None, frm=res.get("from_mm") if res else None, to=res.get("to_mm") if res else None))
    return pd.DataFrame(rows)


def run_dataset(which, data, label):
    man = pd.read_csv(os.path.join(data, "manifest.csv"))
    eng = make_engine(which)
    eng.baseline_mode = True
    for pid in man[man.scenario == "normal"].placement_id.unique()[:6]:
        rv.feed(eng, os.path.join(data, "runs", man[(man.placement_id == pid) & (man.rep == 1)].file.iloc[0]))
    eng.baseline_mode = False
    rows = []
    for pid, g in man.groupby("placement_id"):
        eng.pass_analyzer.history.clear(); eng.pass_result = None
        for r in g.sort_values("rep").itertuples():
            res, fm = rv.feed(eng, os.path.join(data, "runs", r.file), watch_motion=(r.rep >= 2))
            rec = dict(engine=which, dataset=label, placement_id=pid, rep=r.rep, scenario=r.scenario, defects=r.defects,
                       true_HF=r.size_HF_mm, true_C=r.size_C_mm, true_stage=r.stage, pert=r.rail_pert_rms_mm, enc_true=r.enc_scale_left)
            if res is None:
                rec.update(srv_type="none", srv_stage="none", srv_HF=np.nan, srv_C=np.nan, srv_E=np.nan, enc_srv=np.nan)
            else:
                s = res["sizes_mm"]
                rec.update(srv_type=res["defect_type"], srv_stage=ST.get(res["stage"], res["stage"]), srv_HF=s["joint_step"], srv_C=s["vertical"],
                           srv_E=s["cross_level"], enc_srv=res.get("encoder_scale"), srv_from=res.get("from_mm"), srv_to=res.get("to_mm"),
                           drift_flag=res.get("rebaseline_recommended", None))
            rec["motion_first"] = fm[0] if fm else None; rec["motion_x"] = fm[1] if fm else np.nan
            rows.append(rec)
    return pd.DataFrame(rows)


def main():
    out = {}
    out["real"] = pd.concat([run_real("before"), run_real("after")])
    out["real"].to_csv(os.path.join(HERE, "cmp_real.csv"), index=False, encoding="utf-8-sig")
    print("실측 완료", flush=True)
    before = pd.read_csv(os.path.join(HERE, "replay_virtual_result.csv")); before["engine"] = "before"; before["dataset"] = "v2"
    after = run_dataset("after", os.path.join(HERE, "..", "dataset_v2"), "v2")
    pd.concat([before, after]).to_csv(os.path.join(HERE, "cmp_v2.csv"), index=False, encoding="utf-8-sig")
    print("가상 1800 완료", flush=True)
    sw = []
    for d in sorted(glob.glob(os.path.join(HERE, "..", "sweep_*"))):
        label = os.path.basename(d).replace("sweep_", "")
        for which in ("before", "after"):
            sw.append(run_dataset(which, d, label)); print(label, which, "완료", flush=True)
    pd.concat(sw).to_csv(os.path.join(HERE, "cmp_sweep.csv"), index=False, encoding="utf-8-sig")
    print("done")


if __name__ == "__main__":
    main()
