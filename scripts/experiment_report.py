"""주행 실험 결과를 판정 엔진 v1 · v2 · v2+AI 로 재생해 보고서(md)를 만든다.

사용법 (저장소 루트에서):
    python scripts/experiment_report.py <실험 폴더> [--baseline 3] [--out 보고서.md]

실험 폴더 구성 (서버 /runs 에서 받은 CSV 를 나눠 넣는다):
    <실험 폴더>/1. 정상/*.csv   정상 레일 주행. 회차 순으로 앞 --baseline 회는 기준선, 나머지는 오경보 확인
    <실험 폴더>/2. 단차/*.csv   이음부 단차 주행
    (3. 상하침하, 4. 좌우 높이차 폴더가 있으면 같이 재생한다)

판정 방식은 서버 설정(RAIL_JUDGE, RAIL_AI)을 바꿔 가며 같은 CSV 를 따로 재생한다. 서버도 운영 기준선 파일도 건드리지 않는다.
v2+AI 는 지금 들어 있는 rail_ai_weights.npz(9/28 정상 주행으로 적응)를 쓰므로, 펌웨어가 바뀐 뒤 결과는 참고용이다.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODES = [
    ("v1", {"RAIL_JUDGE": "v1", "RAIL_AI": "0"}),
    ("v2", {"RAIL_JUDGE": "v2", "RAIL_AI": "0"}),
    ("v2 + AI", {"RAIL_JUDGE": "v2", "RAIL_AI": "1"}),
]
FOLDERS = {"1. 정상": "normal", "2. 단차": "joint_step", "3. 상하침하": "vertical", "4. 좌우 높이차": "cross_level"}
LABEL = {"normal": "정상", "joint_step": "이음부 단차", "vertical": "수직 변형", "cross_level": "좌우 높이차",
         "sensor_check": "센서 점검", None: "결과 없음"}
STAGE = {"ok": "정상", "caution": "주의", "danger": "위험", None: "-"}


def _files(root: Path, folder: str) -> list[str]:
    import replay_csv
    if not (root / folder).is_dir():
        return []
    number = {v: k for k, v in replay_csv.CFG.items()}
    cfg = replay_csv.CFG[folder]
    assert number[cfg] == folder
    return replay_csv.files_for(str(root), cfg)


def _replay(root: Path, n_baseline: int) -> dict:
    """현재 프로세스의 RAIL_JUDGE/RAIL_AI 로 재생한다(자식 프로세스에서 불린다)."""
    import rail_defect
    import replay_csv

    engine = rail_defect.DefectRuleEngine(segment_count=36, rail_length_cm=180.0, baseline_file=None)
    normal = _files(root, "1. 정상")
    base, check = normal[:n_baseline], normal[n_baseline:]
    engine.baseline_mode = True
    for path in base:
        replay_csv.feed(engine, path)
    engine.baseline_mode = False
    out = {"baseline_runs": [Path(p).name for p in base], "baseline_count": engine.pass_analyzer.baseline_count,
           "judge": engine.judge_info(), "groups": {}}
    groups = [("1. 정상", check)] + [(f, _files(root, f)) for f in FOLDERS if f != "1. 정상"]
    for folder, paths in groups:
        if not paths:
            continue
        engine.pass_analyzer.history.clear()   # 구성마다 3회 평균을 새로 시작
        rows = []
        for path in paths:
            r = replay_csv.feed(engine, path) or {}
            rows.append({
                "file": Path(path).name,
                "type": r.get("defect_type"),
                "stage": r.get("stage"),
                "mag": r.get("magnitude_mm"),
                "from": r.get("from_mm"), "to": r.get("to_mm"), "side": r.get("side"),
                "sizes": r.get("sizes_mm"), "ai": r.get("ai_sizes_mm"), "spread": r.get("ai_spread_mm"),
                "low_conf": r.get("low_confidence"), "rebase": r.get("rebaseline_recommended"),
                "defects": [(d.get("defect_type"), d.get("stage"), d.get("from_mm"), d.get("to_mm"), d.get("side"))
                            for d in (r.get("defects") or [])],
            })
        risk = {s: engine._risk_array(s) for s in ("left", "right")}
        out["groups"][folder] = {"rows": rows, "risk": risk}
    return out


def _hardware(root: Path) -> list[dict]:
    """주행마다 좌·우 엔코더 차, 이음부로 본 엔코더 배율과 출발 시 센서 위치."""
    import pass_analysis
    import replay_csv
    out = []
    for folder in FOLDERS:
        for path in _files(root, folder):
            rows = replay_csv.load_rows(path)
            prof = pass_analysis.PassProfile()
            last_l = last_r = None
            for row in rows:
                l, r = replay_csv.sample_side(row, "left"), replay_csv.sample_side(row, "right")
                if l["position_mm"] is not None:
                    last_l = l["position_mm"]
                if r["position_mm"] is not None:
                    last_r = r["position_mm"]
                if None in (l["position_mm"], l["sensor_distance_mm"], r["sensor_distance_mm"]):
                    continue
                prof.add(l["position_mm"], l["sensor_distance_mm"], r["sensor_distance_mm"])
            res = prof.resample()
            meta = res[2] if res else {}
            scale = meta.get("encoder_scale")
            joints = meta.get("joint_raw_mm") or []
            start = (600.0 - joints[0] * scale) if (scale and joints) else None
            diff = None
            if last_l and last_r and abs(last_l) > 1:
                diff = (last_r - last_l) / abs(last_l) * 100.0
            out.append({"folder": folder, "file": Path(path).name, "samples": len(rows),
                        "left_mm": last_l, "right_mm": last_r, "lr_diff_pct": diff,
                        "scale": scale, "sensor_start_mm": start})
    return out


def _fmt(v, nd=2, unit=""):
    return "-" if v is None else f"{v:.{nd}f}{unit}"


def _span(arr: list[float], seg_mm: float = 50.0) -> str:
    idx = [i for i, v in enumerate(arr) if v > 0]
    if not idx:
        return "없음"
    return f"{idx[0] * seg_mm / 10:.0f}~{(idx[-1] + 1) * seg_mm / 10:.0f} cm"


def report(root: Path, n_baseline: int) -> str:
    lines = [f"# 주행 실험 재생 보고서 — {root.name}", ""]
    counts = {f: len(_files(root, f)) for f in FOLDERS}
    lines.append("주행 수: " + ", ".join(f"{f} {n}회" for f, n in counts.items() if n))
    lines.append(f"기준선: 정상 앞 {n_baseline}회. 같은 CSV 를 판정 방식만 바꿔 재생했다. 서버·운영 기준선과 무관하다.")
    lines.append("")

    results = {}
    for name, env in MODES:
        proc = subprocess.run([sys.executable, __file__, str(root), "--baseline", str(n_baseline), "--child"],
                              env={**os.environ, **env, "RAIL_BASELINE_FILE": os.devnull},
                              capture_output=True, text=True, cwd=ROOT)
        if proc.returncode != 0:
            lines += [f"## {name}: 재생 실패", "```", proc.stderr[-2000:], "```", ""]
            continue
        results[name] = json.loads(proc.stdout.strip().splitlines()[-1])

    # 요약표
    lines += ["## 요약", "", "| 구성 | 정답 | " + " | ".join(results) + " |", "|---|---|" + "---|" * len(results)]
    groups = []
    for res in results.values():
        for g in res["groups"]:
            if g not in groups:
                groups.append(g)
    for g in groups:
        truth = FOLDERS[g]
        cells = []
        for res in results.values():
            rows = res["groups"].get(g, {}).get("rows", [])
            hit = sum((r["type"] == truth) or (truth == "normal" and r["type"] in (None, "normal")) for r in rows)
            last = rows[-1] if rows else {}
            cells.append(f"{hit}/{len(rows)} · 마지막 {LABEL.get(last.get('type'))} {STAGE.get(last.get('stage'))}")
        title = "1. 정상 (기준선 뒤)" if g == "1. 정상" else g
        lines.append(f"| {title} | {LABEL[truth]} | " + " | ".join(cells) + " |")
    lines += ["", "정답 기준: 2 mm 단차는 이음부 단차 · 위험(한계선 1.0 mm 초과)이 나와야 한다. 단계는 같은 구성 3회째부터 나온다.", ""]

    # 방식별 상세
    for name, res in results.items():
        j = res["judge"]
        lines += [f"## {name}", "",
                  f"판정 설정: version={j['version']}, ai={j['ai']}({j['ai_models']}개), motion_from_pass={j['motion_from_pass']} · 기준선 {res['baseline_count']}회", ""]
        for g, data in res["groups"].items():
            lines += [f"### {g}", "", "| 회차 | 종류 | 단계 | 크기 mm | 구간 mm | 쪽 | AI 크기 (±) | 표시 |", "|---|---|---|---|---|---|---|---|"]
            for i, r in enumerate(data["rows"], 1):
                ai = r["ai"] or {}
                sp = r["spread"] or {}
                key = r["type"] if r["type"] in ("joint_step", "vertical") else None
                ai_txt = f"{ai[key]:.2f} (±{sp.get(key, 0):.2f})" if key and key in ai else "-"
                flags = " ".join(x for x in ("신뢰 낮음" if r["low_conf"] else "", "기준선 재등록 권고" if r["rebase"] else "") if x)
                extra = ""
                if len(r["defects"]) > 1:
                    extra = " · 함께: " + ", ".join(f"{LABEL.get(t)} {STAGE.get(s)} {side}" for t, s, _, _, side in r["defects"][1:])
                rng = f"{_fmt(r['from'], 0)}–{_fmt(r['to'], 0)}" if r["from"] is not None else "-"
                lines.append(f"| {i} | {LABEL.get(r['type'])} | {STAGE.get(r['stage'])} | {_fmt(r['mag'])} | {rng} | {r['side'] or '-'} | {ai_txt} | {flags}{extra} |")
            lines.append(f"\n대시보드에 칠해질 구간: 좌 {_span(data['risk']['left'])} · 우 {_span(data['risk']['right'])}\n")

    # 하드웨어 지표
    hw = _hardware(root)
    lines += ["## 하드웨어 지표 (주행마다)", "",
              "좌·우 엔코더 차 = (우 − 좌) / 좌, 주행 끝 기준. 배율·출발 센서 위치는 이음부 틈(600·1200 mm)으로 역산했다.", "",
              "| 구성 | 회차 파일 | 샘플 | 좌 mm | 우 mm | 좌·우 차 | 엔코더 배율 | 출발 시 센서 위치 |", "|---|---|---|---|---|---|---|---|"]
    for h in hw:
        lines.append(f"| {h['folder']} | {h['file'][:40]} | {h['samples']} | {_fmt(h['left_mm'], 0)} | {_fmt(h['right_mm'], 0)} | "
                     f"{_fmt(h['lr_diff_pct'], 1, ' %')} | {_fmt(h['scale'], 3)} | {_fmt(h['sensor_start_mm'], 0, ' mm')} |")
    diffs = [abs(h["lr_diff_pct"]) for h in hw if h["lr_diff_pct"] is not None]
    scales = [h["scale"] for h in hw if h["scale"]]
    starts = [h["sensor_start_mm"] for h in hw if h["sensor_start_mm"] is not None]
    lines.append("")
    if diffs:
        lines.append(f"- 좌·우 엔코더 차 |%|: 중앙값 {statistics.median(diffs):.1f} %, 최대 {max(diffs):.1f} % (9/28 동기화 전: 최대 29 %)")
    if scales:
        lines.append(f"- 엔코더 배율: 중앙값 {statistics.median(scales):.3f}, 범위 {min(scales):.3f}~{max(scales):.3f} (9/28: 0.84~0.99, 중앙값 약 0.89)")
    if starts:
        med = statistics.median(starts)
        lines.append(f"- 출발 시 센서 위치: 중앙값 {med:.0f} mm, 범위 {min(starts):.0f}~{max(starts):.0f} → RAIL_ENCODER_ZERO_MM ≈ {med - 250:.0f} (지금 기본 40)")
    missing = [h["file"] for h in hw if h["scale"] is None]
    if missing:
        lines.append(f"- 이음부 틈을 못 찾은 주행 {len(missing)}회: " + ", ".join(m[:30] for m in missing))
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="실험 폴더 (1. 정상, 2. 단차 ... 하위 폴더)")
    ap.add_argument("--baseline", type=int, default=3, help="정상 주행 중 기준선으로 쓸 앞 회차 수 (기본 3)")
    ap.add_argument("--out", help="보고서 md 경로 (기본: <실험 폴더>/재생_보고서.md)")
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if args.child:
        print(json.dumps(_replay(root, args.baseline), ensure_ascii=False))
        return
    if len(_files(root, "1. 정상")) < args.baseline:
        sys.exit(f"'1. 정상' 폴더의 CSV 가 기준선 {args.baseline}회보다 적다")
    text = report(root, args.baseline)
    out = Path(args.out) if args.out else root / "재생_보고서.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n보고서 저장: {out}")


if __name__ == "__main__":
    main()
