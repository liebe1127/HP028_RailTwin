"""
train_rbf_surrogate.py
갠트리 크레인 하부 주행 레일 변형(단차·침하·뒤틀림) 예측 — RBF 대리 모델 학습 스크립트

실제 센서 데이터가 모이기 전, 파이프라인(데이터 → 특징 추출 → 모델 → 추론) 검증용으로
더미 입력 / 더미 타겟(레일 변형 지표)을 생성하고 RBF 신경망을 학습한다.

입력 피처 (9개, 모두 롤링 윈도우 특징):
  accel_rms, accel_peak_to_peak, crest_factor
  gyro_rms, gyro_peak
  distance_mean_mm, distance_delta_mm, distance_std_mm
  speed_mm_s

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
NUM_SAMPLES = 1500        # 합성 데이터 세트 수 (파이프라인 검증용)
WINDOW_LEN = 32           # 웨이블릿/파고율 계산용 가속도 윈도우 길이
FEATURE_NAMES = [
    "accel_rms",
    "accel_peak_to_peak",
    "crest_factor",
    "gyro_rms",
    "gyro_peak",
    "distance_mean_mm",
    "distance_delta_mm",
    "distance_std_mm",
    "speed_mm_s",
]
INPUT_DIM = len(FEATURE_NAMES)
NUM_CENTERS = 64          # RBF 중심(center) 개수
OUTPUT_DIM = 1            # 레일 변형 지표 (스칼라)

BATCH_SIZE = 32
NUM_EPOCHS = 200
LEARNING_RATE = 1e-3
VAL_SPLIT = 0.15

MODEL_SAVE_PATH = "rbf_dummy_model.pth"
WAVELET_NAME = "sym3"
G_MS2 = 9.80665

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
        if max_level < 1:
            return x.copy()
        level = min(3, max_level)
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


def dynamic_accel_magnitude(ax: float, ay: float, az: float) -> float:
    """MPU6050 가속도 벡터 크기에서 중력 크기를 제거한 동적 진폭."""
    magnitude = np.sqrt(ax ** 2 + ay ** 2 + az ** 2)
    return float(abs(magnitude - G_MS2))


def gyro_magnitude(gx: float, gy: float, gz: float) -> float:
    """MPU6050 자이로 3축 벡터 크기."""
    return float(np.sqrt(gx ** 2 + gy ** 2 + gz ** 2))


def compute_crest_from_window(accel_window: np.ndarray) -> float:
    """가속도 윈도우 → 웨이블릿 디노이징 → 파고율."""
    denoised = wavelet_denoise(accel_window)
    return crest_factor(denoised)


def extract_engineered_features(
    accel_window: np.ndarray,
    gyro_window: np.ndarray,
    distance_window_mm: np.ndarray,
    speed_mm_s: float,
) -> list[float | None]:
    """롤링 센서 창을 RBF 입력용 9개 특징으로 변환한다."""
    accel = np.asarray(accel_window, dtype=np.float64).ravel()
    gyro = np.asarray(gyro_window, dtype=np.float64).ravel()
    distance = np.asarray(distance_window_mm, dtype=np.float64).ravel()

    accel_denoised = wavelet_denoise(accel)
    gyro_denoised = wavelet_denoise(gyro)
    accel_rms = (
        float(np.sqrt(np.mean(accel_denoised ** 2)))
        if accel_denoised.size
        else None
    )
    accel_peak_to_peak = (
        float(np.ptp(accel_denoised)) if accel_denoised.size else None
    )
    crest = (
        float(crest_factor(accel_denoised)) if accel_denoised.size else None
    )
    gyro_rms = (
        float(np.sqrt(np.mean(gyro_denoised ** 2)))
        if gyro_denoised.size
        else None
    )
    gyro_peak = (
        float(np.max(np.abs(gyro_denoised))) if gyro_denoised.size else None
    )

    if distance.size:
        distance_denoised = wavelet_denoise(distance)
        distance_mean = float(np.mean(distance_denoised))
        baseline = float(np.median(distance_denoised))
        distance_delta = float(distance_denoised[-1] - baseline)
        distance_std = float(np.std(distance_denoised))
    else:
        distance_mean = None
        distance_delta = None
        distance_std = None

    return [
        accel_rms,
        accel_peak_to_peak,
        crest,
        gyro_rms,
        gyro_peak,
        distance_mean,
        distance_delta,
        distance_std,
        float(speed_mm_s),
    ]


# ─────────────────────────────────────────────
#  1. 합성 특징 데이터 생성
# ─────────────────────────────────────────────
def _synthetic_windows(
    severity: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """정상 주행부터 단차 충격까지의 짧은 센서 창을 합성한다."""
    t = np.linspace(0.0, 1.0, WINDOW_LEN, endpoint=False)
    center = np.random.uniform(0.25, 0.75)
    width = np.random.uniform(0.025, 0.08)
    impulse = np.exp(-0.5 * ((t - center) / width) ** 2)
    ringing = np.sin(2.0 * np.pi * np.random.uniform(6.0, 12.0) * t)

    accel = (
        np.random.normal(0.03, 0.02, WINDOW_LEN)
        + severity * np.random.uniform(2.0, 8.0) * impulse * ringing
    )
    gyro = (
        np.abs(np.random.normal(0.01, 0.006, WINDOW_LEN))
        + severity * np.random.uniform(0.2, 1.0) * impulse
    )
    baseline_mm = np.random.uniform(3.0, 5.0)
    direction = np.random.choice((-1.0, 1.0))
    distance = (
        baseline_mm
        + direction * severity * np.random.uniform(0.2, 1.2) * impulse
        + np.random.normal(0.0, 0.015, WINDOW_LEN)
    )
    return accel, gyro, distance


def generate_dummy_dataset(num_samples: int) -> tuple[torch.Tensor, torch.Tensor]:
    """
    현재 MPU6050·LR18·엔코더 계약을 모사한 창에서 특징을 추출한다.
    합성 타겟은 파이프라인 검증용이며 실제 레일 정확도 근거가 아니다.
    """
    inputs = np.zeros((num_samples, INPUT_DIM), dtype=np.float64)
    targets = np.zeros(num_samples, dtype=np.float64)

    for index in range(num_samples):
        severity = float(np.random.beta(1.2, 2.0))
        speed_mm_s = float(np.random.uniform(50.0, 250.0))
        accel, gyro, distance = _synthetic_windows(severity)
        features = extract_engineered_features(
            accel,
            gyro,
            distance,
            speed_mm_s,
        )
        feature_values = np.asarray(features, dtype=np.float64)
        inputs[index] = feature_values

        feature_map = dict(zip(FEATURE_NAMES, feature_values))
        targets[index] = (
            0.7 * feature_map["accel_rms"]
            + 0.25 * feature_map["accel_peak_to_peak"]
            + 0.35 * feature_map["crest_factor"]
            + 0.8 * feature_map["gyro_rms"]
            + 0.6 * feature_map["gyro_peak"]
            + 1.2 * abs(feature_map["distance_delta_mm"])
            + 1.5 * feature_map["distance_std_mm"]
            + 0.002 * feature_map["speed_mm_s"] * severity
            + np.random.normal(0.0, 0.1)
        )

    targets = np.clip(targets, a_min=0.0, a_max=None)
    x = torch.tensor(inputs, dtype=torch.float32)
    y = torch.tensor(targets, dtype=torch.float32).unsqueeze(1)
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
    """RBF 대리 모델: 특징 공학 입력 → RBF → 레일 변형 지표 1차원."""

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
            "model_contract_version": 2,
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
