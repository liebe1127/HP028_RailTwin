"""재검증 2: C3 를 다른 씨앗(11)으로 다시 학습해 실측 18회 결과가 유지되는지."""
import numpy as np, torch, time
import ai_train as at, ai_train_v2 as v2t, sim2real_v2 as v2
t0 = time.time()
Xs, Fs, man = at.load_synth(["../dataset_v2", "../dataset_v2_seed9"]); Xr, Fr, truth = at.load_real()
Ys = np.stack([man.size_HF_mm.to_numpy(), man.size_C_mm.to_numpy()], 1).astype(np.float32)
pids = man.pid.to_numpy(); uniq = np.unique(pids); rng = np.random.default_rng(1)
va_p = set(rng.choice(uniq, size=len(uniq) // 5, replace=False)); va = np.array([p in va_p for p in pids]); tr = ~va
runs = truth.run.to_numpy(); clean = [r for r in runs if r.startswith("c1_") and r != "c1_r31"]
pred = np.zeros((len(runs), 2)); cnt = np.zeros(len(runs))
for hold in clean:
    adapt = [i for i, r in enumerate(runs) if r.startswith("c1_") and r not in ("c1_r31", hold)]
    net, vl = v2t.train(Xs[tr], Ys[tr], Xs[va], Ys[va], seed=11, real_bg=Xr[adapt])
    p = v2t.predict(net, Xr)
    for i in range(len(runs)):
        if i not in adapt: pred[i] += p[i]; cnt[i] += 1
    print("hold", hold, f"{time.time()-t0:.0f}s", flush=True)
pred /= cnt[:, None]
s = at.score(pred[:, 0], pred[:, 1], truth.sHF, truth.sC, truth.stage, truth.kind)
hf = truth.kind == "HF"; c = truth.kind == "C"
L = [f"C3 씨앗 11 재학습 — 실측 종류 {int(s['type_acc']*18)}/18, 단계 {int(s['stage_acc']*18)}/18, 단차 {pred[hf,0].mean():.2f} ± {pred[hf,0].std(ddof=1):.2f}, 처짐 {pred[c,1].mean():.2f} ± {pred[c,1].std(ddof=1):.2f}",
     "(씨앗 7: 종류 17/18, 단계 17/18, 단차 1.98 ± 0.03, 처짐 1.56 ± 0.44)"]
for i, r in enumerate(runs): L.append(f"  {r} {v2.KR[truth.kind[i]]} → {v2.KR[s['kinds'][i]]}·{v2.ST[s['stages'][i]]}  단차 {pred[i,0]:.2f} 처짐 {pred[i,1]:.2f}")
txt = "\n".join(L); print(txt); open("recheck_seed.md", "w").write(txt)
