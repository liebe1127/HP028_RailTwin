"""ISO 12488-1에서 잘라 낸 레일 기하 4분류 규칙.

분류: normal / joint_step(HF) / vertical(C, c) / cross_level(E)
구간 특징: m, delta, dm/dx, dΔ/dx, apeak, tilt_deg
단계: ok(한계 50% 이하) / caution / danger
긴급도: (한계선 - 현재값) / 변화 속도. 선형과 로그 중 더 짧은 쪽.
웨이블릿·파고율·RBF는 쓰지 않는다.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field

from pass_analysis import PassAnalyzer, PassProfile, JOINTS_MM, SENSOR_OFFSET_MM

# 좌표계 통일(2026-11-03): 결함 구간·위험도 배열·감속 신호는 모두 "센서 기준 레일 mm" 로 낸다.
# 엔코더 원시값(출발점 0, 뒷바퀴 기준)은 직전 주행 분석이 찾은 이음부 위치·배율로 레일 좌표로 바꾼다.
# 아직 주행 분석 결과가 없을 때만 아래 값(출발 시 뒷바퀴의 레일 위치, mm)을 쓴다. 운용 환경에 맞게 환경 변수로 준다.
# 기본 40: 9/28 실측 24회에서 이음부로 역산한 출발 시 센서 위치 중앙값 289 mm ≈ 40 + 센서 오프셋 250.
ENCODER_ZERO_RAIL_MM = float(os.getenv("RAIL_ENCODER_ZERO_MM", "40"))
# 감속·정지는 주행 분석 결과(rail_risk)에서, 진행 방향으로 이 구간 수만큼 앞을 미리 본다.
MOTION_LOOKAHEAD_SEGMENTS = int(os.getenv("RAIL_MOTION_LOOKAHEAD", "2"))
JUDGE_VERSION = os.getenv("RAIL_JUDGE", "v1").lower()
# 감속·정지를 주행 분석 결과에서 낼지. 기본은 v2 에서만 켠다(v1 은 예전처럼 구간 규칙이 낸다). 환경 변수로 따로 켜고 끈다.
MOTION_FROM_PASS = os.getenv("RAIL_MOTION_FROM_PASS", "1" if JUDGE_VERSION == "v2" else "0").lower() in ("1", "true", "yes")
_BASELINE_FROM_ENV = object()

RAIL_SIDES = ("left", "right")
DEFECT_TYPES = ("normal", "joint_step", "vertical", "cross_level")
STAGES = ("ok", "caution", "danger")
STAGE_SCORE = {"ok": 0.0, "caution": 0.6, "danger": 1.0}
DEFECT_LABELS = {
    "normal": "정상",
    "joint_step": "이음부 단차",
    "vertical": "수직 변형",
    "cross_level": "좌우 높이차",
    "sensor_check": "센서 점검",      # rail_judge_v2 + RAIL_AI=1: 한쪽 센서 어긋남 (레일 결함 아님)
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

# 한계선: 항만 갠트리(수명 주행거리 ≥ 50,000 km)는 ISO 12488-1 공차 1급으로 본다.
# 2026-09-29 실측 24회(정상·단차·수직·좌우 각 6회)로 검증: 3회 이상 평균 판정 시
# 정상 → 정상, 단차 1.84 mm → 위험, 수직 1.98 mm → 위험, 좌우 3.03 mm → 주의.
LIMIT_MM = {
    "joint_step": 1.0,  # 이음부 수직 단차 ≤ 1 mm: ISO 12488-1·BS 466·FEM·CMAA 공통 지침
    "vertical": 1.0,  # ISO 12488-1:2012 표 2, 기호 c (2 m 국부 수직 직진도), 1급
    "cross_level": 5.0,  # ISO 12488-1:2012 표 2, 기호 E, 1급 상한 (스팬 10 m 초과)
}
LIMIT_SOURCE = {
    "joint_step": "joint vertical step <= 1 mm (ISO 12488-1 / BS 466 / FEM / CMAA guidance)",
    "vertical": "ISO 12488-1:2012 table 2 symbol c class 1",
    "cross_level": "ISO 12488-1:2012 table 2 symbol E class 1 cap",
}
# 단계(정상·주의·위험)는 같은 구간을 이 횟수 이상 지난 평균값으로만 판정한다.
# 1회 주행은 정상 레일에서도 ±0.4 mm 흔들려 주의 경계(0.5 mm)에 걸린다(실측 6회 중 2회 오경보).
MIN_PASSES_FOR_STAGE = 3
# 센서 보증 구간(1.6~8 mm) 아래 값은 레일 끝 충돌·접촉이다. 실측에서 레일 끝 충돌이 단차 7~11 mm 오검출을 만들었다.
SENSOR_MIN_VALID_MM = 2.5


# 자이로는 각속도다. 이 시간보다 오래 샘플이 끊기면 각도를 중력 기울기로 다시 잡는다.
GYRO_TILT_GAP_S = 1.0
# 적분 각도가 흔들리지 않게 중력 기울기로 천천히 붙잡는 시간.
GYRO_TILT_TAU_S = 0.5


def estimate_roll_deg(
    accel_x: float | None,
    accel_y: float | None,
    accel_z: float | None,
) -> float | None:
    """중력으로 본 좌우 기울기. 자이로 각도의 기준점이다."""
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
        rail_length_cm: float = 180.0,
        baseline_file=_BASELINE_FROM_ENV,
    ) -> None:
        # baseline_file=None 이면 기준선을 파일에 읽고 쓰지 않는다(재생 전용 엔진). 기본은 RAIL_BASELINE_FILE.
        store = os.getenv("RAIL_BASELINE_FILE", "rail_baseline.json") if baseline_file is _BASELINE_FROM_ENV else baseline_file
        self.segment_count = max(int(segment_count), 1)
        self.rail_length_mm = max(float(rail_length_cm) * 10.0, 1.0)
        self.segment_mm = self.rail_length_mm / self.segment_count
        # 주행 단위 파형 적합 (논문 2.2절). 완만한 결함은 구간 규칙이 못 잡으므로 이 결과가 우선한다.
        if JUDGE_VERSION == "v2":
            # 가상 시운전으로 찾은 네 문제를 고친 수정안(rail_judge_v2.py). 기본은 논문 검증본(v1).
            from rail_judge_v2 import PassAnalyzerV2
            self.pass_analyzer = PassAnalyzerV2(
                LIMIT_MM, MIN_PASSES_FOR_STAGE, store=store
            )
        else:
            self.pass_analyzer = PassAnalyzer(
                LIMIT_MM, MIN_PASSES_FOR_STAGE, store=store
            )
        self.baseline_mode = False       # True 이면 다음 주행들을 정상 기준선으로 등록
        self.pass_profile = PassProfile()
        self.pass_result: dict | None = None
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
        self.roll_deg: float | None = None
        self.roll_at: float | None = None
        self.pass_profile = PassProfile()

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

    def judge_info(self) -> dict:
        """헬스체크·대시보드용 판정 방식 요약."""
        ai = getattr(self.pass_analyzer, "ai", None)
        return {
            "version": JUDGE_VERSION,
            "ai": ai is not None,
            "ai_models": getattr(ai, "n_models", 0) if ai is not None else 0,
            "motion_from_pass": MOTION_FROM_PASS,
            "rail_length_cm": self.rail_length_mm / 10.0,
            "segment_count": self.segment_count,
        }

    def rail_x_mm(self, raw_position_mm: float, *, demo: bool = False) -> float:
        """엔코더 원시값(뒷바퀴, 출발점 0) → 센서 기준 레일 좌표(mm).

        직전 주행 분석이 이음부 틈 두 개를 찾았으면 그 위치·배율로 바꾼다(미끄러짐 보정 포함).
        없으면 출발 위치 가정(ENCODER_ZERO_RAIL_MM) + 센서 오프셋으로 근사한다.
        더미(시연) 샘플은 위치가 이미 더미 레일 좌표라 그대로 쓴다.
        """
        if demo:
            return float(raw_position_mm)
        r = self.pass_result
        if r and r.get("encoder_scale") and r.get("joint_raw_mm"):
            return float(JOINTS_MM[0] + (float(raw_position_mm) - float(r["joint_raw_mm"][0])) * float(r["encoder_scale"]))
        return float(raw_position_mm) + ENCODER_ZERO_RAIL_MM + SENSOR_OFFSET_MM

    def evaluate_pair(self, left: dict, right: dict) -> dict:
        point = self._point_from_pair(left, right)
        if point is None:
            return self._not_ready()
        self.pending["left"] = left
        self.pending["right"] = right
        self._note_direction(point.position_mm)
        self.pass_profile.add(point.position_mm, point.m_mm + point.delta_mm / 2.0, point.m_mm - point.delta_mm / 2.0)
        demo = left.get("_source") == "demo"
        index = self._segment_index(self.rail_x_mm(point.position_mm, demo=demo))   # 구간 번호는 레일 좌표로 (결함 구간과 같은 좌표계)
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
        # 좌·우 엔코더는 배터리 방전에 따라 최대 28%까지 벌어진다(실측). 위치 차로 짝을 버리지 않는다.
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
        if min(gap_l, gap_r) < SENSOR_MIN_VALID_MM:  # 보증 구간 아래 = 레일 끝 충돌·센서 접촉, 버린다
            return None
        recorded = _as_float(left.get("_received_at")) or _as_float(right.get("_received_at"))
        tilt = self._tilt_from_gyro(left, right, recorded if recorded is not None else time.time())
        return SamplePoint(
            position_mm=pos_l,  # 위치 기준은 좌 엔코더 하나로 통일 (디지털 트윈과 동일)
            m_mm=(gap_l + gap_r) / 2.0,
            delta_mm=gap_l - gap_r,
            apeak=max(_dynamic_z(left), _dynamic_z(right)),
            tilt_deg=0.0 if tilt is None else tilt,
            recorded_at=recorded if recorded is not None else time.time(),
        )

    def _tilt_from_gyro(self, left: dict, right: dict, recorded_at: float) -> float:
        """좌우 기울기 φ. 칩 Y 자이로(레일 축 회전)를 적분하고, 중력 기울기로 드리프트를 잡는다.

        인쇄된 X는 좌우, Z는 위다. 좌우로 기우는 회전은 Y축이다.
        MPU-6050에서 Y축 양의 회전은 atan2(ax, az)를 줄이므로 부호를 뒤집는다.
        """
        gravity = estimate_roll_deg(
            _mean_axis(left, right, "accel_x"),
            _mean_axis(left, right, "accel_y"),
            _mean_axis(left, right, "accel_z"),
        )
        gyro_y = _mean_axis(left, right, "gyro_y")
        if gyro_y is None or self.roll_deg is None or self.roll_at is None:
            self.roll_deg = 0.0 if gravity is None else gravity
            self.roll_at = recorded_at
            return self.roll_deg
        dt = recorded_at - self.roll_at
        if dt <= 0 or dt > GYRO_TILT_GAP_S:
            self.roll_deg = 0.0 if gravity is None else gravity
            self.roll_at = recorded_at
            return self.roll_deg
        predicted = self.roll_deg - math.degrees(gyro_y) * dt
        if gravity is None:
            blended = predicted
        else:
            gyro_weight = GYRO_TILT_TAU_S / (GYRO_TILT_TAU_S + dt)
            blended = gyro_weight * predicted + (1.0 - gyro_weight) * gravity
        self.roll_deg = blended
        self.roll_at = recorded_at
        return blended

    def _note_direction(self, position_mm: float) -> None:
        previous = self.previous_position_mm
        self.previous_position_mm = position_mm
        if previous is None:
            return
        delta = position_mm - previous
        if delta <= -PASS_RESET_MM:
            self.finish_pass()
            return
        if abs(delta) >= 0.5:
            self.direction = 1 if delta > 0 else -1

    def finish_pass(self) -> dict | None:
        """주행 한 번이 끝났다(위치가 200 mm 이상 되돌아감, 또는 API 호출). 프로파일을 분석한다."""
        self._close_open_segment()
        self.open_index = None
        self.pass_count += 1
        self.pass_started_at = time.time()
        profile = self.pass_profile
        self.pass_profile = PassProfile()
        if len(profile) < 200:
            return None
        if self.baseline_mode:
            self.pass_analyzer.register_baseline(profile)
            self.pass_result = None
            return {"baseline_registered": self.pass_analyzer.baseline_count}
        result = self.pass_analyzer.analyze(profile)
        if result is not None:
            self.pass_result = result
        return result

    def _pass_defects(self) -> list[dict]:
        """주행 분석 결과의 결함 목록. v2 는 여러 개(defects), v1 은 대표 하나. 센서 점검은 레일 결함이 아니라 뺀다."""
        r = self.pass_result
        if not r or r["defect_type"] in ("normal", "sensor_check"):
            return []
        if isinstance(r.get("defects"), list):
            return [d for d in r["defects"] if d.get("defect_type") not in (None, "normal")]
        return [r]

    def _pass_segment_range(self, d: dict | None = None) -> tuple[int, int] | None:
        d = d if d is not None else self.pass_result
        if not d or d.get("defect_type") == "normal" or d.get("from_mm") is None or d.get("to_mm") is None:
            return None
        lo = self._segment_index(d["from_mm"])
        hi = self._segment_index(d["to_mm"] - 1e-6)
        return lo, hi

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
        passes = len(record.history) + 1
        if passes >= MIN_PASSES_FOR_STAGE:
            magnitude = _mean([item[1] for item in record.history] + [magnitude])
            stage = stage_for(defect_type, abs(magnitude))
        else:
            stage = "ok"  # 3회 미만: 분류만 표시하고 단계는 보류
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
        if MOTION_FROM_PASS and self.pass_result is not None:
            # 판정과 신호를 같은 근거(주행 분석 결과)로. 진행 방향 앞 구간까지 보고 결함 전에 감속·정지한다.
            motion = self._motion_from_pass(index)
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
            "pass_result": self.pass_result,
            "baseline_mode": self.baseline_mode,
            "baseline_passes": self.pass_analyzer.baseline_count,
            "motion": motion,
            "defects": defects,
            "rail_risk_left": self._risk_array("left"),
            "rail_risk_right": self._risk_array("right"),
        }

    def _motion_from_pass(self, index: int) -> str:
        risk_l = self._risk_array("left")
        risk_r = self._risk_array("right")
        scores = []
        for k in range(0, MOTION_LOOKAHEAD_SEGMENTS + 1):
            i = index + self.direction * k
            if 0 <= i < self.segment_count:
                scores.append(max(risk_l[i], risk_r[i]))
        if any(v >= STAGE_SCORE["danger"] for v in scores):
            return "stop"
        if any(v >= STAGE_SCORE["caution"] for v in scores):
            return "slow"
        return "cruise"

    def defect_list(self) -> list[dict]:
        defects: list[dict] = []
        r = self.pass_result
        if r and r["defect_type"] != "normal":
            # 주행 전체에 대한 정보(v2·AI). 결함마다 같은 값을 붙여 대시보드가 행마다 보여 줄 수 있게 한다
            common = {
                "ai_sizes_mm": r.get("ai_sizes_mm"),
                "ai_spread_mm": r.get("ai_spread_mm"),
                "low_confidence": r.get("low_confidence"),
                "rebaseline_recommended": r.get("rebaseline_recommended"),
                "sensor_check": r.get("sensor_check"),
            }
            items = self._pass_defects() or [r]   # 센서 점검만 있는 주행은 그 한 줄을 보인다
            for d in items:
                kind = d["defect_type"]
                defects.append(
                    {
                        "source": "pass_fit",
                        "side": d.get("side", "both"),
                        "from_mm": d.get("from_mm"),
                        "to_mm": d.get("to_mm"),
                        "defect_type": kind,
                        "stage": d.get("stage", "ok"),
                        "magnitude_mm": d.get("magnitude_mm"),
                        "sizes_mm": r.get("sizes_mm"),
                        "limit_mm": LIMIT_MM.get(kind),
                        "limit_source": LIMIT_SOURCE.get(kind),
                        "pass_count": r.get("passes_used"),
                        "score": STAGE_SCORE.get(d.get("stage"), 0.0),
                        "primary": d is r or (d.get("defect_type") == r["defect_type"] and d.get("from_mm") == r.get("from_mm")),
                        **common,
                    }
                )
        if r and r["defect_type"] == "normal" and r.get("rebaseline_recommended"):
            # v2: 결함은 없는데 복원 높이가 계속 남는다 → 레일이 다시 놓였거나 기준선이 낡았다
            defects.append({
                "source": "pass_fit", "side": "both", "from_mm": None, "to_mm": None,
                "defect_type": "rebaseline", "stage": "ok", "magnitude_mm": r.get("drift_mm"),
                "pass_count": r.get("passes_used"), "score": 0.0, "rebaseline_recommended": True,
            })
        if r is not None:
            return defects  # 주행 분석 결과가 있으면 그것이 우선. 구간 규칙 결과는 섞지 않는다
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
        if self.pass_result is not None:
            values = [0.0] * self.segment_count
            for d in self._pass_defects():
                # side: both 면 양쪽, left/right 면 그 레일만 (좌우 높이차는 낮은 쪽, v2 단차는 오른 쪽 레일)
                if d.get("side", "both") not in ("both", side):
                    continue
                rng = self._pass_segment_range(d)
                if rng:
                    for i in range(rng[0], rng[1] + 1):
                        values[i] = max(values[i], STAGE_SCORE.get(d.get("stage"), 0.0))
            return values
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
            "pass_result": self.pass_result,
            "baseline_mode": self.baseline_mode,
            "baseline_passes": self.pass_analyzer.baseline_count,
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
