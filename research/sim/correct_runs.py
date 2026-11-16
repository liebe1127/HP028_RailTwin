"""주행 CSV 에 위치 보정 열을 붙인다. 규칙은 배준호_전달/레일측정데이터/보정/README.txt 와 같다.

사용
  python3 correct_runs.py <주행 CSV 또는 폴더 ...> --out <출력 폴더>
  python3 correct_runs.py "../../배준호_전달/레일측정데이터" --out ../data_check --compare "../../배준호_전달/레일측정데이터/보정"

입력  서버 /runs/{boot_id}.csv 로 받은 주행 CSV (9/28 원본과 같은 열). 폴더를 주면 그 안의 csv 를 전부(하위 폴더 포함) 읽는다.
      이미 보정 열이 붙은 파일을 주면 그 열은 버리고 다시 계산한다.
출력  원본 열은 그대로 두고 아래 7개 열을 덧붙인 사본 <원본이름>_보정.csv 와 보정_기록.csv
      rail_x_mm            센서 위치 (mm). 이음부 틈이 600, 1200 mm 에 오도록 좌 엔코더를 선형 변환
      rear_wheel_x_mm      뒷바퀴 위치 = rail_x_mm - 250
      encoder_scale_left   600 / (이음부 사이 좌 엔코더 값)
      encoder_scale_right  같은 두 행에서 구한 우 엔코더 배율 (참고용)
      sensor_valid         좌·우 센서 값이 모두 2.5 mm 를 넘으면 1
      analysis_window      분석에 쓰는 구간이면 1. 엔코더가 0 으로 되돌아간(충격 정지 후 재출발) 회차는 재출발 뒤
                           이전에 갔던 위치를 넘어선 행부터 1, 그 앞은 0 (rail_x_mm 은 빈칸)
      joint_marker         이음부 틈 스파이크로 잡은 행에 600 또는 1200, 나머지 0

보정  rail_x = 600 + (left_position_mm - E1) * 600 / (E2 - E1)
      E1, E2 = 좌·우 센서 거리의 짧은 양의 스파이크(틈 3 mm) 두 개가 가장 큰 행의 좌 엔코더 값.
      스파이크는 센서 거리에서 이동 중앙값(41 표본)을 뺀 값이 0.25 mm 를 넘는 묶음으로 찾고, 묶음 안에서
      센서 거리가 가장 큰 행을 이음부 행으로 삼는다. 두 묶음은 엔코더로 480~760 mm 떨어져야 한다(배율 0.8~1.25).
실패  이음부 두 개를 못 찾거나 좌 배율이 0.8~1.2 밖이면 그 회차는 출력하지 않고 보정_기록.csv 에 실패로 적는다.
확인  --compare <기존 보정본 폴더> 를 주면 boot_id 가 같은 기존 보정본과 rail_x_mm 차이의 최대값을 회차별·전체로 찍는다.
      9/28 원본 24회에서 전체 최대 차이 1.5 mm (14차 이음부 1 이 한 행 옆, 나머지 23회는 0.0 mm). 37차 공회전은 실패로 걸러진다.
"""
import argparse, glob, itertools, os, re, sys, unicodedata
import numpy as np
import pandas as pd

JOINTS = (600.0, 1200.0)
APPENDED = ["rail_x_mm", "rear_wheel_x_mm", "encoder_scale_left", "encoder_scale_right", "sensor_valid", "analysis_window", "joint_marker"]
NEEDED = ["left_position_mm", "right_position_mm", "left_sensor_distance_mm", "right_sensor_distance_mm"]
RECORD_COLS = ["구성", "회차", "파일", "분석시작행", "이음부1_행", "이음부1_좌엔코더mm", "이음부2_행", "이음부2_좌엔코더mm",
               "좌엔코더_600mm구간_측정값", "좌_배율", "좌_오차퍼센트", "우엔코더_600mm구간_측정값", "우_배율", "우_오차퍼센트", "상태", "비고"]
SCALE_OK = (0.8, 1.2)        # 좌 배율 허용 범위
SEP_OK = (480.0, 760.0)      # 이음부 사이 엔코더 값 허용 범위 (600 mm / 배율 0.8~1.25)


def analysis_start(lp):
    """엔코더가 0 으로 되돌아간(재출발) 회차: 마지막 되돌아간 뒤, 그 전에 갔던 최대 위치를 넘어선 행. 없으면 0."""
    prev = np.concatenate([[np.nan], lp[:-1]])
    drops = np.where((prev > 10.0) & (lp <= 1.0))[0]          # 엔코더가 0 으로 되돌아간 행
    if len(drops) == 0:
        return 0, ""
    r = int(drops[-1]); pre_max = float(np.nanmax(lp[:r]))
    after = np.where(lp[r:] > pre_max)[0]
    if len(after) == 0:
        return r, f"엔코더 재출발 {len(drops)}회, 재출발 뒤 이전 위치 {pre_max:.0f} mm 를 넘지 못해 재출발 행부터"
    return r + int(after[0]), f"엔코더 재출발 {len(drops)}회, 이전 위치 {pre_max:.0f} mm 를 넘어선 행부터"


