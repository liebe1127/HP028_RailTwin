"""
합성 데이터 RBF 학습 결과를 개발보고서용 PNG로 내보낸다.

실행:
  python3 ml/export_synthetic_training_figures.py

산출물은 모두 “합성 데이터”로 표기한다. 실측 정확도 증거가 아니다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import torch
from matplotlib import font_manager, patches
from matplotlib.gridspec import GridSpec

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from ml.train_rbf_surrogate import (  # noqa: E402
    FEATURE_NAMES,
    NUM_EPOCHS,
    SEED,
    WINDOW_LEN,
    _synthetic_windows,
    crest_factor,
    train,
    wavelet_denoise,
)

OUT_DIR = ROOT / "docs"
BANNER = "합성 데이터 · 파이프라인 검증용 (실측 정확도 증거가 아님)"
FEATURE_LABELS = {
    "accel_rms": "가속도 RMS",
    "accel_peak_to_peak": "가속도 Peak-to-Peak",
    "crest_factor": "파고율 Crest",
    "gyro_rms": "자이로 RMS",
    "gyro_peak": "자이로 Peak",
    "distance_mean_mm": "거리 평균 (mm)",
    "distance_delta_mm": "거리 편차 (mm)",
    "distance_std_mm": "거리 표준편차 (mm)",
    "speed_mm_s": "속도 (mm/s)",
}

NAVY = "#0f2744"
AMBER = "#c2410c"
BLUE = "#1d4ed8"
TEAL = "#0f766e"
SLATE = "#334155"
MUTED = "#64748b"
PANEL = "#f8fafc"


def _setup_font() -> str:
    candidates = [
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/AppleGothic.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                font_manager.fontManager.addfont(path)
            except Exception:
                pass
    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in ("AppleGothic", "Apple SD Gothic Neo", "NanumGothic"):
        if name in available:
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return name
    plt.rcParams["axes.unicode_minus"] = False
    return "sans-serif"


def _stamp(fig: plt.Figure, extra: str = "") -> None:
    text = BANNER if not extra else f"{BANNER}  |  {extra}"
    fig.text(
        0.5,
        0.012,
        text,
        ha="center",
        va="bottom",
        fontsize=9,
        color=AMBER,
        fontweight="bold",
    )


def _title_block(ax: plt.Axes, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=12, color=NAVY, fontweight="bold", pad=10)


def _save(fig: plt.Figure, name: str) -> Path:
    path = OUT_DIR / name
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def plot_loss_curve(result: dict) -> Path:
    fig, ax = plt.subplots(figsize=(9.2, 4.8))
    fig.patch.set_facecolor("white")
    ax.plot(result["epochs"], result["train_losses"], color=BLUE, lw=2.0, label="train_loss")
    ax.plot(result["epochs"], result["val_losses"], color=AMBER, lw=2.0, label="val_loss")
    ax.set_xlabel("Epoch")
    ax.set_ylabel("MSE (정규화 타겟)")
    _title_block(ax, "RBF 대리 모델 학습 손실 곡선")
    ax.grid(True, alpha=0.35)
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xlim(1, NUM_EPOCHS)
    last_tr = result["train_losses"][-1]
    last_va = result["val_losses"][-1]
    ax.annotate(
        f"최종 train={last_tr:.4f}\n최종 val={last_va:.4f}",
        xy=(NUM_EPOCHS, last_va),
        xytext=(0.72, 0.62),
        textcoords="axes fraction",
        fontsize=9,
        color=SLATE,
        arrowprops=dict(arrowstyle="->", color=MUTED),
    )
    _stamp(fig)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    return _save(fig, "rbf-synthetic-loss-curve.png")


def plot_feature_distributions(x: torch.Tensor) -> Path:
    values = x.numpy()
    fig, axes = plt.subplots(3, 3, figsize=(11.2, 8.4))
    fig.patch.set_facecolor("white")
    fig.suptitle("RBF 입력 9개 특징 분포", fontsize=14, color=NAVY, fontweight="bold", x=0.02, ha="left")
    colors = [BLUE, TEAL, AMBER, BLUE, TEAL, AMBER, BLUE, TEAL, AMBER]
    for index, (ax, name, color) in enumerate(zip(axes.ravel(), FEATURE_NAMES, colors)):
        ax.hist(values[:, index], bins=28, color=color, alpha=0.82, edgecolor="white")
        ax.set_title(FEATURE_LABELS[name], fontsize=10, color=NAVY)
        ax.tick_params(labelsize=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    _stamp(fig)
    return _save(fig, "rbf-synthetic-feature-distributions.png")


def plot_feature_comparison() -> Path:
    np.random.seed(SEED)
    cases = [
        ("정상 주행 (severity ≈ 0.08)", 0.08, TEAL),
        ("단차 충격 (severity ≈ 0.85)", 0.85, AMBER),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11.2, 7.2), sharex="col")
    fig.patch.set_facecolor("white")
    fig.suptitle(
        "특징 비교: 웨이블릿 디노이징 전·후와 파고율",
        fontsize=14,
        color=NAVY,
        fontweight="bold",
        x=0.02,
        ha="left",
    )

    for row, (title, severity, color) in enumerate(cases):
        accel, _gyro, distance = _synthetic_windows(severity)
        accel_d = wavelet_denoise(accel)
        dist_d = wavelet_denoise(distance)
        t = np.arange(WINDOW_LEN)
        crest_dn = crest_factor(accel_d)
        rms_dn = float(np.sqrt(np.mean(accel_d ** 2))) if accel_d.size else 0.0

        ax_a = axes[row, 0]
        ax_a.plot(t, accel, color=MUTED, lw=1.2, alpha=0.85, label="원시 가속도")
        ax_a.plot(t, accel_d, color=color, lw=2.0, label="sym3 디노이징")
        ax_a.set_ylabel("a_dyn")
        ax_a.set_title(
            f"{title}  ·  Crest {crest_dn:.2f}  RMS {rms_dn:.3f}",
            fontsize=10,
            color=NAVY,
        )
        ax_a.legend(frameon=False, fontsize=8)
        ax_a.grid(True, alpha=0.3)
        ax_a.spines["top"].set_visible(False)
        ax_a.spines["right"].set_visible(False)

        ax_d = axes[row, 1]
        ax_d.plot(t, distance, color=MUTED, lw=1.2, alpha=0.85, label="원시 거리")
        ax_d.plot(t, dist_d, color=BLUE, lw=2.0, label="sym3 디노이징")
        ax_d.set_ylabel("mm")
        ax_d.set_title("LR18 거리 창", fontsize=10, color=NAVY)
        ax_d.legend(frameon=False, fontsize=8)
        ax_d.grid(True, alpha=0.3)
        ax_d.spines["top"].set_visible(False)
        ax_d.spines["right"].set_visible(False)

    axes[1, 0].set_xlabel("샘플 (32-window)")
    axes[1, 1].set_xlabel("샘플 (32-window)")
    fig.tight_layout(rect=(0, 0.05, 1, 0.93))
    _stamp(fig)
    return _save(fig, "rbf-synthetic-feature-comparison.png")


def plot_pred_vs_target(result: dict) -> Path:
    device = torch.device(result["device"])
    model = result["model"]
    model.eval()
    with torch.no_grad():
        y_hat_norm = model(result["x_norm"].to(device)).cpu()
    y_true = result["y"].numpy().ravel()
    y_hat = (y_hat_norm * result["y_std"] + result["y_mean"]).numpy().ravel()
    mae = float(np.mean(np.abs(y_hat - y_true)))
    rmse = float(np.sqrt(np.mean((y_hat - y_true) ** 2)))

    fig, ax = plt.subplots(figsize=(6.8, 6.2))
    fig.patch.set_facecolor("white")
    ax.scatter(y_true, y_hat, s=12, alpha=0.35, color=BLUE, linewidths=0)
    lo = float(min(y_true.min(), y_hat.min()))
    hi = float(max(y_true.max(), y_hat.max()))
    ax.plot([lo, hi], [lo, hi], color=AMBER, lw=1.6, label="y = x")
    ax.set_xlabel("합성 타겟 rail_deform")
    ax.set_ylabel("RBF 추론 pred_rail_deform")
    _title_block(ax, "합성 검증: 타겟 대비 추론값")
    ax.grid(True, alpha=0.3)
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.text(
        0.04,
        0.96,
        f"MAE={mae:.3f}   RMSE={rmse:.3f}\n합성 데이터 내부 적합이며 실측 성능이 아님",
        transform=ax.transAxes,
        va="top",
        fontsize=9,
        color=AMBER,
        fontweight="bold",
    )
    _stamp(fig)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    return _save(fig, "rbf-synthetic-pred-vs-target.png")


def _korean_font() -> str:
    family = plt.rcParams.get("font.family", "AppleGothic")
    if isinstance(family, (list, tuple)):
        return str(family[0])
    return str(family)


def plot_training_log(result: dict) -> Path:
    font_name = _korean_font()
    lines = []
    for line in result["log_lines"]:
        if "모델 가중치 저장 완료" in line:
            lines.append("[OK] 모델 가중치 저장 완료 → rbf_dummy_model.pth")
        else:
            lines.append(line)
    fig = plt.figure(figsize=(10.4, 7.8))
    fig.patch.set_facecolor("#0b1220")
    ax = fig.add_axes((0.05, 0.08, 0.90, 0.82))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(
        patches.FancyBboxPatch(
            (0.0, 0.0),
            1.0,
            1.0,
            boxstyle="round,pad=0.012,rounding_size=0.02",
            facecolor="#111827",
            edgecolor="#334155",
            linewidth=1.4,
        )
    )
    ax.text(
        0.03,
        0.955,
        "RBF 학습 로그  ·  python3 ml/train_rbf_surrogate.py",
        color="#f8fafc",
        fontsize=12,
        fontweight="bold",
        va="top",
        fontfamily=font_name,
    )
    ax.text(
        0.03,
        0.905,
        BANNER,
        color="#fb923c",
        fontsize=10,
        fontweight="bold",
        va="top",
        fontfamily=font_name,
    )
    body = "\n".join(lines)
    ax.text(
        0.03,
        0.86,
        body,
        color="#86efac",
        fontsize=9.6,
        va="top",
        fontfamily=font_name,
        linespacing=1.48,
    )
    fig.text(
        0.5,
        0.025,
        BANNER,
        ha="center",
        color="#fb923c",
        fontsize=9,
        fontweight="bold",
        fontfamily=font_name,
    )
    path = OUT_DIR / "rbf-synthetic-training-log.png"
    fig.savefig(path, dpi=200, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


def plot_evidence_sheet(result: dict, pred_stats: tuple[float, float]) -> Path:
    mae, rmse = pred_stats
    fig = plt.figure(figsize=(12.6, 8.6))
    fig.patch.set_facecolor("white")
    gs = GridSpec(2, 2, figure=fig, height_ratios=(1.05, 1.15), hspace=0.38, wspace=0.28)

    ax_loss = fig.add_subplot(gs[0, 0])
    ax_loss.plot(result["epochs"], result["train_losses"], color=BLUE, lw=2.0, label="train_loss")
    ax_loss.plot(result["epochs"], result["val_losses"], color=AMBER, lw=2.0, label="val_loss")
    ax_loss.set_xlabel("Epoch")
    ax_loss.set_ylabel("MSE")
    ax_loss.set_title("학습 손실", loc="left", color=NAVY, fontweight="bold")
    ax_loss.grid(True, alpha=0.3)
    ax_loss.legend(frameon=False, fontsize=8)
    ax_loss.spines["top"].set_visible(False)
    ax_loss.spines["right"].set_visible(False)

    device = torch.device(result["device"])
    model = result["model"]
    model.eval()
    with torch.no_grad():
        y_hat_norm = model(result["x_norm"].to(device)).cpu()
    y_true = result["y"].numpy().ravel()
    y_hat = (y_hat_norm * result["y_std"] + result["y_mean"]).numpy().ravel()
    ax_sc = fig.add_subplot(gs[0, 1])
    ax_sc.scatter(y_true, y_hat, s=8, alpha=0.3, color=BLUE, linewidths=0)
    lo = float(min(y_true.min(), y_hat.min()))
    hi = float(max(y_true.max(), y_hat.max()))
    ax_sc.plot([lo, hi], [lo, hi], color=AMBER, lw=1.4)
    ax_sc.set_xlabel("합성 타겟")
    ax_sc.set_ylabel("pred_rail_deform")
    ax_sc.set_title("타겟 대비 추론", loc="left", color=NAVY, fontweight="bold")
    ax_sc.grid(True, alpha=0.3)
    ax_sc.spines["top"].set_visible(False)
    ax_sc.spines["right"].set_visible(False)
    ax_sc.text(
        0.04,
        0.96,
        f"MAE={mae:.3f}  RMSE={rmse:.3f}",
        transform=ax_sc.transAxes,
        va="top",
        fontsize=8,
        color=AMBER,
        fontweight="bold",
    )

    ax_feat = fig.add_subplot(gs[1, :])
    values = result["x"].numpy()
    crest = values[:, FEATURE_NAMES.index("crest_factor")]
    delta = np.abs(values[:, FEATURE_NAMES.index("distance_delta_mm")])
    ax_feat.scatter(crest, delta, s=10, alpha=0.28, color=TEAL, linewidths=0)
    ax_feat.set_xlabel("파고율 Crest Factor")
    ax_feat.set_ylabel("|거리 편차| (mm)")
    ax_feat.set_title("특징 비교: 파고율 vs 거리 편차", loc="left", color=NAVY, fontweight="bold")
    ax_feat.grid(True, alpha=0.3)
    ax_feat.spines["top"].set_visible(False)
    ax_feat.spines["right"].set_visible(False)

    fig.suptitle(
        "특징 공학 · RBF 추론 결과 요약",
        fontsize=16,
        color=NAVY,
        fontweight="bold",
        x=0.03,
        ha="left",
        y=0.98,
    )
    _stamp(fig)
    fig.subplots_adjust(left=0.07, right=0.98, top=0.88, bottom=0.10, hspace=0.42, wspace=0.28)
    return _save(fig, "rbf-synthetic-training-evidence.png")


def write_log_text(result: dict, mae: float, rmse: float) -> Path:
    path = OUT_DIR / "rbf-synthetic-training-log.txt"
    extra = [
        "",
        f"[INFO] 합성 내부 적합 MAE={mae:.5f}  RMSE={rmse:.5f}",
        "[INFO] 위 MAE/RMSE는 합성 타겟에 대한 값이며 실측 성능이 아님",
    ]
    path.write_text("\n".join(result["log_lines"] + extra) + "\n", encoding="utf-8")
    return path


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    font_name = _setup_font()
    print(f"[INFO] matplotlib font={font_name}")
    result = train(save_path="rbf_dummy_model.pth")

    device = torch.device(result["device"])
    result["model"].eval()
    with torch.no_grad():
        y_hat_norm = result["model"](result["x_norm"].to(device)).cpu()
    y_true = result["y"].numpy().ravel()
    y_hat = (y_hat_norm * result["y_std"] + result["y_mean"]).numpy().ravel()
    mae = float(np.mean(np.abs(y_hat - y_true)))
    rmse = float(np.sqrt(np.mean((y_hat - y_true) ** 2)))

    paths = [
        plot_loss_curve(result),
        plot_feature_distributions(result["x"]),
        plot_feature_comparison(),
        plot_pred_vs_target(result),
        plot_training_log(result),
        plot_evidence_sheet(result, (mae, rmse)),
        write_log_text(result, mae, rmse),
    ]
    print("[OK] 보고서용 산출물:")
    for path in paths:
        print(f"     {path}")


if __name__ == "__main__":
    main()
