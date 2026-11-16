"""학습한 CNN 가중치(.pt 여러 개)를 서버용 rail_ai_weights.npz 로 내보내고, torch 와 numpy(rail_ai.py) 출력이 같은지 확인한다.

사용: python3 export_weights.py ai_cnn_v3_hold_*.pt --out ../../rail_ai_weights.npz
      (.pt 는 ai_train.Net 구조여야 한다. 여러 개를 주면 rail_ai.py 가 평균하는 앙상블이 된다.)
      내보낸 뒤 바로 ../data/c[123]_r*.csv 실측 18회로 torch 출력과 numpy 출력의 최대 차이를 찍는다.
      최대 차이 < 1e-5 면 "통과", 아니면 "실패" 를 찍고 종료 코드 1.

확인만: python3 export_weights.py --check ../../rail_ai_weights.npz ai_cnn_v3_hold_*.pt
다른 실측 폴더로 확인: --data <보정본 폴더>  (그 안의 *.csv 전부, rail_x_mm·analysis_window·sensor_valid 열이 있어야 한다)

npz 키: n_models, m{i}/c{blk}.w .b .g .beta .m .v (blk 0~3 = 합성곱 블록, w·b 합성곱, g·beta·m·v 배치 정규화), m{i}/l0.w .b, m{i}/l1.w .b
"""
import argparse, glob, os, sys
import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__)); CWD0 = os.getcwd()
sys.path.insert(0, HERE)
os.chdir(HERE)                 # ai_train → sim2real 이 calibration.json, ../data 를 이 폴더 기준으로 읽는다
import ai_train as at          # Net 구조, 실측 읽기
import ai_train_v2 as v2t      # masked()
import rail_ai                 # numpy 추론

TOL = 1e-5


def export(pt_files, out):
    out_dict = {"n_models": np.array(len(pt_files))}
    for i, f in enumerate(pt_files):
        sd = torch.load(f, map_location="cpu")
        for blk, idx in enumerate((0, 2, 4, 6)):            # Sequential 인덱스: 합성곱 블록 0,2,4,6 (안에서 0=conv, 1=bn)
            out_dict[f"m{i}/c{blk}.w"] = sd[f"f.{idx}.0.weight"].numpy(); out_dict[f"m{i}/c{blk}.b"] = sd[f"f.{idx}.0.bias"].numpy()
            out_dict[f"m{i}/c{blk}.g"] = sd[f"f.{idx}.1.weight"].numpy(); out_dict[f"m{i}/c{blk}.beta"] = sd[f"f.{idx}.1.bias"].numpy()
            out_dict[f"m{i}/c{blk}.m"] = sd[f"f.{idx}.1.running_mean"].numpy(); out_dict[f"m{i}/c{blk}.v"] = sd[f"f.{idx}.1.running_var"].numpy()
        out_dict[f"m{i}/l0.w"] = sd["f.9.weight"].numpy(); out_dict[f"m{i}/l0.b"] = sd["f.9.bias"].numpy()
        out_dict[f"m{i}/l1.w"] = sd["f.12.weight"].numpy(); out_dict[f"m{i}/l1.b"] = sd["f.12.bias"].numpy()
    np.savez_compressed(out, **out_dict)
    print(f"{len(pt_files)}개 모델 → {out} ({os.path.getsize(out)//1024} KB)")


def load_signals(data_dir=None):
    """실측 변화 신호 (n, 2, 601). data_dir 가 없으면 ../data/c[123]_r*.csv (9/28 실측 18회)."""
    if data_dir is None:
        Xr, _, truth = at.load_real()
        return Xr, list(truth.run)
    files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    files = [f for f in files if not os.path.basename(f).startswith("보정_기록")]
    X = [at.signals_from_csv(f, real=True) for f in files]
    return np.stack(X), [os.path.basename(f) for f in files]


def check(npz, pt_files, data_dir=None):
    """torch 앙상블 출력과 rail_ai(numpy) 출력의 최대 차이. 돌려주는 값: (최대 차이, 통과 여부)."""
    ai = rail_ai.RailAI(npz)
    nets = []
    for f in pt_files:
        n = at.Net(); n.load_state_dict(torch.load(f, map_location="cpu")); n.eval(); nets.append(n)
    Xr, names = load_signals(data_dir)
    worst = 0.0
    for i in range(len(Xr)):
        with torch.no_grad():
            t = np.mean([n(torch.tensor(v2t.masked(Xr[i][None]))).numpy()[0] for n in nets], 0)
        p = ai.predict(Xr[i][0], Xr[i][1])
        worst = max(worst, abs(p["joint_step"] - t[0]), abs(p["vertical"] - t[1]))
    ok = worst < TOL
    print(f"실측 {len(Xr)}회에서 torch 와 numpy 의 최대 차이 {worst:.2e} → {'통과' if ok else '실패'} (기준 < {TOL:g})")
    return worst, ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pt", nargs="+", help=".pt 파일들 (glob 가능)")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "..", "rail_ai_weights.npz"))
    ap.add_argument("--check", metavar="NPZ", help="내보내지 않고, 이 npz 와 .pt 출력을 비교만 한다")
    ap.add_argument("--data", help="확인에 쓸 실측 보정본 폴더 (기본 ../data 의 9/28 18회)")
    ap.add_argument("--no-check", action="store_true", help="내보내기만 하고 확인은 건너뛴다")
    a = ap.parse_args()
    fix = lambda p: os.path.normpath(os.path.join(CWD0, p)) if p else p          # 명령줄 경로는 원래 폴더 기준
    a.out = fix(a.out); a.check = fix(a.check); a.data = fix(a.data)
    files = sorted(sum([glob.glob(fix(p)) for p in a.pt], []))
    if not files:
        sys.exit("pt 파일이 없습니다")
    if a.check:
        _, ok = check(a.check, files, a.data)
    else:
        export(files, a.out)
        ok = True if a.no_check else check(a.out, files, a.data)[1]
    sys.exit(0 if ok else 1)
