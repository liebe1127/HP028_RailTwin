"""AI 단계 — 가상 데이터로만 학습해 실측 18회를 판정한다. 세 가지를 같은 조건에서 비교.

  A. 규칙 (물리 복원값 → ISO 규칙)                         : 학습 없음. 넘어야 할 기준선
  B. 혼합형 (규칙 추정값 + 물리 특징 → GBR 로 '규칙의 오차'를 학습) : 규칙을 뼈대로 두고 AI 는 보정만
  C. 1D CNN (좌·우 변화 신호 601점×2 → 단차·처짐 크기)      : 신호에서 바로 배움. 학습 중 다시 놓임·잡음·위치 흔들림을 무작위로 더함(도메인 무작위화)

학습: 가상 v2 (seed 2, 1,800회) + seed 9 (720회), 배치 단위로 8:2 나눔
평가: 실측 18회 (정상 6, 단차 6, 처짐 6). 실측은 학습·튜닝에 쓰지 않는다.
정답: 단차 크기·처짐 크기 → 논문 2.3 규칙으로 판정 단계
"""
import os, sys, json, time
import numpy as np
import pandas as pd
import torch, torch.nn as nn
from sklearn.ensemble import GradientBoostingRegressor
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

import railsim as rs
import sim2real as sr
import sim2real_v2 as v2
import generate_dataset as gd

for f in font_manager.findSystemFonts():
    if "NotoSansCJK" in f and "Regular" in f:
        font_manager.fontManager.addfont(f)
plt.rcParams["font.family"] = "Noto Sans CJK KR"; plt.rcParams["axes.unicode_minus"] = False
torch.manual_seed(0); np.random.seed(0)
GRID = sr.GRID; JM = sr.JM; N = len(GRID)
KR = v2.KR; ST = v2.ST


# ---------------- 데이터 ----------------
def signals_from_csv(path, real=False):
    d = pd.read_csv(path)
    if real:
        w = (d.analysis_window == 1) & (d.sensor_valid == 1); d = d[w]
    x = d.rail_x_mm.to_numpy(float)
    out = []
    for s in ("left", "right"):
        g = sr.to_grid(x, d[f"{s}_sensor_distance_mm"].to_numpy(float)) - sr.BASE[s]
        g = np.where(np.isfinite(g), g, 0.0); g = np.where(JM, 0.0, g)
        out.append(g)
    return np.stack(out).astype(np.float32)


def load_synth(paths):
    X, F, man = [], [], []
    for p in paths:
        m = pd.read_csv(os.path.join(p, "manifest.csv")); m["src"] = os.path.basename(p)
        for r in m.itertuples():
            sig = signals_from_csv(os.path.join(p, "runs", r.file))
            X.append(sig); F.append(v2.feats(sig[0], sig[1]))
        man.append(m)
    man = pd.concat(man, ignore_index=True)
    man["pid"] = man.src + "_" + man.placement_id.astype(str)
    return np.stack(X), pd.DataFrame(F), man


def load_real():
    import glob
    X, F, truth = [], [], []
    for f in sorted(glob.glob("../data/c[123]_r*.csv")):
        n = os.path.basename(f)[:-4]; cfg = int(n[1])
        sig = signals_from_csv(f, real=True); X.append(sig); F.append(v2.feats(sig[0], sig[1]))
        truth.append(dict(run=n, sHF=2.0 if cfg == 2 else 0.0, sC=2.0 if cfg == 3 else 0.0,
                          kind={1: "normal", 2: "HF", 3: "C"}[cfg], stage={1: "normal", 2: "danger", 3: "danger"}[cfg]))
    return np.stack(X), pd.DataFrame(F), pd.DataFrame(truth)


def rule_sizes(F):
    sHF = np.maximum(np.abs(F["m_steploc600"]), np.abs(F["m_steploc1200"])).to_numpy()
    sC = (np.maximum(F["m_kink600"], F["m_kink1200"]) / 0.333).clip(lower=0).to_numpy()
    return sHF, sC


def score(pH, pC, truth_HF, truth_C, truth_stage, truth_kind=None):
    ks = [v2.rule(h, c) for h, c in zip(pH, pC)]
    kinds = np.array([k for k, _ in ks]); stages = np.array([s for _, s in ks])
    eff_true = np.array([v2.effective_kind(h, c) for h, c in zip(truth_HF, truth_C)]) if truth_kind is None else np.array(truth_kind)
    return dict(type_acc=float(np.mean(kinds == eff_true)), stage_acc=float(np.mean(stages == np.array(truth_stage))),
                rmse_HF=float(np.sqrt(np.mean((pH - truth_HF) ** 2))), rmse_C=float(np.sqrt(np.mean((pC - truth_C) ** 2))),
                kinds=kinds, stages=stages)


