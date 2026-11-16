"""시나리오 생성기 본편 — AI 학습용 가상 주행 데이터셋.

python3 generate_dataset.py --n 2000 --seed 1 --out ../dataset

회차마다
  - 시나리오: 정상 / 이음부 단차(HF) / 수직 방향 변형(C) / 좌우 높이차(E) / 겹침(두 가지)
  - 결함 크기: 판정 단계(정상/주의/위험)를 먼저 고르게 뽑고 그 범위에서 무작위 (HF·C 0.3~4 mm, E 0.3~8 mm), 위치 무작위, 좌·우 따로
  - 속도 30~100 mm/s, 20 ms 샘플
  - 레일 다시 놓임 효과: 레일 높이에 완만한 무작위 변형을 더해 현측정 값 RMS 0.1~0.35 mm 가 되게 함
  - 잡음: 정상 6회 잔차(calibration.json)에서 무작위로 골라 밀어서 사용
  - 엔코더 미끄러짐: 좌 +1~+19 %, 우 −6~−12 % (보정_기록.csv 범위) → 서버가 스스로 보정하는지 시험할 수 있게
  - 판정 단계: 논문 2.3 규칙 (허용 한계 HF 1.0 / C 1.0 / E 5 mm, 50 % 이하 정상, 한계까지 주의, 초과 위험)

출력
  runs/run_0001.csv ... (실측 CSV 와 같은 열 이름 + 정답 열)
  manifest.csv        회차별 시나리오·크기·위치·판정·속도·엔코더 배율
  rail_profiles.csv   회차별 좌·우 파이프 끝 높이 (진짜 레일 모양)
"""
import argparse, json, os
import numpy as np
import pandas as pd

import railsim as rs

CAL = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")))
GRID = np.array(CAL["grid_mm"])
DT = 0.020
SPIKE = {"left": 1.2, "right": 1.0}
BASE_H = 21.0
LIMIT = {"HF": 1.0, "C": 1.0, "E": 5.0}
TRACK = 386.0
SIZE_RANGE = {"HF": (0.3, 4.0), "C": (0.3, 4.0), "E": (0.3, 8.0)}


def stage_of(kind, size):
    lim = LIMIT[kind]
    if size < 0.5 * lim:
        return "normal"
    if size <= lim:
        return "caution"
    return "danger"


STAGE_RANK = {"normal": 0, "caution": 1, "danger": 2}


def draw_size(rng, kind):
    """판정 단계가 고르게 나오도록 단계를 먼저 뽑고 그 범위 안에서 크기를 뽑는다."""
    lo, hi = SIZE_RANGE[kind]; lim = LIMIT[kind]
    st = rng.choice(["normal", "caution", "danger"])
    if st == "normal":
        return float(rng.uniform(lo, 0.5 * lim))
    if st == "caution":
        return float(rng.uniform(0.5 * lim, lim))
    return float(rng.uniform(lim, hi))


def flat_pipes():
    return [[BASE_H, BASE_H] for _ in range(rs.N_PIPE)]


def apply_step(pipes, joint_idx, size, variant):
    """이음부 단차. joint_idx 1 → 600, 2 → 1200. variant 'pipe': 다음 파이프 전체가 size 만큼 높/낮음,
    'end': 다음 파이프의 이음부 쪽 끝만 size 만큼."""
    k = joint_idx  # 다음 파이프 번호
    pipes[k][0] += size
    if variant == "pipe":
        pipes[k][1] += size
    return pipes


def apply_settle(pipes, supports, depth):
    """받침 침하. supports: 내려앉은 받침 번호 목록 (1 → 600, 2 → 1200). 받침을 공유하는 두 파이프 끝이 함께 내려간다."""
    for sidx in supports:
        if sidx - 1 >= 0:
            pipes[sidx - 1][1] -= depth
        if sidx < rs.N_PIPE:
            pipes[sidx][0] -= depth
    return pipes


def affected_range(kind, where):
    """정답 구간: 센서가 이 결함의 영향을 받는 x 범위."""
    half = rs.WHEELBASE / 2
    if kind == "HF":
        j = rs.JOINTS[where - 1]
        return (j - half, j + half)
    lo = min(where) * rs.PIPE - rs.PIPE - half
    hi = max(where) * rs.PIPE + rs.PIPE + half
    return (max(lo, 0), min(hi, rs.RAIL_LEN))


