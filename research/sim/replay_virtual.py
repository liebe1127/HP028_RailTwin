"""2단계 가상 시운전 — 가상 주행을 서버 판정 엔진(rail_defect.DefectRuleEngine)에 그대로 재생한다.

서버 코드는 레포 그대로(../server), 한 줄도 바꾸지 않는다. replay_csv.py 가 실측을 넣던 방식과 같게
행 단위로 evaluate_pair → 주행 끝에 finish_pass.

  기준선: 가상 정상 주행 6회 등록 (서로 다른 배치에서 1회씩)
  재생:   dataset_v2 의 600 배치 × 3회. 같은 배치 3회를 연달아 넣어 3회째 판정 단계를 본다 (논문 2.3 규칙)
  기록:   회차별 서버 판별 종류·크기·단계·엔코더 배율, 감속/정지 신호가 처음 나온 위치
"""
import os, sys, json
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
os.environ["RAIL_BASELINE_FILE"] = os.path.join(HERE, "..", "server", "virtual_baseline.json")
import rail_defect  # noqa: E402

DATA = os.path.join(HERE, "..", "dataset_v2")
TYPE = {"normal": "normal", "HF": "joint_step", "C": "vertical", "HF+C": "joint_step|vertical"}
STAGE_SRV = {"ok": "normal", "caution": "caution", "danger": "danger"}


def rows_of(path):
    d = pd.read_csv(path)
    return d


def side_sample(r, side):
    return {"position_mm": float(r[f"{side}_position_mm"]), "sensor_distance_mm": float(r[f"{side}_sensor_distance_mm"]),
            "accel_x": None, "accel_y": None, "accel_z": None, "gyro_y": None, "_received_at": float(r["uptime_us"]) / 1e6}


def feed(engine, path, watch_motion=False):
    d = rows_of(path)
    first_motion = None
    L = d[[c for c in d.columns if c.startswith("left_") or c == "uptime_us"]]
    for i in range(len(d)):
        r = d.iloc[i]
        snap = engine.evaluate_pair(side_sample(r, "left"), side_sample(r, "right"))
        if watch_motion and first_motion is None and isinstance(snap, dict) and snap.get("motion") not in (None, "cruise"):
            first_motion = (snap["motion"], float(r["rail_x_mm"]))
    res = engine.finish_pass()
    return res, first_motion


def main():
    man = pd.read_csv(os.path.join(DATA, "manifest.csv"))
    bl = os.environ["RAIL_BASELINE_FILE"]
    if os.path.exists(bl): os.remove(bl)
    engine = rail_defect.DefectRuleEngine(segment_count=20, rail_length_cm=180.0)
    # 기준선: 정상 배치 6개에서 1회씩
    normal_pids = man[man.scenario == "normal"].placement_id.unique()[:6]
    engine.baseline_mode = True
    for pid in normal_pids:
        f = man[(man.placement_id == pid) & (man.rep == 1)].file.iloc[0]
        feed(engine, os.path.join(DATA, "runs", f))
    engine.baseline_mode = False
    print("기준선 등록:", engine.pass_analyzer.baseline_count, "회")
    out = []
    for n, (pid, g) in enumerate(man.groupby("placement_id"), 1):
        engine.pass_analyzer.history.clear()
        engine.pass_result = None
        g = g.sort_values("rep")
        for r in g.itertuples():
            res, fm = feed(engine, os.path.join(DATA, "runs", r.file), watch_motion=(r.rep >= 2))
            rec = dict(placement_id=pid, rep=r.rep, scenario=r.scenario, defects=r.defects, true_HF=r.size_HF_mm, true_C=r.size_C_mm,
                       true_stage=r.stage, speed=r.speed_mm_s, enc_true=r.enc_scale_left, pert=r.rail_pert_rms_mm)
            if res is None:
                rec.update(srv_type="none", srv_stage="none", srv_mag=np.nan, srv_HF=np.nan, srv_C=np.nan, srv_E=np.nan, enc_srv=np.nan)
            else:
                s = res["sizes_mm"]
                rec.update(srv_type=res["defect_type"], srv_stage=STAGE_SRV.get(res["stage"], res["stage"]), srv_mag=res["magnitude_mm"],
                           srv_HF=s["joint_step"], srv_C=s["vertical"], srv_E=s["cross_level"], enc_srv=res.get("encoder_scale"),
                           srv_side=res["side"], srv_from=res["from_mm"], srv_to=res["to_mm"])
            rec["motion_first"] = fm[0] if fm else None; rec["motion_x"] = fm[1] if fm else np.nan
            out.append(rec)
        if n % 100 == 0: print(f"{n}/600 배치")
    df = pd.DataFrame(out)
    df.to_csv(os.path.join(HERE, "replay_virtual_result.csv"), index=False, encoding="utf-8-sig")
    print("saved")


if __name__ == "__main__":
    main()
