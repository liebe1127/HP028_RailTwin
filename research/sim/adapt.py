"""새 정상 주행만으로 AI 를 다시 적응시켜 서버용 rail_ai_weights.npz 를 만든다 (ai_train_v2 의 C3 방식 그대로).

사용
  python3 adapt.py --normal-dir <correct_runs.py 로 보정한 새 정상 폴더> --out <출력 폴더>
  옵션  --datasets ../dataset_v2 ../dataset_v2_seed9   가상 데이터셋 (generate_dataset_v2.py 로 먼저 만들어 둔다)
        --device auto|cpu|mps                           기본 auto = cpu. mps 를 고르면 끝에 cpu 와 출력 차이를 찍는다
        --epochs 40  --seed 7  --min-normals 5

하는 일
  1. 새 정상 주행(5회 이상)을 레일 좌표 격자(300~1500 mm, 2 mm)로 읽어 기준선·설치 높이·레일 굴곡·잡음 묶음을 다시 만든다
     (analyze24.py 의 1 단계만). <out>/calibration_new.json 에 저장하고, 원본 calibration.json 은 건드리지 않는다.
  2. 새 정상마다 서버의 센서 어긋남 검사(rail_ai.sensor_check)를 돌린다. 표시된 회차는 적응에 쓰지 않는다.
  3. 가상 데이터셋은 그대로 두고(원본 교정값으로 만든 것), 학습 중 더하는 실측 정상 배경과 잡음 묶음만 새 정상으로 바꿔
     새 정상 1회씩을 빼 가며 학습한다(씨앗 고정). 모델 수 = 쓴 정상 회차 수.
  4. export_weights.py 로 <out>/rail_ai_weights.npz 를 내보내고 torch 와 numpy 출력 차이를 확인한다.
  5. <out>/adapt_report.md 에 ①~⑤ 와 통과/실패를 적는다.
     ① 뺀 회차(학습에 안 쓴 새 정상)의 AI 단차·처짐 추정 최댓값  → 합격 ≤ 0.25 mm
     ② 새 정상에서 센서 점검 표시 수                               → 합격 0
     ③ 가상 검증 묶음 종류·단계 정답률
     ④ 9/28 실측 18회 판정 (결함 12회 추정은 참고용. 펌웨어가 달라 정답 기준은 아니다)
     ⑤ 걸린 시간

서버에 올리기: <out>/rail_ai_weights.npz 를 레포 루트 rail_ai_weights.npz 로 복사하고 RAIL_AI=1 로 켠다.
"""
import argparse, glob, json, os, sys, time
import numpy as np
import pandas as pd
import torch, torch.nn as nn

HERE = os.path.dirname(os.path.abspath(__file__)); CWD0 = os.getcwd()
sys.path.insert(0, HERE)
os.chdir(HERE)                      # sim2real.py 등이 calibration.json 을 현재 폴더에서 읽는다 (명령줄 경로는 원래 폴더 기준으로 푼다)
import railsim as rs
import sim2real as sr
import sim2real_v2 as v2
import ai_train as at
import ai_train_v2 as v2t
import rail_ai
import export_weights as ew

GRID = sr.GRID; JM = sr.JM; N = len(GRID)
KR = v2.KR; ST = v2.ST
PASS_HOLDOUT_MM = 0.25


# ---------------- 새 정상 읽기와 교정 ----------------
def read_runs(folder):
    """보정본 CSV → [(이름, boot_id, 좌 격자 신호, 우 격자 신호)]. 분석 구간·센서 유효 행만 쓴다."""
    runs = []
    for f in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        if os.path.basename(f).startswith("보정_기록"):
            continue
        d = pd.read_csv(f, encoding="utf-8-sig")
        for c in ("rail_x_mm", "analysis_window", "sensor_valid", "left_sensor_distance_mm", "right_sensor_distance_mm"):
            if c not in d.columns:
                sys.exit(f"{f}: {c} 열이 없습니다. correct_runs.py 로 보정한 파일을 주세요")
        w = (d.analysis_window == 1) & (d.sensor_valid == 1) & np.isfinite(d.rail_x_mm)
        x = d.rail_x_mm[w].to_numpy(float)
        gL = sr.to_grid(x, d.left_sensor_distance_mm[w].to_numpy(float))
        gR = sr.to_grid(x, d.right_sensor_distance_mm[w].to_numpy(float))
        bid = str(d["boot_id"].iloc[0]) if "boot_id" in d.columns else ""
        runs.append((os.path.basename(f)[:-4], bid, gL, gR))
    return runs


