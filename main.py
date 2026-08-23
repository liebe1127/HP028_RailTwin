"""
main.py
갠트리 크레인 레일 변형 예측 FastAPI 서버
주행 진동·가속도 수집 → 특징 공학 → RBF로 하부 레일 변형(단차·침하·뒤틀림) 지표 추론

아키텍처:
  [ESP32-C3] --WiFi WebSocket /ws/sensor--> [asyncio.Queue] --> [Consumer Task] --> [InfluxDB]
  [더미 스트리머] --------------------------------------------->            --> [RBF 레일 변형 추론]
                                                                                --> [left/right rail_risk]
                                                                                --> [WebSocket /ws]

실행:
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload

WebSocket 테스트:
  websocat ws://localhost:8000/ws
  # 또는 브라우저 콘솔: new WebSocket("ws://localhost:8000/ws")

환경 변수 (.env 파일 또는 shell export):
  SENSOR_AUTH_TOKEN sensor-uplink-bearer-token
  DEMO_MODE         true|false
  INFLUX_URL       http://localhost:8086
  INFLUX_TOKEN     your-influxdb-token
  INFLUX_ORG       your-org
  INFLUX_BUCKET    crane_data
  DEVICE_ID        esp32-s3
  RBF_MODEL_PATH   rbf_dummy_model.pth   (ml/train_rbf_surrogate.py로 학습한 가중치)
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import torch
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client import Point

from ml.train_rbf_surrogate import (
    FEATURE_NAMES,
    WINDOW_LEN,
    RBFSurrogateModel,
    accel_dynamic_magnitude,
    compute_crest_from_window,
)
from sensor_contract import RAIL_SIDES, SensorContractError, normalize_sensor_batch

# ─────────────────────────────────────────────
#  환경 변수 로드 (.env 파일 우선, 없으면 shell 환경변수 사용)
# ─────────────────────────────────────────────
load_dotenv()

SENSOR_AUTH_TOKEN: str = os.getenv("SENSOR_AUTH_TOKEN", "")
SENSOR_WS_MAX_MESSAGE_BYTES: int = int(
    os.getenv("SENSOR_WS_MAX_MESSAGE_BYTES", "65536")
)
DEMO_MODE: bool = os.getenv("DEMO_MODE", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

INFLUX_URL: str = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN: str = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG: str = os.getenv("INFLUX_ORG", "")
INFLUX_BUCKET: str = os.getenv("INFLUX_BUCKET", "crane_data")
DEVICE_ID: str = os.getenv("DEVICE_ID", "rail-sensor")

MEASUREMENT = "crane_sensor"
QUEUE_MAX_SIZE = 100  # 큐 최대 적재 수 (초과 시 가장 오래된 항목 드롭)

RBF_MODEL_PATH: str = os.getenv("RBF_MODEL_PATH", "rbf_dummy_model.pth")

# 시연용 더미 스트리머 (1m 플라스틱 크레인)
DEMO_HZ_INTERVAL = 0.1          # 10Hz
DEMO_RAIL_LENGTH_CM = 100.0     # 레일 왕복 거리
DEMO_DANGER_START_CM = 40.0
DEMO_DANGER_END_CM = 50.0
DEMO_DANGER_CENTER_CM = 45.0
G_MS2 = 9.80665

# 레일 구간 위험도 히트맵 (Godot 디지털 트윈용)
RAIL_LENGTH_CM: float = float(os.getenv("RAIL_LENGTH_CM", str(DEMO_RAIL_LENGTH_CM)))
RAIL_SEGMENT_COUNT: int = int(os.getenv("RAIL_SEGMENT_COUNT", "20"))
# CREST / PRED → 0~1 위험도로 정규화할 때 쓰는 스케일
CREST_RISK_LOW = 1.5
CREST_RISK_HIGH = 5.0
PRED_RISK_SCALE = 5.0

# 좌/우 레일 각각 구간별 위험도 (0.0=정상 ~ 1.0=높음). 주행하며 max로 누적.
rail_risk_state: dict[str, list[float]] = {
    side: [0.0] * RAIL_SEGMENT_COUNT for side in RAIL_SIDES
}

# ─────────────────────────────────────────────
#  로거 설정
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("crane")

# ─────────────────────────────────────────────
#  공유 큐 (Producer → Consumer)
# ─────────────────────────────────────────────
sensor_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)


# ─────────────────────────────────────────────
#  WebSocket 연결 관리자
#  다수의 클라이언트(브라우저, 대시보드 등)가 동시에 연결될 수 있음
# ─────────────────────────────────────────────
class ConnectionManager:
    def __init__(self) -> None:
        self._active: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._active.append(ws)
        logger.info("WebSocket 연결: 현재 클라이언트 수=%d", len(self._active))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._active = [c for c in self._active if c is not ws]
        logger.info("WebSocket 해제: 현재 클라이언트 수=%d", len(self._active))

    async def broadcast(self, payload: dict) -> None:
        """연결된 모든 클라이언트에게 JSON 메시지를 전송합니다."""
        if not self._active:
            return

        message = json.dumps(payload, ensure_ascii=False)
        dead: list[WebSocket] = []

        async with self._lock:
            targets = list(self._active)

        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        # 전송 실패한 소켓은 자동 제거
        if dead:
            async with self._lock:
                self._active = [c for c in self._active if c not in dead]
            logger.warning("WebSocket 전송 실패 — %d개 연결 제거", len(dead))

    @property
    def client_count(self) -> int:
        return len(self._active)


ws_manager = ConnectionManager()
sensor_ws_clients = 0
sensor_last_batch_seq: dict[tuple[str, str], int] = {}


def sensor_authorized(ws: WebSocket) -> bool:
    """설정된 센서 토큰이 있으면 Authorization Bearer 값을 검증한다."""
    if not SENSOR_AUTH_TOKEN:
        return True
    authorization = ws.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(
        token.strip(), SENSOR_AUTH_TOKEN
    )


# ─────────────────────────────────────────────
#  AI 추론: PyTorch RBF 레일 변형 대리 모델
#  모델 정의는 ml/train_rbf_surrogate.py (centers=64, output_dim=1).
#  입력 11차원 = 센서 10개 + CREST. 출력은 하부 레일 변형 스칼라.
#  (거더 처짐 계수·PRED_DEFLECTION 을 쓰지 않음)
# ─────────────────────────────────────────────
ml_state: dict = {
    "model": None,
    "device": None,
    "x_mean": None,
    "x_std": None,
    "y_mean": None,
    "y_std": None,
}

# 좌/우 레일 각각 웨이블릿·파고율용 가속도 롤링 윈도우
accel_windows: dict[str, deque[float]] = {
    side: deque(maxlen=WINDOW_LEN) for side in RAIL_SIDES
}


def get_inference_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")   # Apple Silicon GPU
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def load_rbf_model(path: str) -> None:
    """
    학습된 RBF 대리 모델(.pth)을 로드해 ml_state에 채운다.
    파일이 없거나 손상된 경우에도 예외를 삼키고 로그만 남겨
    서버는 AI 추론 없이 정상 기동한다.
    """
    try:
        device = get_inference_device()
        checkpoint = torch.load(path, map_location=device, weights_only=False)

        model = RBFSurrogateModel(
            input_dim=checkpoint["input_dim"],
            num_centers=checkpoint["num_centers"],
            output_dim=checkpoint["output_dim"],
        )
        model.load_state_dict(checkpoint["model_state_dict"])
        model.to(device)
        model.eval()

        ml_state["model"] = model
        ml_state["device"] = device
        ml_state["x_mean"] = checkpoint["x_mean"].to(device)
        ml_state["x_std"] = checkpoint["x_std"].to(device)
        ml_state["y_mean"] = checkpoint["y_mean"].to(device)
        ml_state["y_std"] = checkpoint["y_std"].to(device)

        logger.info("RBF 모델 로드 완료: %s (device=%s)", path, device)
    except Exception as exc:
        logger.error(
            "RBF 모델 로드 실패 (%s) — AI 추론 없이 서버를 계속 실행합니다: %s", path, exc
        )
        ml_state["model"] = None


def extract_crest_feature(data: dict, side: str = "left") -> float:
    """
    가속도 창에 sym3 웨이블릿 디노이징을 적용한 뒤 파고율(Peak/RMS)을 계산한다.

    창 우선순위:
      1) accel_array 가 있으면 그 배열 (엣지가 윈도우를 보낼 때)
      2) 아니면 ADXL+MPU 동적 진폭을 해당 레일 롤링 윈도우(WINDOW_LEN)에 적재
    시연 더미의 `_demo_crest_target` 이 있으면 그 값을 반환한다
    (40~50cm 단차 충격에서 CREST≥5.0 재현).
    """
    window = accel_windows.setdefault(side, deque(maxlen=WINDOW_LEN))
    mag = accel_dynamic_magnitude(
        float(data.get("AAX") or 0.0),
        float(data.get("AAY") or 0.0),
        float(data.get("AAZ") or 9.8),
        float(data.get("MAX") or 0.0),
        float(data.get("MAY") or 0.0),
        float(data.get("MAZ") or 9.8),
    )
    window.append(mag)

    raw_window = data.get("accel_array")
    if raw_window is not None:
        window_arr = np.asarray(raw_window, dtype=np.float64).ravel()
    else:
        window_arr = np.asarray(window, dtype=np.float64)

    crest = compute_crest_from_window(window_arr) if window_arr.size else 0.0

    demo_target = data.get("_demo_crest_target")
    if demo_target is not None:
        return float(demo_target)
    return crest


def preprocess_and_extract_features(
    data: dict, side: str = "left"
) -> tuple[list[float | None], float]:
    """
    원시 센서를 모델에 직입력하지 않는다.
    FEATURE_NAMES 순서의 11차원 벡터를 만들고, CREST만 웨이블릿 특징이다.

      [AAX, AAY, AAZ, DIST, MAX, MAY, MAZ, GX, GY, GZ, CREST]
    """
    crest = extract_crest_feature(data, side)
    values: list[float | None] = []
    for key in FEATURE_NAMES:
        if key == "CREST":
            values.append(float(crest))
            continue
        val = data.get(key)
        values.append(None if val is None else float(val))
    return values, float(crest)


def normalize_risk(pred_rail_deform: float | None, crest: float | None) -> float:
    """PRED / CREST를 0~1 구간 위험도로 정규화. 둘 다 있으면 큰 쪽을 사용."""
    scores: list[float] = []
    if crest is not None:
        scores.append(
            float(
                np.clip(
                    (float(crest) - CREST_RISK_LOW) / (CREST_RISK_HIGH - CREST_RISK_LOW),
                    0.0,
                    1.0,
                )
            )
        )
    if pred_rail_deform is not None:
        scores.append(float(np.clip(float(pred_rail_deform) / PRED_RISK_SCALE, 0.0, 1.0)))
    return max(scores) if scores else 0.0


def update_rail_risk(
    distance_cm: float | None, risk: float, side: str = "left"
) -> list[float]:
    """해당 레일에서 현재 위치 구간의 rail_risk를 max 누적 갱신 후 복사본 반환."""
    state = rail_risk_state.setdefault(side, [0.0] * RAIL_SEGMENT_COUNT)
    if RAIL_SEGMENT_COUNT <= 0 or RAIL_LENGTH_CM <= 0:
        return list(state)
    if distance_cm is None:
        return list(state)

    seg_len = RAIL_LENGTH_CM / RAIL_SEGMENT_COUNT
    idx = int(float(distance_cm) / seg_len)
    idx = max(0, min(idx, RAIL_SEGMENT_COUNT - 1))
    state[idx] = max(state[idx], float(np.clip(risk, 0.0, 1.0)))
    return list(state)


def reset_rail_risk_state(side: str | None = None) -> dict[str, list[float]]:
    """누적 rail_risk를 0으로 초기화. side가 None이면 left/right 모두."""
    targets = RAIL_SIDES if side is None else (side,)
    for s in targets:
        if s not in RAIL_SIDES:
            continue
        rail_risk_state[s] = [0.0] * RAIL_SEGMENT_COUNT
    return {s: list(rail_risk_state[s]) for s in RAIL_SIDES}


def predict_rail_deform(
    data: dict, side: str = "left"
) -> tuple[float | None, float | None]:
    """
    특징 공학(11차원) → RBF → 하부 주행 레일 변형 지표(스칼라).

    Returns:
        (pred_rail_deform, crest) — 실패 시 해당 값은 None
    """
    model = ml_state.get("model")
    crest: float | None = None

    try:
        raw_values, crest = preprocess_and_extract_features(data, side)
    except Exception as exc:
        logger.error("특징 추출 실패 (건너뜀): %s", exc)
        return None, None

    if model is None:
        return None, crest

    try:
        device = ml_state["device"]
        x_mean = ml_state["x_mean"]
        x_std = ml_state["x_std"]
        y_mean = ml_state["y_mean"]
        y_std = ml_state["y_std"]

        filled: list[float] = []
        for i, val in enumerate(raw_values):
            filled.append(float(x_mean[0, i].item()) if val is None else float(val))

        x = torch.tensor([filled], dtype=torch.float32, device=device)
        x_norm = (x - x_mean) / x_std

        with torch.no_grad():
            pred_norm = model(x_norm)

        pred_rail_deform = float(pred_norm.item() * y_std.item() + y_mean.item())
        return pred_rail_deform, crest
    except Exception as exc:
        logger.error("AI 추론 실패 (건너뜀): %s", exc)
        return None, crest


def split_rail_samples(data: dict) -> tuple[str, dict[str, dict]]:
    """큐 항목에서 좌/우 레일 샘플과 source 를 꺼낸다. 구 평면 페이로드는 양쪽에 복제."""
    source = str(data.get("source") or data.get("_source") or "websocket")
    samples: dict[str, dict] = {}
    for side in RAIL_SIDES:
        sample = data.get(side)
        if isinstance(sample, dict):
            samples[side] = sample
    if samples:
        return source, samples
    return source, {"left": data, "right": data}


def build_side_ws_payload(
    sample: dict,
    *,
    side: str,
    pred_rail_deform: float | None,
    crest: float | None,
    rail_risk: list[float],
) -> dict:
    """Godot left/right 객체 하나에 넣을 레일별 페이로드."""
    return {
        "ts": sample.get("_received_at"),
        "distance_x": sample.get("DIST"),
        "AAX": sample.get("AAX"),
        "AAY": sample.get("AAY"),
        "AAZ": sample.get("AAZ"),
        "DIST": sample.get("DIST"),
        "MAX": sample.get("MAX"),
        "MAY": sample.get("MAY"),
        "MAZ": sample.get("MAZ"),
        "GX": sample.get("GX"),
        "GY": sample.get("GY"),
        "GZ": sample.get("GZ"),
        "CREST": crest,
        "PRED_RAIL_DEFORM": pred_rail_deform,
        "rail_risk": rail_risk,
        "rail_length_cm": RAIL_LENGTH_CM,
        "segment_count": RAIL_SEGMENT_COUNT,
        "device_id": f"{DEVICE_ID}-{side}",
    }


async def enqueue_sensor_item(item: dict) -> None:
    if sensor_queue.full():
        try:
            sensor_queue.get_nowait()
            logger.warning("큐 오버플로 — 가장 오래된 항목 드롭")
        except asyncio.QueueEmpty:
            pass
    await sensor_queue.put(item)


# ─────────────────────────────────────────────
#  시연용 더미 센서 샘플 생성 (1m 플라스틱 크레인)
# ─────────────────────────────────────────────
def generate_crane_demo_sample(distance_x: float) -> dict:
    """
    distance_x(cm) 위치에 따른 정상/위험 구간 센서 값을 생성한다.

    - 정상(0~40, 50~100): 미세 노이즈 → CREST ≈ 1.0~1.5
    - 위험(40~50, 중심 45cm): 단차 충격 피크 → CREST ≥ 5.0
    """
    in_danger = DEMO_DANGER_START_CM <= distance_x <= DEMO_DANGER_END_CM

    if in_danger:
        # 45cm 중심 가우시안 충격 엔벨로프 (0~1)
        impact = float(np.exp(-0.5 * ((distance_x - DEMO_DANGER_CENTER_CM) / 2.0) ** 2))
        peak_g = 0.5 + 0.5 * impact  # 0.5g ~ 1.0g

        roll_deg = float(np.random.uniform(-10.0, 10.0) * max(impact, 0.4))
        pitch_deg = float(np.random.uniform(-10.0, 10.0) * max(impact, 0.4))

        accel_x = float(
            np.sin(np.radians(roll_deg)) * G_MS2
            + np.random.normal(0.0, 0.05)
        )
        accel_y = float(
            np.sin(np.radians(pitch_deg)) * G_MS2
            + np.random.normal(0.0, 0.05)
        )
        accel_z = float(
            9.8 + peak_g * G_MS2 + np.random.normal(0.0, 0.1)
        )

        gx = float(np.radians(roll_deg) + np.random.normal(0.0, 0.02))
        gy = float(np.radians(pitch_deg) + np.random.normal(0.0, 0.02))
        gz = float(np.random.normal(0.0, 0.05))
        sensor_distance_mm = float(
            4.0 + 0.8 * impact + np.random.normal(0.0, 0.02)
        )

        # 위험 임계치 5.0 이상으로 치솟도록 시연용 파고율 지정
        demo_crest = float(5.0 + 3.0 * impact + np.random.uniform(0.0, 1.0))
    else:
        # 정상 주행: 거의 0에 가까운 미세 가우시안 노이즈
        accel_x = float(np.random.normal(0.0, 0.005))
        accel_y = float(np.random.normal(0.0, 0.005))
        accel_z = float(9.8 + np.random.normal(0.0, 0.005))
        gx = float(np.random.normal(0.0, 0.005))
        gy = float(np.random.normal(0.0, 0.005))
        gz = float(np.random.normal(0.0, 0.005))
        sensor_distance_mm = float(4.0 + np.random.normal(0.0, 0.01))
        # 정상 범위 파고율 1.0~1.5
        demo_crest = float(np.random.uniform(1.05, 1.45))

    sensor_voltage_v = float(
        np.clip((sensor_distance_mm - 1.0) / 7.0 * 10.0, 0.0, 10.0)
    )
    adc_voltage_v = sensor_voltage_v * (68_000.0 / 538_000.0)
    return {
        "position_mm": float(distance_x) * 10.0,
        "sensor_distance_mm": sensor_distance_mm,
        "adc_raw": int(np.clip(adc_voltage_v / 4.096 * 32768.0, 0, 32767)),
        "adc_voltage_v": adc_voltage_v,
        "sensor_voltage_v": sensor_voltage_v,
        "accel_x": accel_x,
        "accel_y": accel_y,
        "accel_z": accel_z,
        "gyro_x": gx,
        "gyro_y": gy,
        "gyro_z": gz,
        "_demo_crest_target": demo_crest,
        "_source": "demo",
    }


# ─────────────────────────────────────────────
#  더미 스트리머 Task: 시연용 센서 데이터 생성 → 큐 적재
# ─────────────────────────────────────────────
async def dummy_sensor_streamer(stop_event: asyncio.Event) -> None:
    """
    ESP32 미연결 시 1m 플라스틱 크레인 시연용 더미 데이터를 10Hz로 생성한다.
    Consumer가 RBF 추론 후 WebSocket으로 left/right 레일 페이로드를 전송한다.
    """
    logger.info(
        "더미 스트리머 시작 (시연 모드): %.0fcm 레일, %.0fHz, 위험구간 %s~%scm (좌/우 독립)",
        DEMO_RAIL_LENGTH_CM,
        1.0 / DEMO_HZ_INTERVAL,
        DEMO_DANGER_START_CM,
        DEMO_DANGER_END_CM,
    )

    distance_x = 0.0
    sample_seq = 1

    while not stop_event.is_set():
        ts = time.time()
        left = generate_crane_demo_sample(distance_x)
        right = generate_crane_demo_sample(distance_x)
        for side, sample in (("left", left), ("right", right)):
            sample.update(
                {
                    "_received_at": ts,
                    "sample_seq": sample_seq,
                    "uptime_us": int(ts * 1_000_000),
                    "device_id": f"demo-{side}",
                    "rail_side": side,
                    "batch_seq": sample_seq,
                    "dropped_batches": 0,
                    "firmware_version": "demo",
                }
            )

        await enqueue_sensor_item({"left": left, "right": right, "source": "demo"})

        zone = "DANGER" if DEMO_DANGER_START_CM <= distance_x <= DEMO_DANGER_END_CM else "OK"
        logger.info(
            "더미 → x=%.0fcm [%s] left_crest=%.2f right_crest=%.2f",
            distance_x,
            zone,
            left["_demo_crest_target"],
            right["_demo_crest_target"],
        )

        distance_x += 1.0
        if distance_x > DEMO_RAIL_LENGTH_CM:
            distance_x = 0.0
        sample_seq += 1

        await asyncio.sleep(DEMO_HZ_INTERVAL)

    logger.info("더미 스트리머 종료")


# ─────────────────────────────────────────────
#  Consumer Task: 큐에서 꺼내기 → InfluxDB 저장
# ─────────────────────────────────────────────
async def influx_consumer(stop_event: asyncio.Event) -> None:
    logger.info(
        "Consumer 시작: InfluxDB=%s  bucket=%s  org=%s",
        INFLUX_URL, INFLUX_BUCKET, INFLUX_ORG,
    )

    async with InfluxDBClientAsync(
        url=INFLUX_URL,
        token=INFLUX_TOKEN,
        org=INFLUX_ORG,
    ) as influx:
        write_api = influx.write_api()

        while not stop_event.is_set() or not sensor_queue.empty():
            try:
                data: dict = await asyncio.wait_for(sensor_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            source, samples = split_rail_samples(data)
            ws_payload: dict = {"source": source}

            for side, sample in samples.items():
                point = (
                    Point(MEASUREMENT)
                    .tag("device_id", f"{DEVICE_ID}-{side}")
                    .tag("rail_side", side)
                )

                field_map = {
                    "AAX": "adxl_accel_x", "AAY": "adxl_accel_y", "AAZ": "adxl_accel_z",
                    "DIST": "distance_cm",
                    "MAX": "mpu_accel_x", "MAY": "mpu_accel_y", "MAZ": "mpu_accel_z",
                    "GX": "mpu_gyro_x", "GY": "mpu_gyro_y", "GZ": "mpu_gyro_z",
                }
                for sensor_key, influx_field in field_map.items():
                    val = sample.get(sensor_key)
                    if val is not None:
                        point = point.field(influx_field, float(val))

                pred_rail_deform, crest = predict_rail_deform(sample, side)
                if pred_rail_deform is not None:
                    point = point.field("pred_rail_deform", pred_rail_deform)
                if crest is not None:
                    point = point.field("crest_factor", float(crest))

                try:
                    await write_api.write(bucket=INFLUX_BUCKET, record=point)
                    logger.debug("InfluxDB 저장 완료 (%s)", side)
                except Exception as exc:
                    logger.error("InfluxDB 쓰기 실패 (건너뜀, %s): %s", side, exc)

                risk = normalize_risk(pred_rail_deform, crest)
                rail_risk = update_rail_risk(sample.get("DIST"), risk, side)
                ws_payload[side] = build_side_ws_payload(
                    sample,
                    side=side,
                    pred_rail_deform=pred_rail_deform,
                    crest=crest,
                    rail_risk=rail_risk,
                )

            await ws_manager.broadcast(ws_payload)

            sensor_queue.task_done()

    logger.info("Consumer 종료")


# ─────────────────────────────────────────────
#  FastAPI lifespan: 서버 시작/종료 시 백그라운드 태스크 관리
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # AI 모델 로드 (torch.load는 블로킹 I/O이므로 to_thread로 이벤트 루프 비블로킹)
    await asyncio.to_thread(load_rbf_model, RBF_MODEL_PATH)

    stop_event = asyncio.Event()
    tasks: list[asyncio.Task] = []
    if DEMO_MODE:
        tasks.append(
            asyncio.create_task(
                dummy_sensor_streamer(stop_event), name="dummy-streamer"
            )
        )
        logger.warning("DEMO_MODE=true → 시연용 더미 스트리머 시작")
    consumer_task = asyncio.create_task(influx_consumer(stop_event), name="influx-consumer")
    tasks.append(consumer_task)
    logger.info(
        "백그라운드 태스크 시작 (demo_mode=%s, ESP32=/ws/sensor)",
        DEMO_MODE,
    )

    try:
        yield  # ← 서버 가동 중
    finally:
        logger.info("서버 종료 요청 — 태스크 종료 대기 중...")
        stop_event.set()

        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("모든 백그라운드 태스크 종료 완료")


# ─────────────────────────────────────────────
#  FastAPI 앱
# ─────────────────────────────────────────────
app = FastAPI(
    title="Crane Rail Deformation API",
    description="갠트리 크레인 주행 진동 계측 및 하부 레일 변형(단차·침하·뒤틀림) 예측 서버",
    version="0.3.0",
    lifespan=lifespan,
)

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
DASHBOARD_HTML = FRONTEND_DIR / "index.html"


# ─────────────────────────────────────────────
#  엔드포인트
# ─────────────────────────────────────────────
@app.get("/", summary="헬스체크")
async def health_check():
    """서버 상태 및 큐 적재 현황을 반환합니다."""
    return {
        "status": "ok",
        "influx_url": INFLUX_URL,
        "influx_bucket": INFLUX_BUCKET,
        "queue_size": sensor_queue.qsize(),
        "queue_max": QUEUE_MAX_SIZE,
        "ws_clients": ws_manager.client_count,
        "sensor_ws_clients": sensor_ws_clients,
        "ai_model_loaded": ml_state.get("model") is not None,
        "ai_model_device": str(ml_state.get("device")) if ml_state.get("device") else None,
        "demo_mode": DEMO_MODE,
    }


@app.get("/queue/size", summary="큐 현재 크기 조회")
async def queue_size():
    return {"queue_size": sensor_queue.qsize()}


@app.get("/dashboard", summary="레일 변형 웹 대시보드")
async def dashboard():
    """같은 FastAPI 프로세스에서 frontend/index.html 을 연다."""
    if not DASHBOARD_HTML.is_file():
        return {"error": "frontend/index.html 이 서버에 없습니다"}
    return FileResponse(DASHBOARD_HTML)


@app.post("/rail_risk/reset", summary="레일 구간 위험도 히트맵 초기화")
async def rail_risk_reset(side: str | None = None):
    """
    max 누적된 rail_risk를 0으로 리셋한다.
    query: side=left|right (생략 시 양쪽)
    """
    if side is not None and side not in RAIL_SIDES:
        return {"ok": False, "error": f"side must be one of {RAIL_SIDES}"}
    state = reset_rail_risk_state(side)
    logger.info("rail_risk 리셋 완료 (side=%s)", side or "all")
    return {"ok": True, "side": side or "all", "rail_risk": state}


# ─────────────────────────────────────────────
#  WebSocket 엔드포인트
#  센서 업링크: wss://host/ws/sensor
#  화면 다운링크: wss://host/ws
# ─────────────────────────────────────────────
@app.websocket("/ws/sensor")
async def sensor_websocket_endpoint(ws: WebSocket):
    global sensor_ws_clients

    if not sensor_authorized(ws):
        await ws.close(code=1008, reason="invalid sensor token")
        return

    await ws.accept()
    sensor_ws_clients += 1
    logger.info("센서 WebSocket 연결: 현재 센서 수=%d", sensor_ws_clients)
    try:
        while True:
            raw_message = await ws.receive_text()
            if len(raw_message.encode("utf-8")) > SENSOR_WS_MAX_MESSAGE_BYTES:
                await ws.send_json(
                    {"type": "error", "code": "message_too_large"}
                )
                await ws.close(code=1009)
                return

            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "code": "invalid_json"})
                continue

            if isinstance(message, dict) and message.get("type") == "hello":
                await ws.send_json(
                    {
                        "type": "hello_ack",
                        "schema_version": 1,
                        "server_time_ms": int(time.time() * 1000),
                    }
                )
                continue

            received_at = time.time()
            try:
                queue_items = normalize_sensor_batch(message, received_at)
            except SensorContractError as exc:
                await ws.send_json(
                    {
                        "type": "error",
                        "code": "invalid_sensor_batch",
                        "detail": str(exc),
                    }
                )
                continue

            batch = message
            key = (str(batch["device_id"]), str(batch["rail_side"]))
            batch_seq = int(batch["batch_seq"])
            last_seq = sensor_last_batch_seq.get(key, -1)
            if batch_seq <= last_seq:
                await ws.send_json(
                    {
                        "type": "ack",
                        "batch_seq": batch_seq,
                        "duplicate": True,
                    }
                )
                continue

            for item in queue_items:
                await sensor_queue.put(item)
            sensor_last_batch_seq[key] = batch_seq
            await ws.send_json(
                {
                    "type": "ack",
                    "batch_seq": batch_seq,
                    "accepted_samples": len(queue_items),
                }
            )
    except WebSocketDisconnect:
        pass
    finally:
        sensor_ws_clients = max(0, sensor_ws_clients - 1)
        logger.info("센서 WebSocket 해제: 현재 센서 수=%d", sensor_ws_clients)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        # 연결 유지 루프: 클라이언트가 ping/pong 또는 임의 텍스트를 보내도 정상 처리
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(ws)


@app.get("/ws/clients", summary="현재 WebSocket 연결 수 조회")
async def ws_client_count():
    return {"connected_clients": ws_manager.client_count}
