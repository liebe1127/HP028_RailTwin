"""
train_rbf_surrogate.py
갠트리 크레인 하부 주행 레일 변형(단차·침하·뒤틀림) 예측 — RBF 대리 모델 학습 스크립트

실제 센서 데이터가 모이기 전, 파이프라인(데이터 → 특징 추출 → 모델 → 추론) 검증용으로
더미 입력 / 더미 타겟(레일 변형 지표)을 생성하고 RBF 신경망을 학습한다.

입력 피처 (11개):
  AAX, AAY, AAZ  : ADXL345 가속도 (m/s²)
  DIST           : HC-SR04 거리 (cm)
  MAX, MAY, MAZ  : MPU-6050 가속도 (m/s²)
  GX, GY, GZ     : MPU-6050 자이로 (rad/s)
  CREST          : 웨이블릿(sym3) 디노이징 후 파고율 (Crest Factor)

실행:
  python ml/train_rbf_surrogate.py
"""

from __future__ import annotations

import numpy as np
import pywt
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset, random_split

# ─────────────────────────────────────────────
#  설정값
# ─────────────────────────────────────────────
SEED = 42
NUM_SAMPLES = 1500        # 더미 데이터 세트 수 (1000~2000 범위)
WINDOW_LEN = 32           # 웨이블릿/파고율 계산용 가속도 윈도우 길이
INPUT_DIM = 11            # 센서 10개 + CREST 1개
NUM_CENTERS = 64          # RBF 중심(center) 개수
OUTPUT_DIM = 1            # 레일 변형 지표 (스칼라)

BATCH_SIZE = 32
NUM_EPOCHS = 200
LEARNING_RATE = 1e-3
VAL_SPLIT = 0.15

MODEL_SAVE_PATH = "rbf_dummy_model.pth"
WAVELET_NAME = "sym3"

# 원시 센서 키 (CREST는 특징 공학으로 파생)
SENSOR_FEATURE_NAMES = ["AAX", "AAY", "AAZ", "DIST", "MAX", "MAY", "MAZ", "GX", "GY", "GZ"]
FEATURE_NAMES = SENSOR_FEATURE_NAMES + ["CREST"]

torch.manual_seed(SEED)
np.random.seed(SEED)


# ─────────────────────────────────────────────
#  특징 공학: 웨이블릿 디노이징 + 파고율
# ─────────────────────────────────────────────
def wavelet_denoise(signal: np.ndarray, wavelet: str = WAVELET_NAME) -> np.ndarray:
    """
    sym3 웨이블릿으로 고주파 노이즈를 제거한다.
    계수가 너무 짧으면 원본을 그대로 반환한다.
    """
    x = np.asarray(signal, dtype=np.float64).ravel()
    if x.size < 4:
        return x.copy()

    try:
        max_level = pywt.dwt_max_level(x.size, pywt.Wavelet(wavelet).dec_len)
        level = max(1, min(3, max_level))
        coeffs = pywt.wavedec(x, wavelet, level=level)
        # 상세 계수(고주파)만 soft-thresholding
        sigma = np.median(np.abs(coeffs[-1])) / 0.6745 if coeffs[-1].size else 0.0
        uthresh = sigma * np.sqrt(2.0 * np.log(max(x.size, 2)))
        denoised_coeffs = [coeffs[0]]
        for detail in coeffs[1:]:
            denoised_coeffs.append(pywt.threshold(detail, value=uthresh, mode="soft"))
        restored = pywt.waverec(denoised_coeffs, wavelet)
        return restored[: x.size]
    except Exception:
        return x.copy()


def crest_factor(signal: np.ndarray) -> float:
    """파고율 Crest factor = peak(|x|) / RMS(x)."""
    x = np.asarray(signal, dtype=np.float64).ravel()
    if x.size == 0:
        return 0.0
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(x ** 2)))
    if rms < 1e-9:
        return 0.0
    return peak / rms


