"""판정 엔진 수정안 v2 — 가상 시운전에서 찾은 네 가지 문제를 고친 별도 모듈.

팀 레포의 pass_analysis.py / rail_defect.py 는 건드리지 않는다. 위치 보정(PassProfile.resample)은
그대로 가져다 쓰고(잘 동작함), 분석·판정·감속 신호만 새로 쓴다. 재생 장치(replay_virtual.py)가 쓰는
인터페이스(baseline_mode, evaluate_pair, finish_pass, pass_analyzer.history, pass_result, _risk_array)는 같다.

수정 a. 분류 문턱을 허용 한계와 분리: 결함 '있음'은 한계의 절반(주의 기준)부터. 단차·처짐 0.5 mm, 좌우 높이차 2.5 mm.
수정 b. 템플릿을 레일 끝 높이 4개(600−, 600+, 1200−, 1200+) 기본형으로, 좌·우 따로 맞춘다.
        → 임의 위치·한쪽 레일 결함도 크기가 맞고, 결함 위치를 보고할 수 있다.
수정 c. 좌우 높이차 판별 문턱 2.5 mm(ISO 주의선) + 기준선 드리프트 감시(정상인데 복원 높이가 계속 남으면 재등록 권고).
수정 d. 감속·정지 신호를 주행 분석 결과(rail_risk)에서 내고, 진행 방향 앞 두 구간까지 미리 본다.
추가 e. 판별·판정 모두 최근 3회 평균 크기로 한다(1회 값으로 '있음'을 정하지 않음). 잔차 RMS 가 크면 '신뢰 낮음' 경고를 붙인다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

import pass_analysis as pa  # 팀 모듈: GRID_MM, PassProfile(위치 보정), _versine 등 그대로 사용

# 추가 f. AI 크기 추정 (RAIL_AI=1): 단차·처짐 크기를 1D CNN 앙상블(rail_ai.py, numpy 전용)로 잰다.
#         가상 결함 2,520회 + 실측 정상 4회 배경으로 학습. 위치·쪽·좌우 높이차·3회 평균·단계 규칙은 그대로.
#         센서 어긋남 검사도 같이 한다 (한쪽 신호가 이음부를 지나는데 부호가 안 바뀌면 "센서 점검").
USE_AI = os.getenv("RAIL_AI", "0").lower() in ("1", "true", "yes")
if USE_AI:
    import rail_ai

GRID = pa.GRID_MM
JOINTS = pa.JOINTS_MM
RAIL_END = pa.RAIL_END_MM
LIMIT_MM = {"joint_step": 1.0, "vertical": 1.0, "cross_level": 5.0}
DETECT_MM = {k: 0.5 * v for k, v in LIMIT_MM.items()}          # 수정 a, c
MIN_PASSES_FOR_STAGE = 3
STAGE_SCORE = {"ok": 0.0, "caution": 0.5, "danger": 1.0}
DRIFT_WARN_MM = 0.15        # 정상 판정인데 복원된 레일 끝 높이가 이보다 크면 드리프트 의심
LOOKAHEAD_SEGMENTS = 2      # 수정 d: 앞 두 구간까지 보고 미리 감속·정지
RESIDUAL_GATE_MM = 0.30     # 추가 e: 잔차 RMS 가 이보다 크면 '신뢰 낮음' 경고 (정상 주행 잔차는 0.1~0.25)

_MASK = np.ones_like(GRID, dtype=bool)
for _j in JOINTS:
    _MASK &= np.abs(GRID - _j) > pa.JOINT_EXCLUDE_MM


def _profile_from_heights(h600m, h600p, h1200m, h1200p):
    """양 끝 0, 네 끝 높이로 정해지는 파이프 3개의 직선 프로파일."""
    def h(x):
        x = np.asarray(x, float)
        out = np.zeros_like(x)
        seg1 = (x >= 0) & (x < JOINTS[0]); seg2 = (x >= JOINTS[0]) & (x < JOINTS[1]); seg3 = (x >= JOINTS[1]) & (x <= RAIL_END)
        out[seg1] = np.interp(x[seg1], [0.0, JOINTS[0]], [0.0, h600m])
        out[seg2] = np.interp(x[seg2], [JOINTS[0], JOINTS[1]], [h600p, h1200m])
        out[seg3] = np.interp(x[seg3], [JOINTS[1], RAIL_END], [h1200p, 0.0])
        return out
    return h


_T = []
for _k in range(4):
    _u = [0.0] * 4; _u[_k] = 1.0
    _T.append(pa._versine(_profile_from_heights(*_u), GRID))
T_BASIS = np.vstack(_T + [np.ones_like(GRID)]).T      # 열: h600m, h600p, h1200m, h1200p, 상수


def _fit_side(d):
    ok = _MASK & np.isfinite(d)
    coef, *_ = np.linalg.lstsq(T_BASIS[ok], d[ok], rcond=None)
    resid = d[ok] - T_BASIS[ok] @ coef
    return coef[:4], float(np.sqrt(np.mean(resid ** 2)))


def _components(h):
    h600m, h600p, h1200m, h1200p = h
    return {"step": {600.0: h600p - h600m, 1200.0: h1200p - h1200m},
            "settle": {600.0: -(h600m + h600p) / 2.0, 1200.0: -(h1200m + h1200p) / 2.0}}


class PassAnalyzerV2:
    def __init__(self, limits=LIMIT_MM, min_passes_for_stage=MIN_PASSES_FOR_STAGE, store=None):
        self.limits = limits
        self.min_passes = min_passes_for_stage
        self.store = Path(store) if store else None          # v1 과 같은 기준선 저장 파일 (main.py 가 참조)
        self.baseline_l = None; self.baseline_r = None; self.baseline_count = 0
        self.history: list[dict] = []
        self._baseline_runs: list[tuple] = []
        self.ai = rail_ai.RailAI() if USE_AI else None
        if self.store and self.store.exists():
            data = json.loads(self.store.read_text())
            self._baseline_runs = [(np.asarray(l), np.asarray(r)) for l, r in data.get("runs", [])]
            self.baseline_l = np.asarray(data["left"]); self.baseline_r = np.asarray(data["right"])
            self.baseline_count = int(data.get("count", len(self._baseline_runs) or 1))

    def register_baseline(self, profile):
        rs = profile.resample()
        if rs is None:
            return False
        gl, gr, _ = rs
        # 추가 g. 기준선은 주행별 프로파일의 중앙값(3회 이상). 한 회차의 센서 어긋남(실측 31차 같은)이 기준선에 섞이지 않는다
        self._baseline_runs.append((gl, gr))
        L = np.array([a for a, _ in self._baseline_runs]); R = np.array([b for _, b in self._baseline_runs])
        if len(self._baseline_runs) >= 3:
            self.baseline_l, self.baseline_r = np.median(L, axis=0), np.median(R, axis=0)
        else:
            self.baseline_l, self.baseline_r = L.mean(axis=0), R.mean(axis=0)
        self.baseline_count = len(self._baseline_runs)
        if self.store:
            self.store.write_text(json.dumps({"left": self.baseline_l.tolist(), "right": self.baseline_r.tolist(), "count": self.baseline_count,
                                              "runs": [(l.tolist(), r.tolist()) for l, r in self._baseline_runs]}))
        return True

    def analyze(self, profile):
        if self.baseline_l is None:
            return None
        rs = profile.resample()
        if rs is None:
            return None
        gl, gr, meta = rs
        hL, resL = _fit_side(gl - self.baseline_l)
        hR, resR = _fit_side(gr - self.baseline_r)
        low_conf = max(resL, resR) > RESIDUAL_GATE_MM                               # 추가 e: 경고만
        ai_sizes = None; sensor_flags = []
        if self.ai is not None:                                                     # 추가 f
            dl, dr = self._ai_signals(profile, meta)
            sensor_flags = rail_ai.sensor_check(dl, dr)
            ai_sizes = self.ai.predict(dl, dr)
        cL, cR = _components(hL), _components(hR)
        # 단차: 이음부별, 좌·우 중 큰 쪽 (한쪽 레일만 올라간 것도 그대로 잰다)
        step_j = {j: (cL["step"][j], cR["step"][j]) for j in JOINTS}
        j_hf = max(JOINTS, key=lambda j: max(abs(step_j[j][0]), abs(step_j[j][1])))
        sL, sR = step_j[j_hf]
        hf = max(abs(sL), abs(sR))
        hf_side = "both" if min(abs(sL), abs(sR)) > 0.5 * hf else ("left" if abs(sL) >= abs(sR) else "right")
        # 침하: 받침별 좌·우 평균(수직 방향 변형)과 차이(좌우 높이차)
        c_j = {j: (cL["settle"][j] + cR["settle"][j]) / 2.0 for j in JOINTS}
        e_j = {j: cL["settle"][j] - cR["settle"][j] for j in JOINTS}
        j_c = max(JOINTS, key=lambda j: c_j[j]); j_e = max(JOINTS, key=lambda j: abs(e_j[j]))
        c_val = c_j[j_c]; e_val = e_j[j_e]
        # 한쪽만 내려앉은 것은 평균에도 절반이 들어온다 → 차이가 평균보다 크면 좌우 높이차로 본다
        if abs(e_val) > abs(c_val):
            c_report = 0.0
        else:
            c_report = max(c_val, 0.0)
        both_supports = min(c_j.values()) > 0.5 * max(c_j.values()) and c_report > 0
        if ai_sizes is not None:                                                    # 추가 f: 크기만 AI 값으로 바꾼다
            hf = float(ai_sizes["joint_step"])
            ai_c = float(ai_sizes["vertical"])
            # 좌우 높이차 구분: 복원 높이의 좌우 차이가 평균보다 크면 한쪽만 내려앉은 것으로 본다.
            # 다만 AI 가 양쪽 침하를 차이의 절반 이상으로 읽으면 복원 차이가 다시 놓임 때문에 커진 것이므로 AI 값을 믿는다.
            c_report = 0.0 if (abs(e_val) > abs(c_val) and ai_c < 0.5 * abs(e_val)) else ai_c
        sizes = {"joint_step": hf, "vertical": c_report, "cross_level": abs(e_val)}
        signed = {"joint_step": hf, "vertical": c_report, "cross_level": e_val}
        # 이음부 두 곳 모두 단차가 있으면(가운데 파이프 전체가 오르내린 경우) 두 이음부를 한 구간으로 보고한다
        both_joints = all(max(abs(step_j[j][0]), abs(step_j[j][1])) >= DETECT_MM["joint_step"] for j in JOINTS)
        where = {"joint_step": (JOINTS[0] - 100.0, JOINTS[1] + 100.0) if both_joints else j_hf,
                 "vertical": (600.0, 1200.0) if both_supports else j_c, "cross_level": j_e}
        if not sensor_flags:                     # 센서 어긋남 회차는 3회 평균에 넣지 않는다
            self.history.append({"sizes": sizes, "signed": signed})
        recent = self.history[-self.min_passes:]
        # 추가 e: 3회 이상이면 평균 크기로 '있음'과 단계를 정한다 (좌우 높이차는 부호 평균 뒤 절댓값)
        if len(recent) >= self.min_passes:
            avg = {k: float(np.mean([h["signed"][k] for h in recent])) for k in sizes}
            avg["cross_level"] = abs(avg["cross_level"])
        else:
            avg = dict(sizes)
        present = {k: avg[k] >= DETECT_MM[k] for k in sizes}                          # 수정 a, c
        out = self._judge(sizes, avg, present, where, hf_side, e_val, meta, max(resL, resR), hL, hR, low_conf)
        if self.ai is not None:
            out["ai_sizes_mm"] = {k: round(float(v), 3) for k, v in ai_sizes.items() if k != "spread"}
            out["ai_spread_mm"] = {k: round(float(v), 3) for k, v in ai_sizes["spread"].items()}
            out["sensor_check"] = [dict(side=a, joint_mm=b, offset_mm=c) for a, b, c in sensor_flags]
            if sensor_flags:
                out["low_confidence"] = True
                out["defect_type"] = "sensor_check"; out["stage"] = "ok"            # 센서부터 점검. 레일 결함으로 보고하지 않는다
        return out

    def _ai_signals(self, profile, meta):
        """원시 표본을 AI 격자(300~1500, 2 mm)에 얹고 기준선을 뺀 좌·우 변화 신호."""
        pos = np.asarray(profile.pos, float)
        scale = meta.get("encoder_scale"); anchors = meta.get("joint_raw_mm")
        if scale and anchors:
            x = JOINTS[0] + (pos - float(anchors[0])) * float(scale)
        else:
            x = pos + pa.SENSOR_OFFSET_MM
        bl = np.interp(rail_ai.GRID, GRID, self.baseline_l); br = np.interp(rail_ai.GRID, GRID, self.baseline_r)
        return rail_ai.to_ai_grid(x, np.asarray(profile.gl, float)) - bl, rail_ai.to_ai_grid(x, np.asarray(profile.gr, float)) - br

    def _stage(self, kind, magnitude, passes):
        if passes < self.min_passes:
            return "ok"
        lim = self.limits[kind]
        return "danger" if magnitude > lim else ("caution" if magnitude > 0.5 * lim else "ok")

    def _judge(self, sizes, avg, present, where, hf_side, e_val, meta, resid, hL, hR, low_conf=False):
        recent = self.history[-self.min_passes:]; passes = len(recent)
        defects = []
        for kind in ("joint_step", "vertical", "cross_level"):
            if not present[kind]:
                continue
            mag = avg[kind]
            stage = self._stage(kind, mag, passes)
            side = hf_side if kind == "joint_step" else ("both" if kind == "vertical" else ("left" if e_val > 0 else "right"))
            w = where[kind]
            if isinstance(w, tuple):
                frm, to = w
            elif kind == "joint_step":
                frm, to = w - 100.0, w + 100.0
            else:
                frm, to = w - 300.0, w + 300.0
            defects.append(dict(defect_type=kind, magnitude_mm=round(mag, 3), stage=stage, side=side,
                                from_mm=max(frm, 0.0), to_mm=min(to, RAIL_END), ratio=mag / self.limits[kind]))
        if defects:
            primary = max(defects, key=lambda d: (STAGE_SCORE[d["stage"]], d["ratio"]))
        else:
            primary = dict(defect_type="normal", magnitude_mm=0.0, stage="ok", side="both", from_mm=None, to_mm=None)
        # 드리프트 감시: 결함이 없는데 복원된 끝 높이가 계속 크면 기준선 재등록 권고
        drift = float(max(np.max(np.abs(hL)), np.max(np.abs(hR))))
        drift_flag = (not defects) and passes >= self.min_passes and drift > DRIFT_WARN_MM
        return {
            "defect_type": primary["defect_type"], "stage": primary["stage"], "magnitude_mm": primary["magnitude_mm"],
            "side": primary["side"], "from_mm": primary["from_mm"], "to_mm": primary["to_mm"],
            "sizes_mm": {k: round(float(v), 3) for k, v in sizes.items()},
            "defects": defects, "passes_used": passes, "encoder_scale": meta.get("encoder_scale"),
            "residual_rms_mm": round(resid, 3), "drift_mm": round(drift, 3), "rebaseline_recommended": bool(drift_flag),
            "low_confidence": bool(low_conf),
            "joint_raw_mm": meta.get("joint_raw_mm"),   # 다음 주행에서 엔코더 원시값을 레일 좌표로 바꾸는 데 쓴다
        }


class DefectRuleEngineV2:
    """replay_virtual.py 가 쓰는 만큼의 인터페이스만 갖춘 가벼운 엔진."""

    def __init__(self, segment_count=20, rail_length_cm=180.0):
        self.segment_count = int(segment_count)
        self.rail_length_mm = float(rail_length_cm) * 10.0
        self.segment_mm = self.rail_length_mm / self.segment_count
        self.pass_analyzer = PassAnalyzerV2()
        self.baseline_mode = False
        self.pass_profile = pa.PassProfile()
        self.pass_result = None
        self.previous_position = None
        self.direction = 1

    def evaluate_pair(self, left, right):
        gl, gr = left.get("sensor_distance_mm"), right.get("sensor_distance_mm")
        pos = left.get("position_mm")
        if gl is None or gr is None or pos is None:
            return {"ready": False, "motion": "cruise"}
        if min(gl, gr) < pa.SENSOR_MIN_VALID_MM:
            return {"ready": False, "motion": "cruise"}
        if self.previous_position is not None and pos != self.previous_position:
            self.direction = 1 if pos > self.previous_position else -1
        self.previous_position = pos
        self.pass_profile.add(pos, gl, gr)
        # 수정 d: 감속·정지는 직전 주행 분석 결과의 위험도 배열에서, 앞 구간까지 미리 본다
        # 엔코더 원시값 → 레일 좌표: 직전 주행에서 찾은 이음부 틈 위치와 배율로 바꾼다 (원시값은 출발점 기준이라 그대로 쓰면 약 300 mm 어긋남)
        x_sensor = pos + pa.SENSOR_OFFSET_MM
        if self.pass_result and self.pass_result.get("encoder_scale") and self.pass_result.get("joint_raw_mm"):
            r1 = self.pass_result["joint_raw_mm"][0]
            x_sensor = JOINTS[0] + (pos - r1) * self.pass_result["encoder_scale"]
        idx = int(max(0, min(self.segment_count - 1, x_sensor // self.segment_mm)))
        motion = self._motion_at(idx)
        return {"ready": True, "segment_index": idx, "motion": motion, "pass_result": self.pass_result,
                "rail_risk_left": self._risk_array("left"), "rail_risk_right": self._risk_array("right")}

    def _motion_at(self, idx):
        if not self.pass_result or self.pass_result["defect_type"] == "normal":
            return "cruise"
        risk = np.maximum(self._risk_array("left"), self._risk_array("right"))
        look = [idx + self.direction * k for k in range(0, LOOKAHEAD_SEGMENTS + 1)]
        scores = [risk[i] for i in look if 0 <= i < self.segment_count]
        if any(s >= STAGE_SCORE["danger"] for s in scores):
            return "stop"
        if any(s >= STAGE_SCORE["caution"] for s in scores):
            return "slow"
        return "cruise"

    def finish_pass(self):
        profile = self.pass_profile
        self.pass_profile = pa.PassProfile()
        self.previous_position = None
        if len(profile) < 200:
            return None
        if self.baseline_mode:
            self.pass_analyzer.register_baseline(profile)
            self.pass_result = None
            return {"baseline_registered": self.pass_analyzer.baseline_count}
        res = self.pass_analyzer.analyze(profile)
        if res is not None:
            self.pass_result = res
        return res

    def _risk_array(self, side):
        values = [0.0] * self.segment_count
        r = self.pass_result
        if not r:
            return values
        for d in r.get("defects", []):
            if d["side"] not in ("both", side):
                continue
            lo = int(d["from_mm"] // self.segment_mm); hi = int((d["to_mm"] - 1e-6) // self.segment_mm)
            for i in range(max(lo, 0), min(hi, self.segment_count - 1) + 1):
                values[i] = max(values[i], STAGE_SCORE[d["stage"]])
        return values
