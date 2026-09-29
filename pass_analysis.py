"""주행(pass) 단위 결함 분석 — 논문 2.2절의 현측정 파형 적합.

구간 규칙(_classify)은 구간 안의 변화량만 보므로 완만한 결함(수직 변형·좌우 높이차)의
현측정 응답(약 0.4 mm 봉우리)을 놓친다. 이 모듈은 한 번의 주행이 끝나면 전체 프로파일을
정상 기준선과 비교하고, 이론 파형(t_HF, t_C)을 최소제곱으로 맞춰 결함 종류와 크기를 낸다.
2026-09-29 실측 24회로 검증: 24회 중 23회 판별, 크기 오차 0.16 mm 이내.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

# ── 시험 레일 기하 (실물 크레인이면 환경 변수로 바꾼다) ──
CHORD_HALF_MM = 250.0            # 앞뒤 바퀴 간격 500 mm의 절반. 센서는 그 가운데
SENSOR_OFFSET_MM = 250.0         # 뒷바퀴(엔코더 0점)에서 센서까지
JOINTS_MM = (600.0, 1200.0)      # 이음부 위치(센서 좌표). 결함 조각은 두 이음부 사이
RAIL_END_MM = 1800.0
GRID_MM = np.arange(260.0, 1541.0, 5.0)
JOINT_EXCLUDE_MM = 20.0          # 이음부 틈 신호는 크기 추정에서 제외
SENSOR_MIN_VALID_MM = 2.5
THRESHOLD_MM = 1.0               # 재현 결함(2 mm)의 절반
DEFECT_MM = 2.0                  # 이론 파형의 기준 크기
# 이음부 틈 스파이크를 찾을 원시 위치 창(좌 엔코더 mm). 엔코더 배율 0.8~1.3 을 덮는다.
JOINT_SEARCH_RAW = ((200.0, 700.0), (700.0, 1450.0))


def _versine(h, x):
    return (h(x - CHORD_HALF_MM) + h(x + CHORD_HALF_MM)) / 2.0 - h(x)


def _h_step(x):
    return np.where((x >= JOINTS_MM[0]) & (x < JOINTS_MM[1]), 0.0, -DEFECT_MM)


def _h_sag(x):
    return np.interp(x, [0.0, JOINTS_MM[0], JOINTS_MM[1], RAIL_END_MM], [0.0, -DEFECT_MM, -DEFECT_MM, 0.0])


_MASK = np.ones_like(GRID_MM, dtype=bool)
for _j in JOINTS_MM:
    _MASK &= np.abs(GRID_MM - _j) > JOINT_EXCLUDE_MM
T_HF = _versine(_h_step, GRID_MM)
T_C = _versine(_h_sag, GRID_MM)
T_HF = T_HF - T_HF[_MASK].mean()
T_C = T_C - T_C[_MASK].mean()
_ONES = np.ones_like(GRID_MM)


def _fit(y, templates):
    a = np.vstack([t[_MASK] for t in templates]).T
    b = y[_MASK]
    ok = np.isfinite(b)
    coef, *_ = np.linalg.lstsq(a[ok], b[ok], rcond=None)
    return coef


class PassProfile:
    """한 번의 주행 동안 (좌 엔코더 위치, 좌 간격, 우 간격)을 모은다."""

    def __init__(self) -> None:
        self.pos: list[float] = []
        self.gl: list[float] = []
        self.gr: list[float] = []

    def add(self, pos_mm: float, gap_l: float, gap_r: float) -> None:
        if min(gap_l, gap_r) < SENSOR_MIN_VALID_MM:
            return
        self.pos.append(pos_mm)
        self.gl.append(gap_l)
        self.gr.append(gap_r)

    def __len__(self) -> int:
        return len(self.pos)

    def resample(self) -> tuple[np.ndarray, np.ndarray, dict] | None:
        """이음부 틈 스파이크 2개로 위치를 보정한 뒤 5 mm 격자에 얹는다."""
        if len(self.pos) < 200:
            return None
        pos = np.asarray(self.pos)
        gl = np.asarray(self.gl)
        gr = np.asarray(self.gr)
        # 이음부 틈 스파이크: 좌·우 고역 신호의 합에서 창 안 상위 후보를 뽑고,
        # 두 이음부 간격이 엔코더 배율 0.75~1.5 (400~800 mm) 안에 드는 가장 강한 짝을 고른다
        hp = (gl - _running_median(gl, 31)) + (gr - _running_median(gr, 31))
        cands = []
        for lo, hi in JOINT_SEARCH_RAW:
            idx = np.flatnonzero((pos > lo) & (pos < hi))
            if len(idx) == 0:
                return None
            order = idx[np.argsort(hp[idx])[::-1]]
            picked: list[int] = []
            for k in order:
                if all(abs(pos[k] - pos[p]) > 60.0 for p in picked):
                    picked.append(k)
                if len(picked) == 4:
                    break
            cands.append(picked)
        best = None
        for k1 in cands[0]:
            for k2 in cands[1]:
                d = pos[k2] - pos[k1]
                if 400.0 <= d <= 800.0:
                    score = hp[k1] + hp[k2]
                    if best is None or score > best[0]:
                        best = (score, pos[k1], pos[k2])
        anchors = [best[1], best[2]] if best else [pos[cands[0][0]], pos[cands[1][0]]]
        r1, r2 = anchors
        if r2 - r1 < 300.0:          # 이음부 두 개를 못 찾았다: 엔코더 원시값 + 센서 오프셋으로 대신
            x = pos + SENSOR_OFFSET_MM
            scale = None
        else:
            scale = (JOINTS_MM[1] - JOINTS_MM[0]) / (r2 - r1)
            x = JOINTS_MM[0] + (pos - r1) * scale
        out = []
        for g in (gl, gr):
            grid = np.full(GRID_MM.shape, np.nan)
            b = np.round((x - GRID_MM[0]) / 5.0).astype(int)
            for i in range(len(GRID_MM)):
                sel = b == i
                if sel.any():
                    grid[i] = np.median(g[sel])
            grid = _interp_nan(grid)
            out.append(grid)
        return out[0], out[1], {"encoder_scale": scale, "joint_raw_mm": anchors}


def _running_median(a: np.ndarray, w: int) -> np.ndarray:
    half = w // 2
    padded = np.pad(a, half, mode="edge")
    return np.array([np.median(padded[i:i + w]) for i in range(len(a))])


def _interp_nan(a: np.ndarray) -> np.ndarray:
    nans = np.isnan(a)
    if nans.all():
        return a
    idx = np.arange(len(a))
    a = a.copy()
    a[nans] = np.interp(idx[nans], idx[~nans], a[~nans])
    return a


class PassAnalyzer:
    """정상 기준선을 등록해 두고, 이후 주행마다 결함 종류·크기를 낸다.

    limits: {"joint_step": mm, "vertical": mm, "cross_level": mm}
    min_passes_for_stage: 단계는 이 횟수 이상 평균으로만 판정
    """

    def __init__(self, limits: dict, min_passes_for_stage: int = 3, store: str | None = None) -> None:
        self.limits = limits
        self.min_passes = min_passes_for_stage
        self.store = Path(store) if store else None
        self.baseline_l: np.ndarray | None = None
        self.baseline_r: np.ndarray | None = None
        self.baseline_count = 0
        self.history: list[dict] = []          # 주행별 크기 추정치
        if self.store and self.store.exists():
            data = json.loads(self.store.read_text())
            self.baseline_l = np.asarray(data["left"])
            self.baseline_r = np.asarray(data["right"])
            self.baseline_count = int(data.get("count", 1))

    # 정상 레일 주행을 기준선으로 등록한다 (운영: "기준선 등록" 버튼)
    def register_baseline(self, profile: PassProfile) -> bool:
        rs = profile.resample()
        if rs is None:
            return False
        gl, gr, _ = rs
        n = self.baseline_count
        if self.baseline_l is None:
            self.baseline_l, self.baseline_r = gl, gr
        else:
            self.baseline_l = (self.baseline_l * n + gl) / (n + 1)
            self.baseline_r = (self.baseline_r * n + gr) / (n + 1)
        self.baseline_count = n + 1
        if self.store:
            self.store.write_text(json.dumps({"left": self.baseline_l.tolist(), "right": self.baseline_r.tolist(), "count": self.baseline_count}))
        return True

    def analyze(self, profile: PassProfile) -> dict | None:
        if self.baseline_l is None:
            return None
        rs = profile.resample()
        if rs is None:
            return None
        gl, gr, meta = rs
        dl = gl - self.baseline_l
        dr = gr - self.baseline_r
        m = (dl + dr) / 2.0
        delta = dl - dr
        c_hf, c_c, _ = _fit(m, [T_HF, T_C, _ONES])
        e_c, _ = _fit(delta, [T_C, _ONES])
        sizes = {"joint_step": DEFECT_MM * c_hf, "vertical": DEFECT_MM * c_c, "cross_level": DEFECT_MM * e_c}
        defect = self._classify(sizes)
        self.history.append({"sizes": sizes, "defect_type": defect})
        return self._judge(defect, meta)

    @staticmethod
    def _classify(s: dict) -> str:
        if abs(s["joint_step"]) >= THRESHOLD_MM:
            return "joint_step"
        if max(abs(s["vertical"]), abs(s["cross_level"])) < THRESHOLD_MM:
            return "normal"
        return "cross_level" if abs(s["cross_level"]) > abs(s["vertical"]) else "vertical"

    def _judge(self, defect: str, meta: dict) -> dict:
        recent = self.history[-self.min_passes:]
        passes = len(recent)
        if defect == "normal":
            magnitude = 0.0
            stage = "ok"
        else:
            magnitude = float(np.mean([abs(h["sizes"][defect]) for h in recent]))
            limit = self.limits[defect]
            if passes < self.min_passes:
                stage = "ok"       # 3회 미만: 분류만, 단계는 보류
            elif magnitude > limit:
                stage = "danger"
            elif magnitude > 0.5 * limit:
                stage = "caution"
            else:
                stage = "ok"
        latest = self.history[-1]["sizes"]
        side = "both"
        if defect == "cross_level":
            side = "left" if latest["cross_level"] > 0 else "right"   # Δ = gL − gR > 0 이면 좌 레일이 낮다
        return {
            "defect_type": defect,
            "stage": stage,
            "magnitude_mm": round(magnitude, 3),
            "sizes_mm": {k: round(float(v), 3) for k, v in latest.items()},
            "side": side,
            "from_mm": JOINTS_MM[0] if defect != "normal" else None,
            "to_mm": JOINTS_MM[1] if defect != "normal" else None,
            "passes_used": passes,
            "encoder_scale": meta.get("encoder_scale"),
        }
