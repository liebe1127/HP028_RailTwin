"""ISO 12488-1에서 잘라 낸 레일 기하 4분류 규칙.

분류: normal / joint_step(HF) / vertical(C, c) / cross_level(E)
구간 특징: m, delta, dm/dx, dΔ/dx, apeak, tilt_deg
단계: ok(한계 50% 이하) / caution / danger
긴급도: (한계선 - 현재값) / 변화 속도. 선형과 로그 중 더 짧은 쪽.
웨이블릿·파고율·RBF는 쓰지 않는다.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

RAIL_SIDES = ("left", "right")
DEFECT_TYPES = ("normal", "joint_step", "vertical", "cross_level")
STAGES = ("ok", "caution", "danger")
STAGE_SCORE = {"ok": 0.0, "caution": 0.6, "danger": 1.0}
DEFECT_LABELS = {
    "normal": "정상",
    "joint_step": "이음부 단차",
    "vertical": "수직 변형",
    "cross_level": "좌우 높이차",
}

G_MS2 = 9.80665

# 시연·초기 임계. 정상 왕복 실측 뒤 환경 변수로 덮어쓴다.
APEAK_LARGE = 3.0
APEAK_SMALL = 1.5
DM_DX_LARGE = 0.012
M_CHANGE_LARGE_MM = 0.5
DELTA_LARGE_MM = 0.8
DELTA_SMALL_MM = 0.25
TILT_MIN_DEG = 1.0
QUIET_SEGMENTS_TO_LOCK = 2
POSITION_MATCH_MM = 80.0
PAIR_MAX_AGE_S = 2.0
PASS_RESET_MM = 200.0
MIN_TREND_POINTS = 3
SINGLE_PASS_NOISE_MM = 0.24
MIN_PASSES_FOR_POINT1_MM = 6

# 한계선은 임시값이다. 운전 공차 표 7(Cw, Ew)과 이음부 표 6은 원문 확인 전이다.
LIMIT_MM = {
    "joint_step": 0.8,  # CMAA 계열 관행. ISO 12488-1 표 6 미확인
    "vertical": 2.0,  # ISO 12488-1:2012 표 2, 기호 c, 2급
    "cross_level": 10.0,  # ISO 12488-1:2012 표 2, 기호 E, 2급 상한
}
LIMIT_SOURCE = {
    "joint_step": "CMAA practice, ISO table 6 pending",
    "vertical": "ISO 12488-1:2012 table 2 symbol c class 2, operating Cw pending",
    "cross_level": "ISO 12488-1:2012 table 2 symbol E class 2 cap, operating Ew pending",
}


def estimate_roll_deg(
    accel_x: float | None,
    accel_y: float | None,
    accel_z: float | None,
) -> float | None:
    """중력 기준 롤. 자이로 각속도가 아니라 가속도 기울기 각도다."""
    if not isinstance(accel_x, (int, float)) or not isinstance(accel_z, (int, float)):
        return None
    if accel_x == 0.0 and accel_z == 0.0:
        return 0.0
    return math.degrees(math.atan2(float(accel_x), float(accel_z)))


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _linreg(xs: list[float], ys: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n < 2:
        y0 = ys[0] if ys else 0.0
        return 0.0, y0
    xmean = sum(xs) / n
    ymean = sum(ys) / n
    var = sum((x - xmean) ** 2 for x in xs)
    if var < 1e-9:
        return 0.0, ymean
    cov = sum((x - xmean) * (y - ymean) for x, y in zip(xs, ys))
    slope = cov / var
    return slope, ymean - slope * xmean


def stage_for(defect_type: str, magnitude_mm: float) -> str:
    if defect_type == "normal":
        return "ok"
    limit = LIMIT_MM[defect_type]
    if magnitude_mm > limit:
        return "danger"
    if magnitude_mm > 0.5 * limit:
        return "caution"
    return "ok"


def remaining_seconds(
    history: list[tuple[float, float]],
    limit_mm: float | None,
) -> tuple[float | None, float | None]:
    """선형과 로그 열화 중 더 빨리 한계에 닿는 남은 시간(초)과 선형 속도."""
    if limit_mm is None or len(history) < MIN_TREND_POINTS:
        return None, None
    if abs(history[-1][1] - history[0][1]) < SINGLE_PASS_NOISE_MM:
        return None, None
    t0 = history[0][0]
    xs = [item[0] - t0 for item in history]
    ys = [item[1] for item in history]
    slope, intercept = _linreg(xs, ys)
    now = xs[-1]
    current = ys[-1]
    candidates: list[float] = []
    if slope > 1e-9 and current < limit_mm:
        candidates.append((limit_mm - current) / slope)
    elif slope > 1e-9 and current >= limit_mm:
        candidates.append(0.0)
    if all(value > 0.05 for value in ys) and limit_mm > 0:
        log_slope, log_intercept = _linreg(xs, [math.log(value) for value in ys])
        if log_slope > 1e-9:
            remain = (math.log(limit_mm) - (log_intercept + log_slope * now)) / log_slope
            if remain >= 0:
                candidates.append(remain)
    if not candidates:
        return None, slope
    return min(candidates), slope


@dataclass
class SamplePoint:
    position_mm: float
    m_mm: float
    delta_mm: float
    apeak: float
    tilt_deg: float
    recorded_at: float


@dataclass
class SegmentRecord:
    defect_type: str = "normal"
    stage: str = "ok"
    magnitude_mm: float = 0.0
    m_mm: float | None = None
    delta_mm: float | None = None
    dm_dx: float | None = None
    ddelta_dx: float | None = None
    apeak: float | None = None
    tilt_deg: float | None = None
    history: list[tuple[float, float]] = field(default_factory=list)
    remaining_s: float | None = None
    rate_mm_per_s: float | None = None
    relative_fast: bool = False


class DefectRuleEngine:
    def __init__(
        self,
        *,
        segment_count: int = 20,
        rail_length_cm: float = 100.0,
    ) -> None:
        self.segment_count = max(int(segment_count), 1)
        self.rail_length_mm = max(float(rail_length_cm) * 10.0, 1.0)
        self.segment_mm = self.rail_length_mm / self.segment_count
        self.reset()

    def reset(self, side: str | None = None) -> None:
        if side in RAIL_SIDES:
            self.pending[side] = None
            return
        self.pending: dict[str, dict | None] = {side: None for side in RAIL_SIDES}
        self.segments = [SegmentRecord() for _ in range(self.segment_count)]
        self.open_index: int | None = None
        self.open_points: list[SamplePoint] = []
        self.baseline_m: float | None = None
        self.delta_offset: float = 0.0
        self.baseline_locked = False
        self.quiet_segments = 0
        self.previous_position_mm: float | None = None
        self.direction = 1
        self.pass_count = 1
        self.pass_started_at = time.time()

    def evaluate_side(self, sample: dict, side: str) -> dict:
        self.pending[side] = sample
        other = "right" if side == "left" else "left"
        mate = self.pending.get(other)
        if not isinstance(mate, dict):
            return self._not_ready()
        if not self._pair_is_fresh(sample, mate):
            return self._not_ready()
        left = sample if side == "left" else mate
        right = mate if side == "left" else sample
        return self.evaluate_pair(left, right)

    def evaluate_pair(self, left: dict, right: dict) -> dict:
        point = self._point_from_pair(left, right)
        if point is None:
            return self._not_ready()
        self.pending["left"] = left
        self.pending["right"] = right
        self._note_direction(point.position_mm)
        index = self._segment_index(point.position_mm)
        if self.open_index is None:
            self.open_index = index
        elif index != self.open_index:
            self._close_open_segment()
            self.open_index = index
        self.open_points.append(point)
        self._judge_open_segment(commit_history=False)
        return self._snapshot(index)

    def _pair_is_fresh(self, left: dict, right: dict) -> bool:
        left_pos = _as_float(left.get("position_mm"))
        right_pos = _as_float(right.get("position_mm"))
        if left_pos is None or right_pos is None:
            return False
        if abs(left_pos - right_pos) > POSITION_MATCH_MM:
            return False
        left_at = _as_float(left.get("_received_at"))
        right_at = _as_float(right.get("_received_at"))
        if left_at is None or right_at is None:
            return True
        return abs(left_at - right_at) <= PAIR_MAX_AGE_S

    def _point_from_pair(self, left: dict, right: dict) -> SamplePoint | None:
        gap_l = _as_float(left.get("sensor_distance_mm"))
        gap_r = _as_float(right.get("sensor_distance_mm"))
        pos_l = _as_float(left.get("position_mm"))
        pos_r = _as_float(right.get("position_mm"))
        if None in (gap_l, gap_r, pos_l, pos_r):
            return None
        if abs(pos_l - pos_r) > POSITION_MATCH_MM:
            return None
        ax = _mean_axis(left, right, "accel_x")
        az = _mean_axis(left, right, "accel_z")
        tilt = estimate_roll_deg(ax, _mean_axis(left, right, "accel_y"), az)
        recorded = _as_float(left.get("_received_at")) or _as_float(right.get("_received_at"))
        return SamplePoint(
            position_mm=(pos_l + pos_r) / 2.0,
            m_mm=(gap_l + gap_r) / 2.0,
            delta_mm=gap_l - gap_r,
            apeak=max(_dynamic_z(left), _dynamic_z(right)),
            tilt_deg=0.0 if tilt is None else tilt,
            recorded_at=recorded if recorded is not None else time.time(),
        )

    def _note_direction(self, position_mm: float) -> None:
        previous = self.previous_position_mm
        self.previous_position_mm = position_mm
        if previous is None:
            return
        delta = position_mm - previous
        if delta <= -PASS_RESET_MM:
            self._close_open_segment()
            self.open_index = None
            self.pass_count += 1
            self.pass_started_at = time.time()
            return
        if abs(delta) >= 0.5:
            self.direction = 1 if delta > 0 else -1

    def _segment_index(self, position_mm: float) -> int:
        index = int(position_mm / self.segment_mm)
        return max(0, min(index, self.segment_count - 1))

    def _close_open_segment(self) -> None:
        if self.open_index is None or not self.open_points:
            self.open_points = []
            return
        self._judge_open_segment(commit_history=True)
        self.open_points = []

    def _judge_open_segment(self, *, commit_history: bool) -> None:
        if self.open_index is None or not self.open_points:
            return
        features = _features(self.open_points)
        record = self.segments[self.open_index]
        if not self.baseline_locked:
            if _is_quiet(features):
                self._absorb_baseline(features)
                if commit_history:
                    self.quiet_segments += 1
                    if self.quiet_segments >= QUIET_SEGMENTS_TO_LOCK:
                        self.baseline_locked = True
            self._write_normal(record, features)
            return

        delta = features["delta_raw"] - self.delta_offset
        m_change = features["m"] - (self.baseline_m or features["m"])
        defect_type, magnitude = _classify(
            m_change=m_change,
            delta=delta,
            dm_dx=features["dm_dx"],
            apeak=features["apeak"],
            tilt_deg=features["tilt"],
            segment_mm=self.segment_mm,
        )
        if len(record.history) + 1 >= MIN_PASSES_FOR_POINT1_MM:
            magnitude = _mean([item[1] for item in record.history] + [magnitude])
        stage = stage_for(defect_type, abs(magnitude))
        record.defect_type = defect_type
        record.stage = stage
        record.magnitude_mm = abs(magnitude)
        record.m_mm = m_change
        record.delta_mm = delta
        record.dm_dx = features["dm_dx"]
        record.ddelta_dx = features["ddelta_dx"]
        record.apeak = features["apeak"]
        record.tilt_deg = features["tilt"]
        if commit_history:
            record.history.append((features["recorded_at"], abs(magnitude)))
            limit = LIMIT_MM.get(defect_type)
            record.remaining_s, record.rate_mm_per_s = remaining_seconds(
                record.history, limit
            )
            self._mark_relative_fast()

    def _absorb_baseline(self, features: dict) -> None:
        if self.baseline_m is None:
            self.baseline_m = features["m"]
            self.delta_offset = features["delta_raw"]
            return
        self.baseline_m = 0.5 * self.baseline_m + 0.5 * features["m"]
        self.delta_offset = 0.5 * self.delta_offset + 0.5 * features["delta_raw"]

    def _write_normal(self, record: SegmentRecord, features: dict) -> None:
        record.defect_type = "normal"
        record.stage = "ok"
        record.magnitude_mm = 0.0
        record.m_mm = 0.0
        record.delta_mm = features["delta_raw"] - self.delta_offset
        record.dm_dx = features["dm_dx"]
        record.ddelta_dx = features["ddelta_dx"]
        record.apeak = features["apeak"]
        record.tilt_deg = features["tilt"]

    def _mark_relative_fast(self) -> None:
        rates = [
            record.rate_mm_per_s
            for record in self.segments
            if isinstance(record.rate_mm_per_s, (int, float))
        ]
        if not rates:
            return
        ordered = sorted(rates)
        median = ordered[len(ordered) // 2]
        for record in self.segments:
            rate = record.rate_mm_per_s
            record.relative_fast = bool(
                isinstance(rate, (int, float)) and rate > 0 and rate >= max(median * 2.0, 1e-6)
            )

    def _snapshot(self, index: int) -> dict:
        current = self.segments[index]
        ahead = index + self.direction
        ahead_stage = (
            self.segments[ahead].stage
            if 0 <= ahead < self.segment_count
            else "ok"
        )
        motion = _motion(current.stage, ahead_stage)
        defects = self.defect_list()
        return {
            "ready": True,
            "segment_index": index,
            "defect_type": current.defect_type,
            "stage": current.stage,
            "score": STAGE_SCORE[current.stage],
            "m_mm": current.m_mm,
            "delta_mm": current.delta_mm,
            "dm_dx": current.dm_dx,
            "ddelta_dx": current.ddelta_dx,
            "apeak": current.apeak,
            "tilt_deg": current.tilt_deg,
            "roll_deg": current.tilt_deg,
            "distance_delta_mm": current.delta_mm,
            "magnitude_mm": current.magnitude_mm,
            "limit_mm": LIMIT_MM.get(current.defect_type),
            "limit_source": LIMIT_SOURCE.get(current.defect_type),
            "remaining_s": current.remaining_s,
            "rate_mm_per_s": current.rate_mm_per_s,
            "relative_fast": current.relative_fast,
            "pass_count": self.pass_count,
            "baseline_locked": self.baseline_locked,
            "motion": motion,
            "defects": defects,
            "rail_risk_left": self._risk_array("left"),
            "rail_risk_right": self._risk_array("right"),
        }

    def defect_list(self) -> list[dict]:
        defects: list[dict] = []
        for index, record in enumerate(self.segments):
            if record.defect_type == "normal":
                continue
            start = index * self.segment_mm
            side = "both"
            if record.defect_type == "cross_level" and isinstance(record.delta_mm, (int, float)):
                side = "left" if record.delta_mm >= 0 else "right"
            defects.append(
                {
                    "side": side,
                    "from_mm": start,
                    "to_mm": start + self.segment_mm,
                    "defect_type": record.defect_type,
                    "stage": record.stage,
                    "m_mm": record.m_mm,
                    "delta_mm": record.delta_mm,
                    "dm_dx": record.dm_dx,
                    "ddelta_dx": record.ddelta_dx,
                    "apeak": record.apeak,
                    "tilt_deg": record.tilt_deg,
                    "magnitude_mm": record.magnitude_mm,
                    "limit_mm": LIMIT_MM.get(record.defect_type),
                    "limit_source": LIMIT_SOURCE.get(record.defect_type),
                    "remaining_s": record.remaining_s,
                    "rate_mm_per_s": record.rate_mm_per_s,
                    "relative_fast": record.relative_fast,
                    "pass_count": len(record.history) or self.pass_count,
                    "score": STAGE_SCORE[record.stage],
                }
            )
        return defects

    def _risk_array(self, side: str) -> list[float]:
        values: list[float] = []
        for record in self.segments:
            score = STAGE_SCORE[record.stage]
            if record.defect_type == "cross_level" and isinstance(record.delta_mm, (int, float)):
                low_side = "left" if record.delta_mm >= 0 else "right"
                if side != low_side:
                    score = 0.0
            values.append(score)
        return values

    def _not_ready(self) -> dict:
        return {
            "ready": False,
            "defect_type": "normal",
            "stage": "ok",
            "score": 0.0,
            "m_mm": None,
            "delta_mm": None,
            "dm_dx": None,
            "ddelta_dx": None,
            "apeak": None,
            "tilt_deg": None,
            "roll_deg": None,
            "distance_delta_mm": None,
            "magnitude_mm": 0.0,
            "motion": "cruise",
            "defects": [],
            "rail_risk_left": [0.0] * self.segment_count,
            "rail_risk_right": [0.0] * self.segment_count,
            "pass_count": self.pass_count,
            "baseline_locked": self.baseline_locked,
            "remaining_s": None,
            "relative_fast": False,
        }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _mean_axis(left: dict, right: dict, key: str) -> float | None:
    values = [value for value in (_as_float(left.get(key)), _as_float(right.get(key))) if value is not None]
    if not values:
        return None
    return _mean(values)


def _dynamic_z(sample: dict) -> float:
    az = _as_float(sample.get("accel_z"))
    if az is None:
        return 0.0
    return abs(az - G_MS2)


def _features(points: list[SamplePoint]) -> dict:
    xs = [point.position_mm for point in points]
    ms = [point.m_mm for point in points]
    deltas = [point.delta_mm for point in points]
    dm_dx, _ = _linreg(xs, ms)
    ddelta_dx, _ = _linreg(xs, deltas)
    return {
        "m": _mean(ms),
        "delta_raw": _mean(deltas),
        "dm_dx": dm_dx,
        "ddelta_dx": ddelta_dx,
        "apeak": max(point.apeak for point in points),
        "tilt": _mean([point.tilt_deg for point in points]),
        "recorded_at": points[-1].recorded_at,
    }


def _is_quiet(features: dict) -> bool:
    return (
        features["apeak"] < APEAK_SMALL
        and abs(features["dm_dx"]) < DM_DX_LARGE
        and abs(features["ddelta_dx"]) < DM_DX_LARGE
    )


def _same_sign(left: float, right: float) -> bool:
    if abs(left) < 1e-6 or abs(right) < 1e-6:
        return False
    return (left > 0) == (right > 0)


def _classify(
    *,
    m_change: float,
    delta: float,
    dm_dx: float,
    apeak: float,
    tilt_deg: float,
    segment_mm: float,
) -> tuple[str, float]:
    if apeak >= APEAK_LARGE and abs(dm_dx) >= DM_DX_LARGE:
        return "joint_step", abs(dm_dx) * segment_mm
    if abs(delta) >= DELTA_LARGE_MM and _same_sign(delta, tilt_deg) and abs(tilt_deg) >= TILT_MIN_DEG:
        return "cross_level", abs(delta)
    if (
        abs(m_change) >= M_CHANGE_LARGE_MM
        and apeak < APEAK_SMALL
        and abs(delta) < DELTA_SMALL_MM
    ):
        return "vertical", abs(m_change)
    return "normal", max(abs(m_change), abs(delta))


def _motion(current_stage: str, ahead_stage: str) -> str:
    if current_stage == "danger" or ahead_stage == "danger":
        return "stop"
    if current_stage == "caution" or ahead_stage == "caution":
        return "slow"
    return "cruise"
