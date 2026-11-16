"""AI 2차 — 1차 결과에서 찾은 두 문제를 고친다.

  문제 1. CNN 이 실측 단차 크기를 작게 봄 (1.39, 정답 2). 실측 주행의 파이프 가운데 구간(두 바퀴가 같은 파이프 위, 850~950 mm)이
          −0.6 mm 로 내려가는데 가상 모형은 0 이다. 강체 파이프라면 결함 정보는 이음부 ±250 mm 에만 있으므로,
          그 밖(300~340, 860~940, 1460~1500)은 입력에서 0 으로 지운다  → C2 "구간 제한"
  문제 2. 실측 정상의 다시 놓임 배경이 가상과 달라 처짐 크기가 흔들림. 실측 정상 주행을 배경으로 섞고 "정상이면 0" 손실을 더한다
          → C3 "구간 제한 + 실측 정상 적응". 실측 정상 5회(32~36) 중 1회씩 빼 가며 5번 학습(교차검증). 31차는 센서 어긋남 회차라 적응에 쓰지 않는다.
  추가.   센서 어긋남 검사: 한쪽 신호가 이음부를 지나면서 부호가 바뀌지 않고 0.7 mm 이상 유지되면 "센서 점검" (강체 파이프에서는 불가능한 모양)

실측 결함 12회는 어느 학습에도 들어가지 않는다.
"""
import os, sys, json, time, glob
import numpy as np
import pandas as pd
import torch, torch.nn as nn
import ai_train as at
import sim2real as sr
import sim2real_v2 as v2
import generate_dataset as gd
import matplotlib.pyplot as plt

GRID = sr.GRID; JM = sr.JM; N = len(GRID)
KR = v2.KR; ST = v2.ST
INFO = ((GRID >= 340) & (GRID <= 860)) | ((GRID >= 940) & (GRID <= 1460))   # 결함 정보가 있는 구간
MASK = ~INFO


def masked(x):
    x = x.copy(); x[..., MASK] = 0.0; return x


def sensor_check(sig, thr=0.7):
    """한쪽 센서가 이음부를 지나는데 부호가 안 바뀌고 큰 값을 유지 → 센서 어긋남. (side, joint, 값) 목록."""
    flags = []
    for s, name in enumerate(("left", "right")):
        g = sig[s]
        for j in (600.0, 1200.0):
            a = g[(GRID > j - 200) & (GRID < j - 60)].mean(); b = g[(GRID > j + 60) & (GRID < j + 200)].mean()
            if np.sign(a) == np.sign(b) and min(abs(a), abs(b)) >= thr and min(abs(a), abs(b)) / max(abs(a), abs(b)) >= 0.6:
                flags.append((name, int(j), round(float((a + b) / 2), 2)))
    return flags