def accel_dynamic_magnitude(
    aax: float, aay: float, aaz: float,
    max_: float, may: float, maz: float,
) -> float:
    """중력 성분을 대략 제거한 가속도 진폭 (레일 충격 민감)."""
    adxl = np.sqrt(aax ** 2 + aay ** 2 + (aaz - 9.8) ** 2)
    mpu = np.sqrt(max_ ** 2 + may ** 2 + (maz - 9.8) ** 2)
    return float(0.5 * (adxl + mpu))


def compute_crest_from_window(accel_window: np.ndarray) -> float:
    """가속도 윈도우 → 웨이블릿 디노이징 → 파고율."""
    denoised = wavelet_denoise(accel_window)
    return crest_factor(denoised)


# ─────────────────────────────────────────────
#  1. 더미 데이터 생성
# ─────────────────────────────────────────────
def _synthetic_accel_window(base_mag: float, impact: float) -> np.ndarray:
    """레일 단차 충격을 모사한 짧은 가속도 윈도우 + 고주파 노이즈."""
    t = np.linspace(0.0, 1.0, WINDOW_LEN, endpoint=False)
    # 충격 펄스 (초반) + 잔진동
    pulse = impact * np.exp(-12.0 * t) * np.sin(2.0 * np.pi * 8.0 * t)
    baseline = base_mag * (0.3 + 0.1 * np.sin(2.0 * np.pi * 1.5 * t))
    noise = np.random.normal(0.0, 0.15, size=WINDOW_LEN)
    return baseline + pulse + noise


def generate_dummy_dataset(num_samples: int) -> tuple[torch.Tensor, torch.Tensor]:
    """
    센서 특성에 맞는 범위의 난수로 10차원 원시 입력을 만들고,
    각 샘플마다 합성 가속도 윈도우로 CREST를 계산해 11차원 입력을 구성한다.
    타겟(레일 변형 지표)은 비선형 수식 + 가우시안 노이즈로 생성한다.
    """
    aax = np.random.normal(loc=0.0, scale=2.0, size=num_samples)
    aay = np.random.normal(loc=0.0, scale=2.0, size=num_samples)
    aaz = np.random.normal(loc=9.8, scale=1.5, size=num_samples)
    dist = np.random.uniform(low=10.0, high=300.0, size=num_samples)
    max_ = np.random.normal(loc=0.0, scale=2.0, size=num_samples)
    may = np.random.normal(loc=0.0, scale=2.0, size=num_samples)
    maz = np.random.normal(loc=9.8, scale=1.5, size=num_samples)
    gx = np.random.normal(loc=0.0, scale=0.3, size=num_samples)
    gy = np.random.normal(loc=0.0, scale=0.3, size=num_samples)
    gz = np.random.normal(loc=0.0, scale=0.3, size=num_samples)

    crest = np.zeros(num_samples, dtype=np.float64)
    for i in range(num_samples):
        base_mag = accel_dynamic_magnitude(aax[i], aay[i], aaz[i], max_[i], may[i], maz[i])
        # 거리(팁 쪽 하중)와 연동된 충격 강도 → 레일 단차 특징 모사
        impact = 0.5 + 0.02 * (300.0 - dist[i]) / 50.0 + 0.3 * np.random.rand()
        window = _synthetic_accel_window(base_mag, impact)
        crest[i] = compute_crest_from_window(window)

    inputs = np.stack(
        [aax, aay, aaz, dist, max_, may, maz, gx, gy, gz, crest], axis=1
    )

    adxl_mag = np.sqrt(aax ** 2 + aay ** 2 + (aaz - 9.8) ** 2)
    mpu_mag = np.sqrt(max_ ** 2 + may ** 2 + (maz - 9.8) ** 2)
    gyro_mag = np.sqrt(gx ** 2 + gy ** 2 + gz ** 2)
    noise = np.random.normal(loc=0.0, scale=0.5, size=num_samples)

    # 파고율이 클수록 레일 단차 충격이 크다고 가정해 레일 변형 지표에 반영
    rail_deform = (
        0.8 * adxl_mag
        + 0.5 * mpu_mag
        + 3.0 * gyro_mag
        + 0.05 * (300.0 - dist)
        + 0.6 * crest
        + noise
    )
    rail_deform = np.clip(rail_deform, a_min=0.0, a_max=None)

    x = torch.tensor(inputs, dtype=torch.float32)
    y = torch.tensor(rail_deform, dtype=torch.float32).unsqueeze(1)
    return x, y