def calibrate(runs):
    """analyze24.py 1 단계: 기준선(평균), 흔들림(표준편차), 설치 높이 H, 레일 굴곡 r(x), 잡음 묶음."""
    out = {"grid_mm": GRID.tolist(), "source_runs": [r[0] for r in runs]}
    base, bank = {}, {}
    use = ~JM
    for si, s in enumerate(("left", "right")):
        A = np.array([r[2 + si] for r in runs])
        med = np.nanmedian(A, axis=0)
        A[np.abs(A - med) > 0.8] = np.nan                  # 센서 이상 점 제거 (중앙값에서 0.8 mm 초과)
        mean = np.nanmean(A, axis=0); std = np.nanstd(A, axis=0, ddof=1) if len(runs) > 1 else np.zeros(N)
        H = float(np.nanmean(mean[use]))
        base[s] = mean
        dev = A - mean
        B = dev.copy(); B[:, JM] = np.nan
        for k in range(B.shape[0]):
            ok = np.isfinite(B[k])
            B[k] = np.interp(GRID, GRID[ok], B[k][ok]) if ok.sum() > 10 else 0.0
        bank[s] = B
        out[f"baseline_{s}"] = mean.tolist(); out[f"baseline_std_{s}"] = std.tolist(); out[f"H_{s}"] = H
        out[f"rshape_{s}"] = np.nan_to_num(mean - H).tolist()
    out["noise_bank"] = {s: bank[s].tolist() for s in bank}
    return out, base, bank


def change_signal(gL, gR, base):
    """격자 신호 − 기준선, 이음부 ±20 mm 는 0, 빈 곳은 0. (2, N) float32"""
    sig = []
    for g, s in ((gL, "left"), (gR, "right")):
        c = g - base[s]; c = np.where(np.isfinite(c), c, 0.0); c = np.where(JM, 0.0, c); sig.append(c)
    return np.stack(sig).astype(np.float32)


# ---------------- 가상 데이터 ----------------
def load_synth(dirs):
    X, man = [], []
    for p in dirs:
        mf = os.path.join(p, "manifest.csv")
        if not os.path.exists(mf):
            sys.exit(f"{p}: manifest.csv 가 없습니다. generate_dataset_v2.py 로 먼저 만드세요")
        m = pd.read_csv(mf); m["src"] = os.path.basename(os.path.normpath(p))
        for r in m.itertuples():
            X.append(at.signals_from_csv(os.path.join(p, "runs", r.file)))
        man.append(m)
    man = pd.concat(man, ignore_index=True); man["pid"] = man.src + "_" + man.placement_id.astype(str)
    return np.stack(X), man