def train(Xtr, Ytr, Xva, Yva, seed, real_bg=None, epochs=40):
    """real_bg: 실측 정상 변화 신호 (k, 2, N). 있으면 배경으로 섞고 0 손실을 더한다."""
    torch.manual_seed(seed); rng = np.random.default_rng(seed)
    bank = {0: np.array(gd.CAL["noise_bank"]["left"]), 1: np.array(gd.CAL["noise_bank"]["right"])}
    net = at.Net(); opt = torch.optim.Adam(net.parameters(), lr=2e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    Xva_t = torch.tensor(masked(Xva)); Yva_t = torch.tensor(Yva)
    best = (1e9, None)
    for ep in range(epochs):
        net.train(); idx = rng.permutation(len(Xtr))
        for b in range(0, len(idx), 64):
            j = idx[b:b + 64]
            xb = at.augment(Xtr[j], rng, bank)
            if real_bg is not None:
                # 절반의 표본에 실측 정상 배경을 0.5~1.0 배, ±20 mm 밀어서 더한다
                for i in range(len(j)):
                    if rng.random() < 0.5:
                        k = rng.integers(len(real_bg)); sh = rng.integers(-10, 11)
                        xb[i] += rng.uniform(0.5, 1.0) * np.roll(real_bg[k], sh, axis=1)
            loss = nn.functional.smooth_l1_loss(net(torch.tensor(masked(xb))), torch.tensor(Ytr[j]))
            if real_bg is not None:
                rb = real_bg[rng.integers(len(real_bg), size=8)].copy()
                for i in range(len(rb)):
                    rb[i] = np.roll(rb[i], rng.integers(-10, 11), axis=1) * rng.uniform(0.8, 1.2)
                loss = loss + 0.5 * nn.functional.smooth_l1_loss(net(torch.tensor(masked(rb).astype(np.float32))), torch.zeros(len(rb), 2))
            opt.zero_grad(); loss.backward(); opt.step()
        sched.step()
        net.eval()
        with torch.no_grad():
            vl = nn.functional.smooth_l1_loss(net(Xva_t), Yva_t).item()
        if vl < best[0]:
            best = (vl, {k: v.clone() for k, v in net.state_dict().items()})
    net.load_state_dict(best[1]); net.eval()
    return net, best[0]


def predict(net, X):
    with torch.no_grad():
        return net(torch.tensor(masked(X).astype(np.float32))).numpy()


def main():
    t0 = time.time()
    Xs, Fs, man = at.load_synth(["../dataset_v2", "../dataset_v2_seed9"])
    Xr, Fr, truth = at.load_real(); Fr = Fr[list(Fs.columns)]
    Ys = np.stack([man.size_HF_mm.to_numpy(), man.size_C_mm.to_numpy()], 1).astype(np.float32)
    pids = man.pid.to_numpy(); uniq = np.unique(pids); rng = np.random.default_rng(1)
    va_p = set(rng.choice(uniq, size=len(uniq) // 5, replace=False)); va = np.array([p in va_p for p in pids]); tr = ~va
    runs = truth.run.to_numpy(); lines = []
    # 센서 어긋남 검사
    lines.append("센서 어긋남 검사 (실측 18회):")
    sflag = {}
    for i, r in enumerate(runs):
        f = sensor_check(Xr[i]); sflag[r] = bool(f)
        if f: lines.append(f"  {r}: 센서 점검 {f}")
    lines.append(f"  표시된 회차 {sum(sflag.values())}개 / 18")
    results = {}
    # A 규칙, C1 (1차 CNN, 저장된 가중치)
    rH, rC = at.rule_sizes(Fr); results["A 규칙"] = (None, rH, rC)
    c1 = []
    for s in range(3):
        n = at.Net(); n.load_state_dict(torch.load(f"ai_cnn_seed{s}.pt")); n.eval()
        with torch.no_grad(): c1.append(n(torch.tensor(Xr)).numpy())
    c1 = np.mean(c1, 0); results["C1 CNN (1차)"] = (None, c1[:, 0], c1[:, 1])
    # C2 구간 제한 (실측 정상 안 씀) 씨앗 3개
    c2v = []; c2r = []
    for seed in (0, 1, 2):
        net, vl = train(Xs[tr], Ys[tr], Xs[va], Ys[va], seed)
        c2v.append(predict(net, Xs[va])); c2r.append(predict(net, Xr)); torch.save(net.state_dict(), f"ai_cnn_v2_seed{seed}.pt")
        print("C2 seed", seed, "val", round(vl, 4), f"{time.time()-t0:.0f}s", flush=True)
    c2v = np.mean(c2v, 0); c2r = np.mean(c2r, 0)
    sv2 = at.score(c2v[:, 0], c2v[:, 1], Ys[va, 0], Ys[va, 1], man.stage[va])
    results["C2 CNN 구간 제한"] = (sv2, c2r[:, 0], c2r[:, 1])
    # C3 구간 제한 + 실측 정상 적응, 정상 5회 교차검증
    clean = [r for r in runs if r.startswith("c1_") and r != "c1_r31"]
    pred3 = np.zeros((len(runs), 2)); cnt = np.zeros(len(runs)); sv3s = []
    for hold in clean:
        adapt_idx = [i for i, r in enumerate(runs) if r.startswith("c1_") and r != "c1_r31" and r != hold]
        real_bg = Xr[adapt_idx]
        net, vl = train(Xs[tr], Ys[tr], Xs[va], Ys[va], seed=7, real_bg=real_bg)
        p = predict(net, Xr); pv = predict(net, Xs[va]); sv3s.append(at.score(pv[:, 0], pv[:, 1], Ys[va, 0], Ys[va, 1], man.stage[va]))
        for i, r in enumerate(runs):
            if i in adapt_idx: continue
            pred3[i] += p[i]; cnt[i] += 1
        torch.save(net.state_dict(), f"ai_cnn_v3_hold_{hold}.pt")
        print("C3 hold", hold, "val", round(vl, 4), f"{time.time()-t0:.0f}s", flush=True)
    pred3 /= cnt[:, None]
    sv3 = {k: float(np.mean([s[k] for s in sv3s])) for k in ("type_acc", "stage_acc", "rmse_HF", "rmse_C")}
    results["C3 CNN 구간 제한 + 실측 정상 적응"] = (sv3, pred3[:, 0], pred3[:, 1])

    # 표
    hf = truth.kind == "HF"; c = truth.kind == "C"; nm = truth.kind == "normal"
    lines.append("\n| 방법 | 가상 검증 종류 / 단계 / 단차 RMSE / 처짐 RMSE | 실측 종류 | 실측 단계 | 센서 검사 뒤 단계 | 단차 크기 (정답 2) | 처짐 크기 (정답 2) | 정상 회차 최대 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    per = pd.DataFrame(dict(run=runs, kind=truth.kind, stage=truth.stage))
    for name, (sv, pH, pC) in results.items():
        s = at.score(pH, pC, truth.sHF, truth.sC, truth.stage, truth.kind)
        ok_after = sum((st == truth.stage[i]) or sflag[runs[i]] and truth.kind[i] == "normal" for i, st in enumerate(s["stages"]))
        svtxt = "-" if sv is None else f"{sv['type_acc']*100:.0f} % / {sv['stage_acc']*100:.0f} % / {sv['rmse_HF']:.2f} / {sv['rmse_C']:.2f}"
        lines.append(f"| {name} | {svtxt} | {int(s['type_acc']*18)}/18 | {int(s['stage_acc']*18)}/18 | {ok_after}/18 | {pH[hf].mean():.2f} ± {pH[hf].std(ddof=1):.2f} | {pC[c].mean():.2f} ± {pC[c].std(ddof=1):.2f} | 단차 {pH[nm & (runs != 'c1_r31')].max():.2f} 처짐 {pC[nm & (runs != 'c1_r31')].max():.2f} |")
        short = name.split(" (")[0]; per[f"{short}_HF"] = np.round(pH, 3); per[f"{short}_C"] = np.round(pC, 3)
        per[f"{short}_판정"] = [f"{KR[k]}·{ST[st]}" for k, st in zip(s["kinds"], s["stages"])]
    lines.append("\n'센서 검사 뒤 단계' = 센서 점검으로 표시된 정상 회차는 결함 판정 대신 '센서 점검'으로 처리한 경우")
    # 3회 평균
    from itertools import combinations
    lines.append("\n3회 평균 판정 (센서 점검 회차 31차 제외: 정상 5회 중 3회 조합 10가지, 결함은 20가지씩):")
    lines.append("| 방법 | 종류 | 단계 | 정상 오경보 | 단차 위험 | 처짐 위험 |"); lines.append("|---|---|---|---|---|---|")
    for name, (sv, pH, pC) in results.items():
        okk = oks = n = 0; fa = hd = cd = 0; nn_ = 0
        for kind in ("normal", "HF", "C"):
            idx = [i for i in np.where(truth.kind == kind)[0] if runs[i] != "c1_r31"]
            for trip in combinations(idx, 3):
                h = pH[list(trip)].mean(); cc = pC[list(trip)].mean(); k, st = v2.rule(h, cc)
                n += 1; okk += (k == kind); oks += (st == truth.stage[trip[0]])
                if kind == "normal": fa += (st != "normal"); nn_ += 1
                if kind == "HF": hd += (st == "danger")
                if kind == "C": cd += (st == "danger")
        lines.append(f"| {name.split(' (')[0]} | {okk}/{n} | {oks}/{n} | {fa}/{nn_} | {hd}/20 | {cd}/20 |")
    lines.append("\n실측 회차별 판정:")
    lines.append(per[["run", "kind"] + [cn for cn in per.columns if cn.endswith("_판정")]].to_string(index=False))
    lines.append(f"\n전체 {time.time()-t0:.0f}초")
    txt = "\n".join(lines); print(txt); open("ai_v2_result.md", "w").write(txt)
    per.to_csv("ai_v2_real_predictions.csv", index=False, encoding="utf-8-sig")
    # 그림
    fig, ax = plt.subplots(figsize=(11, 4.6)); names = list(results); x = np.arange(len(names))
    for i, k in enumerate(names):
        pH, pC = results[k][1], results[k][2]
        ax.errorbar(i - 0.15, pH[hf].mean(), yerr=pH[hf].std(ddof=1), fmt="o", color="tab:orange", capsize=4, label="단차 회차의 단차 크기" if i == 0 else None)
        ax.errorbar(i + 0.15, pC[c].mean(), yerr=pC[c].std(ddof=1), fmt="s", color="tab:green", capsize=4, label="처짐 회차의 처짐 크기" if i == 0 else None)
        s = at.score(pH, pC, truth.sHF, truth.sC, truth.stage, truth.kind)
        ax.text(i, 2.75, f"종류 {int(s['type_acc']*18)}/18\n단계 {int(s['stage_acc']*18)}/18", ha="center", fontsize=9)
    ax.axhline(2.0, color="k", ls="--", lw=.8, label="정답 2 mm"); ax.axhline(1.0, color="tab:red", ls=":", lw=.8, label="허용 한계 1.0")
    ax.set_xticks(x); ax.set_xticklabels([n.split(" (")[0] for n in names], fontsize=9); ax.set_ylim(0, 3.1); ax.set_ylabel("mm"); ax.grid(alpha=.3, axis="y"); ax.legend(fontsize=8, loc="lower right")
    ax.set_title("AI 2차 — 실측 18회 결함 크기 추정과 판정 (실측 결함은 학습에 없음)"); fig.tight_layout(); fig.savefig("ai_v2_result.png", dpi=110)


if __name__ == "__main__":
    main()