def find_joints(lp, L, R, start, win=41, thr=0.25, gap_mm=40.0):
    """이음부 틈 스파이크 두 개의 행을 찾는다. (행1, 행2, 설명) 또는 None."""
    valid = np.zeros(len(lp), bool); valid[start:] = True
    valid &= (L > 2.5) & (R > 2.5) & np.isfinite(lp)
    dev = {}
    for name, g in (("L", L), ("R", R)):
        med = pd.Series(g).rolling(win, center=True, min_periods=5).median().to_numpy()
        dev[name] = np.where(valid, g - med, -np.inf)
    dmax = np.maximum(dev["L"], dev["R"])
    idx = np.where(dmax > thr)[0]
    if len(idx) == 0:
        return None
    groups = [[idx[0]]]
    for i in idx[1:]:
        if lp[i] - lp[groups[-1][-1]] < gap_mm:
            groups[-1].append(i)
        else:
            groups.append([i])
    clusters = []
    for c in groups:
        c = np.array(c)
        side = "L" if dev["L"][c].max() >= dev["R"][c].max() else "R"
        g = L if side == "L" else R
        j = int(c[np.argmax(g[c])])
        clusters.append((j, float(dmax[c].max()), side, float(lp[j])))
    best = None
    for a, b in itertools.combinations(clusters, 2):
        sep = b[3] - a[3]
        if SEP_OK[0] <= sep <= SEP_OK[1]:
            sc = a[1] + b[1]
            if best is None or sc > best[0]:
                best = (sc, a, b)
    if best is None:
        return None
    a, b = best[1], best[2]
    return a[0], b[0], f"스파이크 {a[2]} {a[1]:.2f} mm / {b[2]} {b[1]:.2f} mm"


def correct_one(d):
    """보정 열을 붙인 DataFrame 과 기록 dict 를 돌려준다. 실패하면 (None, 기록)."""
    d = d.drop(columns=[c for c in APPENDED if c in d.columns])
    lp = d["left_position_mm"].to_numpy(float); rp = d["right_position_mm"].to_numpy(float)
    L = d["left_sensor_distance_mm"].to_numpy(float); R = d["right_sensor_distance_mm"].to_numpy(float)
    rec = {"분석시작행": 0}
    start, note = analysis_start(lp)
    rec["분석시작행"] = start
    found = find_joints(lp, L, R, start)
    if found is None:
        rec.update({"상태": "실패", "비고": "이음부 스파이크 두 개를 못 찾음" + (f"; {note}" if note else "")})
        return None, rec
    j1, j2, how = found
    E1, E2 = float(lp[j1]), float(lp[j2])
    span_l = E2 - E1; scale_l = 600.0 / span_l
    span_r = float(rp[j2] - rp[j1]); scale_r = 600.0 / span_r if span_r > 1e-6 else np.nan
    rec.update({"이음부1_행": j1, "이음부1_좌엔코더mm": round(E1, 1), "이음부2_행": j2, "이음부2_좌엔코더mm": round(E2, 1),
                "좌엔코더_600mm구간_측정값": round(span_l, 1), "좌_배율": round(scale_l, 4), "좌_오차퍼센트": round(span_l / 600.0 * 100 - 100, 1),
                "우엔코더_600mm구간_측정값": round(span_r, 1), "우_배율": round(scale_r, 4) if np.isfinite(scale_r) else "",
                "우_오차퍼센트": round(span_r / 600.0 * 100 - 100, 1)})
    if not (SCALE_OK[0] <= scale_l <= SCALE_OK[1]):
        rec.update({"상태": "실패", "비고": f"좌 배율 {scale_l:.4f} 이 {SCALE_OK[0]}~{SCALE_OK[1]} 밖" + (f"; {note}" if note else "")})
        return None, rec
    x = 600.0 + (lp - E1) * scale_l
    win = np.arange(len(d)) >= start
    x = np.where(win, x, np.nan)
    d["rail_x_mm"] = np.round(x, 1)
    d["rear_wheel_x_mm"] = np.round(x - 250.0, 1)
    d["encoder_scale_left"] = round(scale_l, 4)
    d["encoder_scale_right"] = round(scale_r, 4) if np.isfinite(scale_r) else np.nan
    d["sensor_valid"] = ((L > 2.5) & (R > 2.5)).astype(int)
    d["analysis_window"] = win.astype(int)
    jm = np.zeros(len(d), int); jm[j1] = 600; jm[j2] = 1200
    d["joint_marker"] = jm
    rec.update({"상태": "성공", "비고": how + (f"; {note}" if note else "")})
    return d, rec