# ---------------- C. 1D CNN ----------------
class Net(nn.Module):
    def __init__(self):
        super().__init__()
        c = lambda i, o, k: nn.Sequential(nn.Conv1d(i, o, k, padding=k // 2), nn.BatchNorm1d(o), nn.ReLU())
        self.f = nn.Sequential(c(2, 16, 9), nn.MaxPool1d(2), c(16, 32, 9), nn.MaxPool1d(2), c(32, 64, 7), nn.MaxPool1d(2),
                               c(64, 64, 5), nn.AdaptiveAvgPool1d(8), nn.Flatten(), nn.Linear(64 * 8, 64), nn.ReLU(), nn.Dropout(0.2), nn.Linear(64, 2))
    def forward(self, x):
        return nn.functional.softplus(self.f(x))


def augment(xb, rng, bank):
    """학습 중 도메인 무작위화: 위치 흔들림 ±6 mm, 완만한 추가 변형, 실측 잡음 추가, 배율 0.95~1.05."""
    xb = xb.copy(); n = xb.shape[0]
    for i in range(n):
        sh = rng.integers(-3, 4); xb[i] = np.roll(xb[i], sh, axis=1)
        for s in range(2):
            amp = rng.uniform(0, 0.25)
            lam = rng.choice([400.0, 600.0, 900.0, 1400.0]); ph = rng.uniform(0, 2 * np.pi)
            xb[i, s] += amp * np.sin(2 * np.pi * GRID / lam + ph) * 0.6
            k = rng.integers(bank[s].shape[0]); xb[i, s] += 0.5 * np.roll(bank[s][k], rng.integers(N))
            xb[i, s] *= rng.uniform(0.95, 1.05)
        xb[i][:, JM] = 0.0
    return xb


def train_cnn(Xtr, Ytr, Xva, Yva, epochs=40, seed=0):
    torch.manual_seed(seed); rng = np.random.default_rng(seed)
    bank = {0: np.array(gd.CAL["noise_bank"]["left"]), 1: np.array(gd.CAL["noise_bank"]["right"])}
    net = Net(); opt = torch.optim.Adam(net.parameters(), lr=2e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    Xva_t = torch.tensor(Xva); Yva_t = torch.tensor(Yva)
    best = (1e9, None)
    for ep in range(epochs):
        net.train(); idx = rng.permutation(len(Xtr))
        for b in range(0, len(idx), 64):
            j = idx[b:b + 64]
            xb = torch.tensor(augment(Xtr[j], rng, bank)); yb = torch.tensor(Ytr[j])
            loss = nn.functional.smooth_l1_loss(net(xb), yb)
            opt.zero_grad(); loss.backward(); opt.step()
        sched.step()
        net.eval()
        with torch.no_grad():
            vl = nn.functional.smooth_l1_loss(net(Xva_t), Yva_t).item()
        if vl < best[0]:
            best = (vl, {k: v.clone() for k, v in net.state_dict().items()})
    net.load_state_dict(best[1]); net.eval()
    return net, best[0]


def main():
    t0 = time.time()
    Xs, Fs, man = load_synth(["../dataset_v2", "../dataset_v2_seed9"])
    Xr, Fr, truth = load_real(); cols = list(Fs.columns); Fr = Fr[cols]
    Ys = np.stack([man.size_HF_mm.to_numpy(), man.size_C_mm.to_numpy()], 1).astype(np.float32)
    pids = man.pid.to_numpy(); uniq = np.unique(pids); rng = np.random.default_rng(1)
    va_p = set(rng.choice(uniq, size=len(uniq) // 5, replace=False)); va = np.array([p in va_p for p in pids]); tr = ~va
    lines = [f"학습 {tr.sum()}회 / 가상 검증 {va.sum()}회 (배치 단위 분리), 실측 평가 18회"]
    results = {}

    # A. 규칙
    rH_s, rC_s = rule_sizes(Fs); rH_r, rC_r = rule_sizes(Fr)
    results["A 규칙"] = (score(rH_s[va], rC_s[va], Ys[va, 0], Ys[va, 1], man.stage[va]), score(rH_r, rC_r, truth.sHF, truth.sC, truth.stage, truth.kind), rH_r, rC_r)

    # B. 혼합형: 규칙 오차를 GBR 로 학습
    Fb = Fs.copy(); Fb["rule_HF"] = rH_s; Fb["rule_C"] = rC_s
    Fbr = Fr.copy(); Fbr["rule_HF"] = rH_r; Fbr["rule_C"] = rC_r
    gH = GradientBoostingRegressor(random_state=0, n_estimators=400, max_depth=3, learning_rate=0.05, subsample=0.8).fit(Fb[tr], Ys[tr, 0] - rH_s[tr])
    gC = GradientBoostingRegressor(random_state=0, n_estimators=400, max_depth=3, learning_rate=0.05, subsample=0.8).fit(Fb[tr], Ys[tr, 1] - rC_s[tr])
    bH_s = np.clip(rH_s + gH.predict(Fb), 0, None); bC_s = np.clip(rC_s + gC.predict(Fb), 0, None)
    bH_r = np.clip(rH_r + gH.predict(Fbr), 0, None); bC_r = np.clip(rC_r + gC.predict(Fbr), 0, None)
    results["B 혼합형 (규칙+GBR 보정)"] = (score(bH_s[va], bC_s[va], Ys[va, 0], Ys[va, 1], man.stage[va]), score(bH_r, bC_r, truth.sHF, truth.sC, truth.stage, truth.kind), bH_r, bC_r)

    # C. 1D CNN — 씨앗 3개로 따로 학습해 흔들림을 본다. 표에는 씨앗 평균 예측(앙상블)을 싣는다
    cnn_runs = []; cs_all = []; cr_all = []
    for seed in (0, 1, 2):
        net, vl = train_cnn(Xs[tr], Ys[tr], Xs[va], Ys[va], epochs=40, seed=seed)
        with torch.no_grad():
            cs = net(torch.tensor(Xs[va])).numpy(); cr = net(torch.tensor(Xr)).numpy()
        cs_all.append(cs); cr_all.append(cr)
        sv = score(cs[:, 0], cs[:, 1], Ys[va, 0], Ys[va, 1], man.stage[va]); srl = score(cr[:, 0], cr[:, 1], truth.sHF, truth.sC, truth.stage, truth.kind)
        cnn_runs.append((seed, vl, sv, srl)); torch.save(net.state_dict(), f"ai_cnn_seed{seed}.pt")
    cs = np.mean(cs_all, 0); cr = np.mean(cr_all, 0)
    results["C 1D CNN (도메인 무작위화, 씨앗 3개 평균)"] = (score(cs[:, 0], cs[:, 1], Ys[va, 0], Ys[va, 1], man.stage[va]), score(cr[:, 0], cr[:, 1], truth.sHF, truth.sC, truth.stage, truth.kind), cr[:, 0], cr[:, 1])

    # 표
    lines.append("\n| 방법 | 가상 검증: 종류 / 단계 / 단차 RMSE / 처짐 RMSE | 실측 18회: 종류 / 단계 | 실측 단차 크기 (정답 2) | 실측 처짐 크기 (정답 2) |")
    lines.append("|---|---|---|---|---|")
    hf_idx = truth.kind == "HF"; c_idx = truth.kind == "C"
    for name, (sv, srl, pH, pC) in results.items():
        lines.append(f"| {name} | {sv['type_acc']*100:.0f} % / {sv['stage_acc']*100:.0f} % / {sv['rmse_HF']:.2f} / {sv['rmse_C']:.2f} | "
                     f"{int(srl['type_acc']*18)}/18 / {int(srl['stage_acc']*18)}/18 | {pH[hf_idx].mean():.2f} ± {pH[hf_idx].std(ddof=1):.2f} | {pC[c_idx].mean():.2f} ± {pC[c_idx].std(ddof=1):.2f} |")
    lines.append("\n실측 회차별 (정답 / A / B / C):")
    for i, r in truth.iterrows():
        cells = [f"{KR[results[k][1]['kinds'][i]]}·{ST[results[k][1]['stages'][i]]}" for k in results]
        lines.append(f"  {r.run:<8s} {KR[r.kind]}·{ST[r.stage]:<3s} | " + " | ".join(cells))
    lines.append("\nCNN 씨앗별 (가상 검증 손실 / 가상 종류·단계 / 실측 종류·단계):")
    for seed, vl, sv, srl in cnn_runs:
        lines.append(f"  씨앗 {seed}: {vl:.4f} / {sv['type_acc']*100:.0f} %·{sv['stage_acc']*100:.0f} % / {int(srl['type_acc']*18)}/18·{int(srl['stage_acc']*18)}/18")
    # 3회 평균 판정 (논문 2.3: 3회 주행 평균으로 단계 확정). 같은 배치 6회 중 3회 조합 20가지 모두
    from itertools import combinations
    lines.append("\n3회 평균 판정 (같은 배치 6회 중 3회 조합 20가지 × 3배치 = 60):")
    lines.append("| 방법 | 종류 | 단계 | 정상 오경보 | 단차 위험 | 처짐 위험 |"); lines.append("|---|---|---|---|---|---|")
    per_run = pd.DataFrame(dict(run=truth.run, kind=truth.kind, stage=truth.stage, sHF=truth.sHF, sC=truth.sC))
    for name, (sv, srl, pH, pC) in results.items():
        short = name.split(" (")[0]; per_run[f"{short}_HF"] = pH; per_run[f"{short}_C"] = pC
        okk = oks = n = 0; fa = 0; hd = 0; cd = 0
        for kind in ("normal", "HF", "C"):
            idx = np.where(truth.kind == kind)[0]
            for trip in combinations(idx, 3):
                h = pH[list(trip)].mean(); c = pC[list(trip)].mean(); k, st = v2.rule(h, c)
                n += 1; okk += (k == kind); oks += (st == truth.stage[trip[0]])
                if kind == "normal": fa += (st != "normal")
                if kind == "HF": hd += (st == "danger")
                if kind == "C": cd += (st == "danger")
        lines.append(f"| {short} | {okk}/{n} | {oks}/{n} | {fa}/20 | {hd}/20 | {cd}/20 |")
    per_run.round(3).to_csv("ai_real_predictions.csv", index=False, encoding="utf-8-sig")
    lines.append(f"\n전체 {time.time()-t0:.0f}초")
    txt = "\n".join(lines); print(txt); open("ai_result.md", "w").write(txt)
    # 그림
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.8))
    names = list(results); x = np.arange(len(names))
    ax[0].bar(x - 0.2, [results[k][0]["stage_acc"] * 100 for k in names], 0.4, label="가상 검증 (배치 분리)", color="0.6")
    ax[0].bar(x + 0.2, [results[k][1]["stage_acc"] * 100 for k in names], 0.4, label="실측 18회", color="tab:blue")
    for i, k in enumerate(names):
        ax[0].text(i - 0.2, results[k][0]["stage_acc"] * 100 + 1, f"{results[k][0]['stage_acc']*100:.0f}%", ha="center", fontsize=9)
        ax[0].text(i + 0.2, results[k][1]["stage_acc"] * 100 + 1, f"{int(results[k][1]['stage_acc']*18)}/18", ha="center", fontsize=9)
    ax[0].set_xticks(x); ax[0].set_xticklabels([n.split(" (")[0] for n in names], fontsize=9); ax[0].set_ylim(0, 105); ax[0].set_ylabel("판정 단계 정답률 %"); ax[0].grid(alpha=.3, axis="y"); ax[0].legend(fontsize=9)
    ax[0].set_title("판정 단계 정답률")
    for i, k in enumerate(names):
        pH, pC = results[k][2], results[k][3]
        ax[1].errorbar(i - 0.15, pH[hf_idx].mean(), yerr=pH[hf_idx].std(ddof=1), fmt="o", color="tab:orange", capsize=4, label="단차 회차의 단차 크기" if i == 0 else None)
        ax[1].errorbar(i + 0.15, pC[c_idx].mean(), yerr=pC[c_idx].std(ddof=1), fmt="s", color="tab:green", capsize=4, label="처짐 회차의 처짐 크기" if i == 0 else None)
    ax[1].axhline(2.0, color="k", ls="--", lw=.8, label="정답 2 mm"); ax[1].axhline(1.0, color="tab:red", ls=":", lw=.8, label="허용 한계 1.0")
    ax[1].set_xticks(x); ax[1].set_xticklabels([n.split(" (")[0] for n in names], fontsize=9); ax[1].set_ylim(0, 3); ax[1].set_ylabel("mm"); ax[1].grid(alpha=.3, axis="y"); ax[1].legend(fontsize=8)
    ax[1].set_title("실측 결함 크기 추정 (평균 ± 표준편차)")
    fig.suptitle("AI 단계 — 가상으로만 학습, 실측 18회 평가", fontsize=12); fig.tight_layout(rect=(0, 0, 1, .94)); fig.savefig("ai_result.png", dpi=110)


if __name__ == "__main__":
    main()
