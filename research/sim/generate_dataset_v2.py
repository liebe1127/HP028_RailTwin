"""시나리오 생성기 v2 — 1단계용 (좌우 높이차 제외).

v1 에서 바뀐 것
  1. 레일 다시 놓임을 "배치"마다 한 번만 뽑는다. 한 배치에서 여러 회(기본 3회)를 달리며, 회차마다는 잡음·속도·엔코더만 다르다.
     (실측에서 다시 놓임은 받침을 바꿔 끼울 때 생기고, 같은 배치의 6회 안에서는 유지됐다)
  2. 다시 놓임 크기를 실측 범위로: 현측정 RMS 0.08~0.25 mm (실측 추정 0.1~0.25)
  3. 시나리오: 정상 / 이음부 단차(HF) / 수직 방향 변형(C) / HF+C 겹침. 좌우 높이차(E)는 뺀다.

python3 generate_dataset_v2.py --placements 600 --runs 3 --seed 2 --out ../dataset_v2
"""
import argparse, os
import numpy as np
import pandas as pd

import railsim as rs
import generate_dataset as gd

PERT_RMS = (0.08, 0.25)


def make_scenario_v2(rng, kind):
    pipes = {"left": gd.flat_pipes(), "right": gd.flat_pipes()}
    defects = []

    def add_HF():
        j = int(rng.integers(1, rs.N_PIPE))
        size = gd.draw_size(rng, "HF") * (1 if rng.random() < 0.6 else -1)
        variant = "pipe" if rng.random() < 0.5 else "end"
        side_mode = rng.choice(["both", "left", "right"], p=[0.5, 0.25, 0.25])
        for s in (["left", "right"] if side_mode == "both" else [side_mode]):
            gd.apply_step(pipes[s], j, size, variant)
        defects.append(dict(kind="HF", side=side_mode, where=j, size=abs(size), signed=size, variant=variant))

    def add_C():
        sup = [1] if rng.random() < 0.5 else [1, 2]
        if len(sup) == 1 and rng.random() < 0.5:
            sup = [2]
        depth = gd.draw_size(rng, "C")
        for s in ["left", "right"]:
            gd.apply_settle(pipes[s], sup, depth)
        defects.append(dict(kind="C", side="both", where=sup, size=depth, signed=-depth, variant="settle"))

    if kind == "HF":
        add_HF()
    elif kind == "C":
        add_C()
    elif kind == "HF+C":
        add_HF(); add_C()
    return pipes, defects


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placements", type=int, default=600)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--seed", type=int, default=2)
    ap.add_argument("--out", default="../dataset_v2")
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    os.makedirs(os.path.join(a.out, "runs"), exist_ok=True)
    kinds = ["normal", "HF", "C", "HF+C"]
    plan = np.array([kinds[i % 4] for i in range(a.placements)]); rng.shuffle(plan)
    nb = {s: np.array(gd.CAL["noise_bank"][s]) for s in ["left", "right"]}
    rsh = {s: np.array(gd.CAL[f"rshape_{s}"]) for s in ["left", "right"]}
    H = {s: gd.CAL[f"H_{s}"] for s in ["left", "right"]}
    manifest, profiles = [], []
    t0 = pd.Timestamp("2026-10-29T10:00:00+09:00")
    run_id = 0
    for pid, kind in enumerate(plan, 1):
        pipes, defects = make_scenario_v2(rng, kind)
        pert_rms = float(rng.uniform(*PERT_RMS))
        pert = {s: gd.rail_perturbation(rng, pert_rms) for s in ["left", "right"]}   # 배치마다 한 번
        for rep in range(1, a.runs + 1):
            run_id += 1
            speed = float(rng.uniform(30, 100))
            x0 = float(rng.uniform(280, 320)); x1 = float(rng.uniform(1500, 1540))
            n = int((x1 - x0) / speed / gd.DT); t = np.arange(n) * gd.DT; x = x0 + speed * t
            enc = {"left": float(rng.uniform(0.84, 0.99)), "right": float(rng.uniform(1.06, 1.12))}
            cols = {"time": [(t0 + pd.Timedelta(seconds=float(tt))).isoformat() for tt in t],
                    "uptime_us": (t * 1e6).astype(np.int64)}
            chord = {}
            for s in ["left", "right"]:
                meas, clean, ch, pitch = gd.side_signal(x, pipes[s], pert[s], H[s], rsh[s], nb[s], gd.SPIKE[s], rng)
                cols[f"{s}_position_mm"] = np.round((x - x0) / enc[s], 2)
                cols[f"{s}_sensor_distance_mm"] = np.round(meas, 3)
                cols[f"{s}_clean_mm"] = np.round(clean, 3)
                cols[f"{s}_tilt_deg"] = np.round(pitch, 3)
                chord[s] = ch
            roll = np.degrees(np.arctan2(chord["left"] - chord["right"], gd.TRACK))
            cols["left_roll_deg"] = np.round(roll, 3); cols["right_roll_deg"] = np.round(roll, 3)
            cols["rail_x_mm"] = np.round(x, 2)
            jm = np.zeros(n, dtype=int)
            for j in rs.JOINTS:
                idx = np.argmin(np.abs(x - j))
                if abs(x[idx] - j) < 3: jm[idx] = int(j)
            cols["joint_marker"] = jm
            lab_type = np.array(["normal"] * n, dtype=object); lab_size = np.zeros(n); lab_stage = np.array(["normal"] * n, dtype=object)
            run_stage = "normal"; sHF = 0.0; sC = 0.0
            for d in defects:
                lo, hi = gd.affected_range(d["kind"], d["where"]); m = (x >= lo) & (x <= hi)
                tag = f"{d['kind']}_{d['side']}"
                lab_type[m] = np.where(lab_type[m] == "normal", tag, lab_type[m] + "+" + tag)
                lab_size[m] = np.maximum(lab_size[m], d["size"])
                st = gd.stage_of(d["kind"], d["size"])
                lab_stage[m] = [st if gd.STAGE_RANK[st] > gd.STAGE_RANK[v] else v for v in lab_stage[m]]
                if gd.STAGE_RANK[st] > gd.STAGE_RANK[run_stage]: run_stage = st
                if d["kind"] == "HF": sHF = d["size"]
                if d["kind"] == "C": sC = d["size"]
            cols["label_type"] = lab_type; cols["label_size_mm"] = np.round(lab_size, 3); cols["label_stage"] = lab_stage
            fname = f"run_{run_id:04d}.csv"
            pd.DataFrame(cols).to_csv(os.path.join(a.out, "runs", fname), index=False)
            manifest.append(dict(run_id=run_id, placement_id=pid, rep=rep, file=fname, scenario=kind,
                                 defects=";".join(f"{d['kind']}:{d['side']}:{d['where']}:{d['signed']:+.2f}:{d['variant']}" for d in defects),
                                 size_HF_mm=round(sHF, 3), size_C_mm=round(sC, 3), stage=run_stage,
                                 speed_mm_s=round(speed, 1), n_samples=n, enc_scale_left=round(enc["left"], 4),
                                 enc_scale_right=round(enc["right"], 4), rail_pert_rms_mm=round(pert_rms, 3)))
        prof = dict(placement_id=pid)
        for s in ["left", "right"]:
            for k, (p0, p1) in enumerate(pipes[s]):
                prof[f"{s}_pipe{k+1}_start_mm"] = round(p0, 3); prof[f"{s}_pipe{k+1}_end_mm"] = round(p1, 3)
        profiles.append(prof)
        if pid % 100 == 0: print(f"{pid}/{a.placements} placements")
    pd.DataFrame(manifest).to_csv(os.path.join(a.out, "manifest.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame(profiles).to_csv(os.path.join(a.out, "rail_profiles.csv"), index=False)
    print("done", a.out, run_id, "runs")


if __name__ == "__main__":
    main()
