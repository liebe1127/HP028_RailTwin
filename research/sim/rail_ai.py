"""레일 결함 크기 AI 추정 — numpy 만으로 돌아가는 1D CNN 앙상블 (torch 불필요).

입력: 기준선(정상)을 뺀 좌·우 변화 신호. 어떤 격자든 받아서 300~1500 mm, 2 mm 간격으로 다시 얹는다.
출력: 단차 크기, 처짐 크기 (mm). 판정 단계는 호출하는 쪽의 규칙(0.5 주의, 1.0 위험, 3회 평균)으로 정한다.
학습: 가상 결함 2,520회 + 실측 정상 4회 배경 (ai_train_v2.py, C3). 실측 결함은 학습에 없다.
가중치: rail_ai_weights.npz (5개 모델, 실측 정상 1회씩 빼고 학습한 교차검증 모델의 앙상블)
"""
import os
import numpy as np

GRID = np.arange(300.0, 1501.0, 2.0)
JOINTS = (600.0, 1200.0)
JM = np.zeros_like(GRID, dtype=bool)
for _j in JOINTS:
    JM |= np.abs(GRID - _j) < 20.0
INFO = ((GRID >= 340) & (GRID <= 860)) | ((GRID >= 940) & (GRID <= 1460))   # 결함 정보가 있는 구간 (이음부 ±250 mm)
KEEP = INFO & ~JM
_WEIGHTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rail_ai_weights.npz")


def to_ai_grid(x, g):
    """임의 격자의 신호를 AI 격자로. NaN 은 이웃으로 메우고 남는 끝은 0."""
    x = np.asarray(x, float); g = np.asarray(g, float)
    ok = np.isfinite(g) & np.isfinite(x)
    if ok.sum() < 10:
        return np.zeros_like(GRID)
    xs, gs = x[ok], g[ok]
    o = np.argsort(xs, kind="stable")
    ux, inv = np.unique(np.round(xs[o], 1), return_inverse=True)          # 같은 위치 표본은 평균
    ug = np.bincount(inv, weights=gs[o]) / np.bincount(inv)
    out = np.interp(GRID, ux, ug, left=np.nan, right=np.nan)
    return np.where(np.isfinite(out), out, 0.0)


def prepare(gL, gR, x=None):
    """(2, 601) float32 입력. x 가 None 이면 이미 AI 격자라고 본다."""
    if x is not None:
        gL = to_ai_grid(x, gL); gR = to_ai_grid(x, gR)
    sig = np.stack([np.asarray(gL, float), np.asarray(gR, float)])
    sig = np.where(np.isfinite(sig), sig, 0.0)
    sig[:, ~KEEP] = 0.0
    return sig.astype(np.float32)


def sensor_check(gL, gR, x=None, thr=0.7):
    """한쪽 센서가 이음부를 지나는데 부호가 안 바뀌고 큰 값을 유지하면 센서 어긋남 (강체 파이프에서는 못 나오는 모양).
    반환: [(side, joint_mm, offset_mm), ...]"""
    if x is not None:
        gL = to_ai_grid(x, gL); gR = to_ai_grid(x, gR)
    flags = []
    for name, g in (("left", np.asarray(gL, float)), ("right", np.asarray(gR, float))):
        g = np.where(np.isfinite(g), g, 0.0)
        for j in JOINTS:
            wa = (GRID > j - 200) & (GRID < j - 60); wb = (GRID > j + 60) & (GRID < j + 200)
            a = g[wa].mean(); b = g[wb].mean()
            lo, hi = min(abs(a), abs(b)), max(abs(a), abs(b))
            if not (np.sign(a) == np.sign(b) and lo >= thr and lo / hi >= 0.6):
                continue
            # 평평한가: 받침 침하의 봉우리(이음부 쪽이 높고 멀수록 0 으로 감)는 평평하지 않다
            flat = True
            for w in (wa, wb):
                near = g[w & (np.abs(GRID - j) < 130)].mean(); far = g[w & (np.abs(GRID - j) >= 130)].mean()
                if abs(near - far) > 0.25 * max(abs(near), abs(far), 1e-6):
                    flat = False
            # 이음부 ±250 mm 밖까지 이어지는가: 강체 파이프 결함의 신호는 ±250 안에만 있다
            outside = False
            for lo_x, hi_x in ((j - 340, j - 260), (j + 260, j + 340)):
                w = (GRID > lo_x) & (GRID < hi_x)
                if w.any() and np.sign(g[w].mean()) == np.sign(a) and abs(g[w].mean()) >= thr:
                    outside = True
            if flat and outside:
                flags.append((name, float(j), round(float((a + b) / 2), 2)))
    return flags


# ---- numpy 로 쓴 CNN 순전파 (ai_train.Net 과 같은 구조) ----
def _conv1d(x, w, b):
    o, i, k = w.shape; pad = k // 2; T = x.shape[1]
    xp = np.pad(x, ((0, 0), (pad, pad)))
    out = np.zeros((o, T)) + b[:, None]
    for t in range(k):
        out += w[:, :, t] @ xp[:, t:t + T]
    return out


def _bn(x, g, b, m, v, eps=1e-5):
    return (x - m[:, None]) / np.sqrt(v[:, None] + eps) * g[:, None] + b[:, None]


def _maxpool2(x):
    T = x.shape[1] // 2
    return np.maximum(x[:, 0:2 * T:2], x[:, 1:2 * T:2])


def _adaptive_avg(x, n):
    L = x.shape[1]
    return np.stack([x[:, int(np.floor(i * L / n)):int(np.ceil((i + 1) * L / n))].mean(1) for i in range(n)], 1)


def _forward(p, sig):
    x = sig.astype(float)
    for blk, pool in ((0, True), (1, True), (2, True), (3, False)):
        x = _conv1d(x, p[f"c{blk}.w"], p[f"c{blk}.b"])
        x = np.maximum(_bn(x, p[f"c{blk}.g"], p[f"c{blk}.beta"], p[f"c{blk}.m"], p[f"c{blk}.v"]), 0.0)
        if pool:
            x = _maxpool2(x)
    x = _adaptive_avg(x, 8).reshape(-1)
    x = np.maximum(p["l0.w"] @ x + p["l0.b"], 0.0)
    z = p["l1.w"] @ x + p["l1.b"]
    return np.log1p(np.exp(-np.abs(z))) + np.maximum(z, 0.0)     # softplus


class RailAI:
    def __init__(self, path=_WEIGHTS):
        z = np.load(path)
        self.n_models = int(z["n_models"])
        self.models = [{k.split("/", 1)[1]: z[k] for k in z.files if k.startswith(f"m{i}/")} for i in range(self.n_models)]

    def predict(self, gL, gR, x=None):
        """단차 크기, 처짐 크기 (mm). 모델 평균과 모델 간 표준편차를 함께 준다."""
        sig = prepare(gL, gR, x)
        outs = np.array([_forward(p, sig) for p in self.models])
        mean = outs.mean(0); sd = outs.std(0)
        return {"joint_step": float(mean[0]), "vertical": float(mean[1]),
                "spread": {"joint_step": float(sd[0]), "vertical": float(sd[1])}}


if __name__ == "__main__":
    import sys, pandas as pd
    ai = RailAI()
    for f in sys.argv[1:]:
        d = pd.read_csv(f)
        print(f, ai.predict(d.iloc[:, 1], d.iloc[:, 2], d.iloc[:, 0]))