def collect(inputs):
    files = []
    for p in inputs:
        if os.path.isdir(p):
            files += sorted(f for f in glob.glob(os.path.join(p, "**", "*.csv"), recursive=True)
                            if not os.path.basename(f).startswith("보정_기록"))
        elif os.path.isfile(p):
            files.append(p)
        else:
            print(f"없음: {p}")
    return files


def run_number(name, fallback):
    m = re.search(r"(\d+)\s*차", name)
    return int(m.group(1)) if m else fallback


def main():
    ap = argparse.ArgumentParser(description="주행 CSV 에 위치 보정 열을 붙인다 (README.txt 규칙)")
    ap.add_argument("inputs", nargs="+", help="주행 CSV 파일 또는 폴더")
    ap.add_argument("--out", required=True, help="출력 폴더")
    ap.add_argument("--compare", help="기존 보정본 폴더: boot_id 가 같은 파일과 rail_x_mm 차이를 찍는다")
    a = ap.parse_args()
    files = collect(a.inputs)
    if not files:
        sys.exit("입력 csv 가 없습니다")
    os.makedirs(a.out, exist_ok=True)
    records, outputs = [], []
    for k, f in enumerate(files, 1):
        name = unicodedata.normalize("NFC", os.path.basename(f)[:-4])
        parent = unicodedata.normalize("NFC", os.path.basename(os.path.dirname(f)))
        cfg = parent if any(os.path.isdir(p) and os.path.abspath(os.path.dirname(f)) != os.path.abspath(p) for p in a.inputs) else ""
        try:
            d = pd.read_csv(f, encoding="utf-8-sig")
        except Exception as e:
            records.append({"구성": cfg, "회차": run_number(name, k), "파일": name + ".csv", "상태": "실패", "비고": f"읽기 실패: {e}"}); continue
        missing = [c for c in NEEDED if c not in d.columns]
        if missing:
            records.append({"구성": cfg, "회차": run_number(name, k), "파일": name + ".csv", "상태": "실패", "비고": f"열 없음: {missing}"}); continue
        out_df, rec = correct_one(d)
        rec = {"구성": cfg, "회차": run_number(name, k), "파일": name + "_보정.csv", **rec}
        records.append(rec)
        if out_df is None:
            print(f"실패  {name}: {rec['비고']}"); continue
        op = os.path.join(a.out, name + "_보정.csv")
        out_df.to_csv(op, index=False, encoding="utf-8-sig")
        outputs.append((op, out_df))
        print(f"성공  {name}: 이음부 행 {rec['이음부1_행']}·{rec['이음부2_행']}, 좌 배율 {rec['좌_배율']}, 분석 시작 행 {rec['분석시작행']}")
    log = pd.DataFrame(records).reindex(columns=RECORD_COLS)
    for c in ("분석시작행", "이음부1_행", "이음부2_행"):
        log[c] = log[c].astype("Int64")
    log.to_csv(os.path.join(a.out, "보정_기록.csv"), index=False, encoding="utf-8-sig")
    n_ok = int((log["상태"] == "성공").sum())
    print(f"\n{n_ok}/{len(files)} 회차 보정 → {os.path.abspath(a.out)} (보정_기록.csv 포함)")

    if a.compare:
        olds = {}
        for f in glob.glob(os.path.join(a.compare, "**", "*.csv"), recursive=True):
            if os.path.basename(f).startswith("보정_기록"):
                continue
            try:
                od = pd.read_csv(f, encoding="utf-8-sig")
            except Exception:
                continue
            if "rail_x_mm" in od.columns and "boot_id" in od.columns and len(od):
                olds[str(od["boot_id"].iloc[0])] = (f, od)
        worst = 0.0; lines = []
        for op, nd in outputs:
            bid = str(nd["boot_id"].iloc[0]) if "boot_id" in nd.columns else None
            if bid not in olds:
                lines.append(f"  {os.path.basename(op)}: 비교할 기존 보정본 없음"); continue
            of, od = olds[bid]
            if len(od) != len(nd):
                lines.append(f"  {os.path.basename(op)}: 행 수가 다름 ({len(nd)} vs {len(od)})"); continue
            xn = nd["rail_x_mm"].to_numpy(float); xo = od["rail_x_mm"].to_numpy(float)
            both = np.isfinite(xn) & np.isfinite(xo); diff_win = int((np.isfinite(xn) != np.isfinite(xo)).sum())
            dmax = float(np.nanmax(np.abs(xn[both] - xo[both]))) if both.any() else np.nan
            worst = max(worst, dmax if np.isfinite(dmax) else 0.0)
            lines.append(f"  {os.path.basename(op)}: rail_x_mm 최대 차이 {dmax:.1f} mm, 분석 구간이 다른 행 {diff_win}개")
        print("\n기존 보정본과 비교:"); print("\n".join(lines))
        print(f"  전체 rail_x_mm 최대 차이 {worst:.1f} mm")


if __name__ == "__main__":
    main()
