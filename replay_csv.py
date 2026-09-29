"""사용법: python replay_csv.py <레일측정데이터 폴더>

서버를 켜지 않고 실측 CSV를 판정 엔진에 넣어, 웹에 뜰 결과를 출력한다.
'1. 정상' 폴더의 6회를 기준선으로 등록한 뒤, 나머지 구성을 6회씩 재생한다.
"""
from __future__ import annotations

import csv
import glob
import os
import re
import sys
import unicodedata
from datetime import datetime

import rail_defect

CFG = {"1. 정상": 1, "2. 단차": 2, "3. 상하침하": 3, "4. 좌우 높이차": 4}
TRUTH = {1: "normal", 2: "joint_step", 3: "vertical", 4: "cross_level"}
def files_for(root: str, cfg: int) -> list[str]:
    folder = [name for name, number in CFG.items() if number == cfg][0]
    paths = glob.glob(os.path.join(root, folder, "*.csv"))
    def run_number(path: str) -> int:
        name = unicodedata.normalize("NFC", os.path.basename(path))
        match = re.search(r"(\d+)차", name)
        if match is None:
            raise ValueError(f"회차 번호를 찾지 못했습니다: {name}")
        return int(match.group(1))
    return sorted(paths, key=run_number)


def _num(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def load_rows(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if "12차" in unicodedata.normalize("NFC", os.path.basename(path)):
        # 출발 직후 멈췄다 재출발한 파일: 재출발부터
        start = datetime.fromisoformat(rows[0]["time"])
        kept = []
        for row in rows:
            elapsed = (datetime.fromisoformat(row["time"]) - start).total_seconds()
            if elapsed > 26.6:
                kept.append(row)
        origin_l = _num(kept[0]["left_position_mm"]) or 0.0
        origin_r = _num(kept[0]["right_position_mm"]) or 0.0
        for row in kept:
            row["left_position_mm"] = str((_num(row["left_position_mm"]) or 0.0) - origin_l)
            row["right_position_mm"] = str((_num(row["right_position_mm"]) or 0.0) - origin_r)
        rows = kept
    return rows


def sample_side(row: dict, side: str) -> dict:
    uptime = _num(row.get("uptime_us"))
    return {
        "position_mm": _num(row.get(f"{side}_position_mm")),
        "sensor_distance_mm": _num(row.get(f"{side}_sensor_distance_mm")),
        "accel_x": _num(row.get(f"{side}_mpu_accel_x")),
        "accel_y": _num(row.get(f"{side}_mpu_accel_y")),
        "accel_z": _num(row.get(f"{side}_mpu_accel_z")),
        "gyro_y": _num(row.get(f"{side}_mpu_gyro_y")),
        "_received_at": (uptime / 1e6) if uptime is not None else None,
    }


def feed(engine: rail_defect.DefectRuleEngine, path: str) -> dict | None:
    for row in load_rows(path):
        engine.evaluate_pair(sample_side(row, "left"), sample_side(row, "right"))
    return engine.finish_pass()


def clear_baseline_file() -> None:
    path = os.getenv("RAIL_BASELINE_FILE", "rail_baseline.json")
    if os.path.exists(path):
        os.remove(path)


def run(root: str) -> int:
    clear_baseline_file()
    engine = rail_defect.DefectRuleEngine(segment_count=20, rail_length_cm=180.0)
    engine.baseline_mode = True
    for path in files_for(root, 1):
        feed(engine, path)
    engine.baseline_mode = False
    print("기준선 등록:", engine.pass_analyzer.baseline_count, "회\n")
    ok = tot = 0
    for cfg in (2, 3, 4):
        print(f"[{rail_defect.DEFECT_LABELS[TRUTH[cfg]]} 구성] 6회 재생")
        engine.pass_analyzer.history.clear()
        for index, path in enumerate(files_for(root, cfg), 1):
            result = feed(engine, path)
            tot += 1
            if result is None:
                print(f"  {index}회: 결과 없음")
                continue
            ok += result["defect_type"] == TRUTH[cfg]
            print(
                f"  {index}회: {rail_defect.DEFECT_LABELS[result['defect_type']]:7s} "
                f"단계={result['stage']:8s} 크기={result['magnitude_mm']:.2f} mm "
                f"쪽={result['side']} 구간={result['from_mm']}-{result['to_mm']} mm"
            )
        print("  웹 위험도(좌):", [round(v, 1) for v in engine._risk_array("left")])
        print("  웹 위험도(우):", [round(v, 1) for v in engine._risk_array("right")], "\n")
    print(f"판별 정답 {ok}/{tot} (정상 구성은 기준선으로 사용)")
    return ok


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "레일측정데이터"
    raise SystemExit(0 if run(folder) == 18 else 1)