# ─────────────────────────────────────────────
#  2. RBF 층 및 대리 모델 정의
# ─────────────────────────────────────────────
class RBFLayer(nn.Module):
    """
    가우시안 RBF 층.
      phi_j(x) = exp(-||x - c_j||^2 / (2 * sigma_j^2))
    """

    def __init__(self, in_features: int, num_centers: int):
        super().__init__()
        self.in_features = in_features
        self.num_centers = num_centers
        self.centers = nn.Parameter(torch.randn(num_centers, in_features))
        self.log_sigmas = nn.Parameter(torch.zeros(num_centers))

    def init_centers_from_data(self, x: torch.Tensor) -> None:
        idx = torch.randperm(x.size(0))[: self.num_centers]
        with torch.no_grad():
            self.centers.copy_(x[idx])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.unsqueeze(1)
        centers = self.centers.unsqueeze(0)
        dist_sq = torch.sum((x - centers) ** 2, dim=-1)
        sigmas = F.softplus(self.log_sigmas) + 1e-3
        return torch.exp(-dist_sq / (2 * sigmas ** 2))


class RBFSurrogateModel(nn.Module):
    """RBF 대리 모델: 11차원 입력(센서+CREST) → RBF → 선형 → 레일 변형 지표 1차원."""

    def __init__(
        self,
        input_dim: int = INPUT_DIM,
        num_centers: int = NUM_CENTERS,
        output_dim: int = OUTPUT_DIM,
    ):
        super().__init__()
        self.rbf = RBFLayer(input_dim, num_centers)
        self.output_layer = nn.Linear(num_centers, output_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.output_layer(self.rbf(x))


# ─────────────────────────────────────────────
#  3. 디바이스 선택 (MPS / CUDA / CPU)
# ─────────────────────────────────────────────
def get_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


# ─────────────────────────────────────────────
#  4. 학습 루프
# ─────────────────────────────────────────────
def train() -> None:
    device = get_device()
    print(f"[INFO] 사용 디바이스: {device}")
    print(f"[INFO] 입력 차원={INPUT_DIM}  피처={FEATURE_NAMES}")

    x, y = generate_dummy_dataset(NUM_SAMPLES)

    x_mean, x_std = x.mean(dim=0, keepdim=True), x.std(dim=0, keepdim=True) + 1e-6
    y_mean, y_std = y.mean(), y.std() + 1e-6
    x_norm = (x - x_mean) / x_std
    y_norm = (y - y_mean) / y_std

    dataset = TensorDataset(x_norm, y_norm)
    val_size = int(len(dataset) * VAL_SPLIT)
    train_size = len(dataset) - val_size
    train_set, val_set = random_split(
        dataset, [train_size, val_size], generator=torch.Generator().manual_seed(SEED)
    )

    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=BATCH_SIZE, shuffle=False)

    model = RBFSurrogateModel().to(device)
    model.rbf.init_centers_from_data(x_norm.to(device))

    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)

    for epoch in range(1, NUM_EPOCHS + 1):
        model.train()
        train_loss = 0.0
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * xb.size(0)
        train_loss /= train_size

        if epoch % 20 == 0 or epoch == 1:
            model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for xb, yb in val_loader:
                    xb, yb = xb.to(device), yb.to(device)
                    val_loss += criterion(model(xb), yb).item() * xb.size(0)
            val_loss /= max(val_size, 1)
            print(
                f"[Epoch {epoch:4d}/{NUM_EPOCHS}] "
                f"train_loss={train_loss:.5f}  val_loss={val_loss:.5f}"
            )

    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "input_dim": INPUT_DIM,
            "num_centers": NUM_CENTERS,
            "output_dim": OUTPUT_DIM,
            "feature_names": FEATURE_NAMES,
            "x_mean": x_mean,
            "x_std": x_std,
            "y_mean": y_mean,
            "y_std": y_std,
        },
        MODEL_SAVE_PATH,
    )
    print(f"[OK] 모델 가중치 저장 완료 → {MODEL_SAVE_PATH}")


if __name__ == "__main__":
    train()