def rail_perturbation(rng, target_rms):
    """레일 다시 놓임 효과: 완만한 무작위 높이 변형. 현측정 값의 RMS 가 target_rms 가 되게 배율을 맞춘다."""
    lams = np.array([350.0, 500.0, 700.0, 1000.0, 1800.0])
    amps = rng.normal(0, 1, len(lams)) * np.array([0.4, 0.6, 0.8, 1.0, 1.0])
    phs = rng.uniform(0, 2 * np.pi, len(lams))

    def h(x):
        x = np.asarray(x, float)
        return sum(a * np.sin(2 * np.pi * x / l + p) for a, l, p in zip(amps, lams, phs))

    xx = np.arange(300, 1500, 2.0)
    v = (h(xx + 250) + h(xx - 250)) / 2 - h(xx)
    scale = target_rms / (np.sqrt(np.mean(v ** 2)) + 1e-9)
    return lambda x: scale * h(x)


def side_signal(x, pipes, pert, H, rshape, noise_bank, spike, rng):
    h_s = rs.rail_height(x, pipes) + pert(x)
    h_f = rs.rail_height(x + 250, pipes) + pert(x + 250)
    h_r = rs.rail_height(x - 250, pipes) + pert(x - 250)
    chord = (h_f + h_r) / 2
    clean = H + np.interp(x, GRID, rshape) + (chord - h_s)
    for j in rs.JOINTS:
        clean = clean + spike * np.exp(-0.5 * ((x - j) / 5.0) ** 2)
    k = rng.integers(noise_bank.shape[0])
    nb = np.roll(noise_bank[k], rng.integers(len(GRID)))
    noise = np.interp(x, GRID, nb)
    pitch = np.degrees(np.arctan2(h_f - h_r, rs.WHEELBASE))
    return clean + noise, clean, chord, pitch