# ---------------- 학습 (ai_train_v2.train 과 같음, 잡음 묶음·장치만 바깥에서 받는다) ----------------
def train(Xtr, Ytr, Xva, Yva, seed, real_bg, bank, device, epochs=40):
    torch.manual_seed(seed); rng = np.random.default_rng(seed)
    net = at.Net().to(device); opt = torch.optim.Adam(net.parameters(), lr=2e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    Xva_t = torch.tensor(v2t.masked(Xva)).to(device); Yva_t = torch.tensor(Yva).to(device)
    best = (1e9, None)
    for ep in range(epochs):
        net.train(); idx = rng.permutation(len(Xtr))
        for b in range(0, len(idx), 64):
            j = idx[b:b + 64]
            xb = at.augment(Xtr[j], rng, bank)
            for i in range(len(j)):                              # 절반에 실측 정상 배경 0.5~1.0 배, ±20 mm 밀어서
                if rng.random() < 0.5:
                    k = rng.integers(len(real_bg)); sh = rng.integers(-10, 11)
                    xb[i] += rng.uniform(0.5, 1.0) * np.roll(real_bg[k], sh, axis=1)
            loss = nn.functional.smooth_l1_loss(net(torch.tensor(v2t.masked(xb)).to(device)), torch.tensor(Ytr[j]).to(device))
            rb = real_bg[rng.integers(len(real_bg), size=8)].copy()  # 실측 정상이면 0 손실
            for i in range(len(rb)):
                rb[i] = np.roll(rb[i], rng.integers(-10, 11), axis=1) * rng.uniform(0.8, 1.2)
            loss = loss + 0.5 * nn.functional.smooth_l1_loss(net(torch.tensor(v2t.masked(rb).astype(np.float32)).to(device)), torch.zeros(len(rb), 2, device=device))
            opt.zero_grad(); loss.backward(); opt.step()
        sched.step()
        net.eval()
        with torch.no_grad():
            vl = nn.functional.smooth_l1_loss(net(Xva_t), Yva_t).item()
        if vl < best[0]:
            best = (vl, {k: v.detach().cpu().clone() for k, v in net.state_dict().items()})
    net = at.Net(); net.load_state_dict(best[1]); net.eval()       # 저장·추론은 CPU 로
    return net, best[0]


def predict(net, X, device="cpu"):
    net = net.to(device)
    with torch.no_grad():
        out = net(torch.tensor(v2t.masked(X).astype(np.float32)).to(device)).cpu().numpy()
    net.to("cpu")
    return out


def pick_device(name):
    """auto = cpu (이 크기의 모델은 CPU 로 충분하다). mps 는 Apple Silicon 에서 쓸 수 있을 때만."""
    if name == "mps":
        if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            return "mps"
        print("MPS 를 쓸 수 없어 CPU 로 돕니다")
    return "cpu"


# ---------------- 주 흐름 ----------------
def main():
    ap = argparse.ArgumentParser(description="새 정상 주행만으로 AI 재적응 → rail_ai_weights.npz")
    ap.add_argument("--normal-dir", required=True, help="correct_runs.py 로 보정한 새 정상 주행 폴더")
    ap.add_argument("--out", required=True, help="출력 폴더")
    ap.add_argument("--datasets", nargs="+", default=None, help="가상 데이터셋 폴더들 (기본 sim 옆의 ../dataset_v2 ../dataset_v2_seed9)")
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "mps"])
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--min-normals", type=int, default=5)
    a = ap.parse_args()
    a.normal_dir = os.path.normpath(os.path.join(CWD0, a.normal_dir)); a.out = os.path.normpath(os.path.join(CWD0, a.out))
    a.datasets = [os.path.normpath(os.path.join(CWD0, p)) for p in a.datasets] if a.datasets else [os.path.join(HERE, "..", "dataset_v2"), os.path.join(HERE, "..", "dataset_v2_seed9")]
    t0 = time.time(); os.makedirs(a.out, exist_ok=True)
    device = pick_device(a.device)
    L = [f"# AI 재적응 보고 ({time.strftime('%Y-%m-%d %H:%M')})", "",
         f"- 새 정상 폴더: `{os.path.abspath(a.normal_dir)}`", f"- 가상 데이터셋: {', '.join(a.datasets)}",
         f"- 장치: {device} (torch {torch.__version__}), 씨앗 {a.seed}, epoch {a.epochs}", ""]

    # 1. 새 정상 읽기
    runs = read_runs(a.normal_dir)
    if len(runs) < a.min_normals:
        sys.exit(f"새 정상 주행이 {len(runs)}회뿐입니다. {a.min_normals}회 이상 필요합니다")
    cal, base, bank = calibrate(runs)
    # 2. 센서 어긋남 검사 → 표시된 회차 제외 후 다시 교정
    flags = {r[0]: rail_ai.sensor_check(*change_signal(r[2], r[3], base)) for r in runs}
    usable = [r for r in runs if not flags[r[0]]]
    if len(usable) < len(runs):
        cal, base, bank = calibrate(usable)
    if len(usable) < a.min_normals:
        sys.exit(f"센서 점검으로 표시되지 않은 새 정상이 {len(usable)}회뿐입니다 ({a.min_normals}회 이상 필요). 정상 주행을 더 받아 주세요")
    cal["excluded_runs"] = [r[0] for r in runs if flags[r[0]]]
    with open(os.path.join(a.out, "calibration_new.json"), "w") as fp:
        json.dump(cal, fp)
    bank_np = {0: np.array(cal["noise_bank"]["left"]), 1: np.array(cal["noise_bank"]["right"])}
    real_sig = np.stack([change_signal(r[2], r[3], base) for r in usable])
    L += ["## 새 정상 주행", "", f"- 받은 정상 {len(runs)}회, 적응에 쓴 정상 {len(usable)}회",
          f"- 설치 높이 H 좌 {cal['H_left']:.3f} mm, 우 {cal['H_right']:.3f} mm; 회차 간 흔들림 1회 RMS 좌 {np.sqrt(np.nanmean(bank_np[0][:, ~JM]**2)):.3f} / 우 {np.sqrt(np.nanmean(bank_np[1][:, ~JM]**2)):.3f} mm",
          f"- 새 교정값: `{os.path.join(a.out, 'calibration_new.json')}` (원본 calibration.json 은 그대로)", ""]
    print(f"새 정상 {len(runs)}회 읽음, 센서 점검 표시 {len(runs) - len(usable)}회, {time.time()-t0:.0f}s", flush=True)

    # 3. 가상 데이터
    Xs, man = load_synth(a.datasets)
    Ys = np.stack([man.size_HF_mm.to_numpy(), man.size_C_mm.to_numpy()], 1).astype(np.float32)
    pids = man.pid.to_numpy(); uniq = np.unique(pids); rng = np.random.default_rng(1)
    va_p = set(rng.choice(uniq, size=len(uniq) // 5, replace=False)); va = np.array([p in va_p for p in pids]); tr = ~va
    Xr, _, truth = at.load_real()                     # 9/28 실측 18회 (원본 교정값 기준)
    r_names = list(truth.run); r_bid = {}
    for n in r_names:
        d = pd.read_csv(f"../data/{n}.csv", usecols=["boot_id"], nrows=1); r_bid[str(d.boot_id.iloc[0])] = n
    print(f"가상 {len(Xs)}회 (학습 {tr.sum()} / 검증 {va.sum()}), 9/28 실측 {len(Xr)}회 읽음, {time.time()-t0:.0f}s", flush=True)

    # 4. 1회씩 빼고 학습
    hold_pred = []; va_preds = []; real_preds = []; pt_files = []; loo_for_0928 = {}
    for k, r in enumerate(usable):
        real_bg = np.delete(real_sig, k, axis=0)
        net, vl = train(Xs[tr], Ys[tr], Xs[va], Ys[va], a.seed, real_bg, bank_np, device, a.epochs)
        ph = predict(net, real_sig[k:k + 1])[0]; hold_pred.append(ph)
        va_preds.append(predict(net, Xs[va])); pr = predict(net, Xr); real_preds.append(pr)
        if r[1] in r_bid:
            loo_for_0928[r_bid[r[1]]] = pr[r_names.index(r_bid[r[1]])]
        f = os.path.join(a.out, f"ai_cnn_adapt_hold_{k:02d}.pt"); torch.save(net.state_dict(), f); pt_files.append(f)
        print(f"[{k+1}/{len(usable)}] 뺀 회차 {r[0]}: 검증 손실 {vl:.4f}, 뺀 회차 추정 단차 {ph[0]:.2f} / 처짐 {ph[1]:.2f} mm, {time.time()-t0:.0f}s", flush=True)
    hold_pred = np.array(hold_pred)
    t_train = time.time() - t0

    # 5. npz 내보내기와 확인
    npz = os.path.join(a.out, "rail_ai_weights.npz")
    ew.export(pt_files, npz)
    diff1, ok1 = ew.check(npz, pt_files)                   # 9/28 18회
    diff2, ok2 = ew.check(npz, pt_files, a.normal_dir)     # 새 정상
    npz_ok = ok1 and ok2

    # 6. 결과 정리
    ok_hold = float(hold_pred.max()) <= PASS_HOLDOUT_MM
    n_flag = len(runs) - len(usable); ok_flag = n_flag == 0
    L += ["## ① 뺀 회차의 AI 추정 (학습에 안 쓴 새 정상 1회씩)", "", "| 뺀 회차 | 단차 mm | 처짐 mm | 판정 |", "|---|---|---|---|"]
    for r, p in zip(usable, hold_pred):
        kd, st = v2.rule(p[0], p[1]); L.append(f"| {r[0]} | {p[0]:.2f} | {p[1]:.2f} | {KR[kd]}·{ST[st]} |")
    L += ["", f"최댓값 단차 {hold_pred[:, 0].max():.2f} mm, 처짐 {hold_pred[:, 1].max():.2f} mm → **{'통과' if ok_hold else '실패'}** (기준 ≤ {PASS_HOLDOUT_MM} mm)", ""]
    L += ["## ② 새 정상의 센서 점검 표시", ""]
    for r in runs:
        L.append(f"- {r[0]}: {'센서 점검 ' + str(flags[r[0]]) if flags[r[0]] else '표시 없음'}")
    L += ["", f"표시 {n_flag}회 / {len(runs)}회 → **{'통과' if ok_flag else '실패'}** (기준 0)", ""]
    svs = [at.score(p[:, 0], p[:, 1], Ys[va, 0], Ys[va, 1], man.stage[va]) for p in va_preds]
    ens_va = np.mean(va_preds, 0); sv_e = at.score(ens_va[:, 0], ens_va[:, 1], Ys[va, 0], Ys[va, 1], man.stage[va])
    L += ["## ③ 가상 검증 묶음 (배치 단위로 떼어 둔 가상 주행)", "",
          f"- 검증 {va.sum()}회: 모델별 평균 종류 {np.mean([s['type_acc'] for s in svs])*100:.0f} %, 단계 {np.mean([s['stage_acc'] for s in svs])*100:.0f} %, "
          f"단차 RMSE {np.mean([s['rmse_HF'] for s in svs]):.2f}, 처짐 RMSE {np.mean([s['rmse_C'] for s in svs]):.2f} mm",
          f"- {len(pt_files)}개 모델 평균(서버가 쓰는 방식): 종류 {sv_e['type_acc']*100:.0f} %, 단계 {sv_e['stage_acc']*100:.0f} %", ""]
    # ④ 9/28 18회: 서버와 같은 numpy 추론. 새 정상과 boot_id 가 같은 회차는 그 회차를 뺀 모델의 추정을 쓴다
    ai = rail_ai.RailAI(npz)
    rows = []; ok_k = ok_s = ok_after = 0; pH = np.zeros(len(r_names)); pC = np.zeros(len(r_names))
    for i, n in enumerate(r_names):
        if n in loo_for_0928:
            p = loo_for_0928[n]; how = "뺀 모델"
        else:
            q = ai.predict(Xr[i][0], Xr[i][1]); p = (q["joint_step"], q["vertical"]); how = "앙상블"
        pH[i], pC[i] = p[0], p[1]
        kd, st = v2.rule(p[0], p[1]); sflag = bool(rail_ai.sensor_check(Xr[i][0], Xr[i][1]))
        tk, ts = truth.kind[i], truth.stage[i]
        ok_k += kd == tk; ok_s += st == ts; ok_after += (st == ts) or (sflag and tk == "normal")
        rows.append(f"| {n} | {KR[tk]} | {p[0]:.2f} | {p[1]:.2f} | {KR[kd]}·{ST[st]} | {'O' if kd == tk else 'X'} | {'O' if st == ts else 'X'} | {'센서 점검' if sflag else ''} | {how} |")
    hf = (truth.kind == "HF").to_numpy(); cc = (truth.kind == "C").to_numpy()
    L += ["## ④ 9/28 실측 18회 (참고: 펌웨어가 달라 정답 기준은 아니다)", "",
          "| 회차 | 정답 | 단차 mm | 처짐 mm | 판정 | 종류 | 단계 | 센서 | 추정에 쓴 모델 |", "|---|---|---|---|---|---|---|---|---|"] + rows
    L += ["", f"종류 {ok_k}/18, 단계 {ok_s}/18, 센서 검사 뒤 단계 {ok_after}/18. 단차 회차의 단차 크기 {pH[hf].mean():.2f} ± {pH[hf].std(ddof=1):.2f} mm, "
          f"처짐 회차의 처짐 크기 {pC[cc].mean():.2f} ± {pC[cc].std(ddof=1):.2f} mm (정답 2 mm)", ""]
    # MPS 확인
    if device == "mps":
        worst = 0.0
        for f in pt_files:
            net = at.Net(); net.load_state_dict(torch.load(f, map_location="cpu")); net.eval()
            for X in (real_sig, Xr):
                worst = max(worst, float(np.abs(predict(net, X, "cpu") - predict(net, X, "mps")).max()))
        L += [f"- MPS 와 CPU 추론 출력의 최대 차이 {worst:.2e} (학습은 MPS 로 했고, 저장·내보내기·서버 추론은 CPU 값)", ""]
    L += ["## npz 확인", "", f"- 9/28 18회: torch 와 numpy 최대 차이 {diff1:.2e}, 새 정상 {len(runs)}회: {diff2:.2e} → **{'통과' if npz_ok else '실패'}** (기준 < 1e-5)", ""]
    L += ["## ⑤ 걸린 시간", "", f"- 학습 {t_train/60:.1f}분 ({len(pt_files)}개 모델), 전체 {(time.time()-t0)/60:.1f}분", ""]
    all_ok = ok_hold and ok_flag and npz_ok
    L += ["## 결과", "", f"**{'통과' if all_ok else '실패'}** — ① {'통과' if ok_hold else '실패'}, ② {'통과' if ok_flag else '실패'}, npz {'통과' if npz_ok else '실패'}",
          "", f"만든 파일: `{npz}` (서버용, 레포 루트 rail_ai_weights.npz 로 복사), `calibration_new.json`, 모델 .pt {len(pt_files)}개, 이 보고서", ""]
    rep = os.path.join(a.out, "adapt_report.md"); open(rep, "w").write("\n".join(L))
    print("\n".join(L[L.index("## ① 뺀 회차의 AI 추정 (학습에 안 쓴 새 정상 1회씩)"):]))
    print(f"보고서 → {rep}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