def make_scenario(rng, kind_main):
    """시나리오 하나를 뽑아 좌·우 파이프 높이와 정답 목록을 돌려준다."""
    pipes = {"left": flat_pipes(), "right": flat_pipes()}
    defects = []  # dict(kind, side, where, size, variant)

    def add_HF():
        j = int(rng.integers(1, rs.N_PIPE))           # 1 또는 2
        size = draw_size(rng, "HF") * (1 if rng.random() < 0.6 else -1)
        variant = "pipe" if rng.random() < 0.5 else "end"
        side_mode = rng.choice(["both", "left", "right"], p=[0.5, 0.25, 0.25])
        sides = ["left", "right"] if side_mode == "both" else [side_mode]
        for s in sides:
            apply_step(pipes[s], j, size, variant)
        defects.append(dict(kind="HF", side=side_mode, where=j, size=abs(size), signed=size, variant=variant))

    def add_C():
        sup = [1] if rng.random() < 0.5 else [1, 2]
        if len(sup) == 1 and rng.random() < 0.5:
            sup = [2]
        depth = draw_size(rng, "C")
        for s in ["left", "right"]:
            apply_settle(pipes[s], sup, depth)
        defects.append(dict(kind="C", side="both", where=sup, size=depth, signed=-depth, variant="settle"))

    def add_E():
        sup = [1] if rng.random() < 0.5 else [1, 2]
        if len(sup) == 1 and rng.random() < 0.5:
            sup = [2]
        depth = draw_size(rng, "E")
        s = "left" if rng.random() < 0.5 else "right"
        apply_settle(pipes[s], sup, depth)
        defects.append(dict(kind="E", side=s, where=sup, size=depth, signed=-depth, variant="settle"))

    adders = {"HF": add_HF, "C": add_C, "E": add_E}
    if kind_main == "normal":
        pass
    elif kind_main == "mixed":
        a, b = rng.choice(["HF", "C", "E"], size=2, replace=False)
        adders[a](); adders[b]()
    else:
        adders[kind_main]()
    return pipes, defects


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="../dataset")
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    os.makedirs(os.path.join(a.out, "runs"), exist_ok=True)
    kinds = ["normal", "HF", "C", "E", "mixed"]
    plan = np.array([kinds[i % 5] for i in range(a.n)])
    rng.shuffle(plan)
    nb = {s: np.array(CAL["noise_bank"][s]) for s in ["left", "right"]}
    rsh = {s: np.array(CAL[f"rshape_{s}"]) for s in ["left", "right"]}
    H = {s: CAL[f"H_{s}"] for s in ["left", "right"]}
    manifest, profiles = [], []
    t0 = pd.Timestamp("2026-10-28T12:00:00+09:00")
    for i, kind_main in enumerate(plan, 1):
        pipes, defects = make_scenario(rng, kind_main)
        speed = float(rng.uniform(30, 100))
        x0 = float(rng.uniform(280, 320)); x1 = float(rng.uniform(1500, 1540))
        n = int((x1 - x0) / speed / DT)
        t = np.arange(n) * DT
        x = x0 + speed * t
        pert_rms = float(rng.uniform(0.10, 0.35))
        pert = {s: rail_perturbation(rng, pert_rms) for s in ["left", "right"]}
        enc = {"left": float(rng.uniform(0.84, 0.99)), "right": float(rng.uniform(1.06, 1.12))}
        cols = {"time": [(t0 + pd.Timedelta(seconds=float(tt))).isoformat() for tt in t],
                "uptime_us": (t * 1e6).astype(np.int64)}
        chord = {}
        for s in ["left", "right"]:
            meas, clean, ch, pitch = side_signal(x, pipes[s], pert[s], H[s], rsh[s], nb[s], SPIKE[s], rng)
            cols[f"{s}_position_mm"] = np.round((x - x0) / enc[s], 2)
            cols[f"{s}_sensor_distance_mm"] = np.round(meas, 3)
            cols[f"{s}_clean_mm"] = np.round(clean, 3)
            cols[f"{s}_tilt_deg"] = np.round(pitch, 3)
            chord[s] = ch
        roll = np.degrees(np.arctan2(chord["left"] - chord["right"], TRACK))
        cols["left_roll_deg"] = np.round(roll, 3); cols["right_roll_deg"] = np.round(roll, 3)
        cols["rail_x_mm"] = np.round(x, 2)
        jm = np.zeros(n, dtype=int)
        for j in rs.JOINTS:
            idx = np.argmin(np.abs(x - j))
            if abs(x[idx] - j) < 3: jm[idx] = int(j)
        cols["joint_marker"] = jm
        # 정답 열 (샘플 단위)
        lab_type = np.array(["normal"] * n, dtype=object); lab_size = np.zeros(n); lab_stage = np.array(["normal"] * n, dtype=object)
        run_stage = "normal"
        for d in defects:
            lo, hi = affected_range(d["kind"], d["where"])
            m = (x >= lo) & (x <= hi)
            tag = f"{d['kind']}_{d['side']}"
            lab_type[m] = np.where(lab_type[m] == "normal", tag, lab_type[m] + "+" + tag)
            lab_size[m] = np.maximum(lab_size[m], d["size"])
            st = stage_of(d["kind"], d["size"])
            lab_stage[m] = [st if STAGE_RANK[st] > STAGE_RANK[v] else v for v in lab_stage[m]]
            if STAGE_RANK[st] > STAGE_RANK[run_stage]: run_stage = st
        cols["label_type"] = lab_type; cols["label_size_mm"] = np.round(lab_size, 3); cols["label_stage"] = lab_stage
        fname = f"run_{i:04d}.csv"
        pd.DataFrame(cols).to_csv(os.path.join(a.out, "runs", fname), index=False)
        manifest.append(dict(
            run_id=i, file=fname, scenario=kind_main, n_defects=len(defects),
            defects=";".join(f"{d['kind']}:{d['side']}:{d['where']}:{d['signed']:+.2f}:{d['variant']}" for d in defects),
            kind1=defects[0]["kind"] if defects else "", side1=defects[0]["side"] if defects else "",
            where1=str(defects[0]["where"]) if defects else "", size1_mm=defects[0]["size"] if defects else 0.0,
            kind2=defects[1]["kind"] if len(defects) > 1 else "", side2=defects[1]["side"] if len(defects) > 1 else "",
            where2=str(defects[1]["where"]) if len(defects) > 1 else "", size2_mm=defects[1]["size"] if len(defects) > 1 else 0.0,
            stage=run_stage, speed_mm_s=round(speed, 1), n_samples=n, x_start_mm=round(x0, 1), x_end_mm=round(x1, 1),
            enc_scale_left=round(enc["left"], 4), enc_scale_right=round(enc["right"], 4), rail_pert_rms_mm=round(pert_rms, 3)))
        prof = dict(run_id=i)
        for s in ["left", "right"]:
            for k, (p0, p1) in enumerate(pipes[s]):
                prof[f"{s}_pipe{k+1}_start_mm"] = round(p0, 3); prof[f"{s}_pipe{k+1}_end_mm"] = round(p1, 3)
        profiles.append(prof)
        if i % 200 == 0:
            print(f"{i}/{a.n}")
    pd.DataFrame(manifest).to_csv(os.path.join(a.out, "manifest.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame(profiles).to_csv(os.path.join(a.out, "rail_profiles.csv"), index=False)
    print("done", a.out)


if __name__ == "__main__":
    main()
