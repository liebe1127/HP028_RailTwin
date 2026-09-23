"""
main.py
갠트리 크레인 레일 변형 예측 FastAPI 서버
주행 진동·가속도 수집 → 특징 공학 → RBF로 하부 레일 변형(단차·침하·뒤틀림) 지표 추론

아키텍처:
  [ESP32-C3] --MQTTS QoS 1--> [Mosquitto] --> [MQTT Subscriber] --> [asyncio.Queue]
  [더미 스트리머] -----------------------------------------------------------> [Consumer Task]
                                                                                 --> [InfluxDB]
                                                                                 --> [RBF 레일 변형 추론]
                                                                                 --> [left/right rail_risk]
                                                                                 --> [WebSocket /ws]

실행:
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload

WebSocket 테스트:
  websocat ws://localhost:8000/ws
  # 또는 브라우저 콘솔: new WebSocket("ws://localhost:8000/ws")

환경 변수 (.env 파일 또는 shell export):
  MQTT_HOST         127.0.0.1
  MQTT_PORT         1883
  MQTT_USERNAME     railtwin-backend
  MQTT_PASSWORD     broker-password
  MQTT_TLS          true|false
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
import json
import logging
import mimetypes
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import numpy as np
import paho.mqtt.client as mqtt
import torch
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client import Point, WritePrecision

from ml.train_rbf_surrogate import (
    FEATURE_NAMES,
    WINDOW_LEN,
    RBFSurrogateModel,
    dynamic_accel_magnitude,
    extract_engineered_features,
    gyro_magnitude,
)
from sensor_contract import RAIL_SIDES, SensorContractError, normalize_sensor_batch

# ─────────────────────────────────────────────
#  환경 변수 로드 (.env 파일 우선, 없으면 shell 환경변수 사용)
# ─────────────────────────────────────────────
load_dotenv()

MQTT_HOST: str = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT: int = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME: str = os.getenv("MQTT_USERNAME", "railtwin-backend")
MQTT_PASSWORD: str = os.getenv("MQTT_PASSWORD") or os.getenv(
    "MQTT_BACKEND_PASSWORD", ""
)
MQTT_TLS: bool = os.getenv("MQTT_TLS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
MQTT_CA_CERT: str = os.getenv("MQTT_CA_CERT", "")
MQTT_CLIENT_ID: str = os.getenv("MQTT_CLIENT_ID", "railtwin-backend")
MQTT_TOPIC_PREFIX: str = os.getenv("MQTT_TOPIC_PREFIX", "rail/v1/nodes").strip("/")
MQTT_TELEMETRY_TOPIC: str = f"{MQTT_TOPIC_PREFIX}/+/telemetry"
MQTT_STATUS_TOPIC: str = f"{MQTT_TOPIC_PREFIX}/+/status"
MQTT_KEEPALIVE_SECONDS: int = int(os.getenv("MQTT_KEEPALIVE_SECONDS", "30"))
MQTT_MAX_PAYLOAD_BYTES: int = int(os.getenv("MQTT_MAX_PAYLOAD_BYTES", "65536"))
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
INFLUX_WRITE_ENABLED: bool = bool(INFLUX_TOKEN and INFLUX_ORG)
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
latest_ws_payload_by_side: dict[str, dict] = {}

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
sensor_last_batch_seq: dict[tuple[str, str, str], int] = {}
sensor_node_state: dict[str, dict] = {}
mqtt_ingest_queue: asyncio.Queue[tuple[str, bytes, float]] = asyncio.Queue(
    maxsize=QUEUE_MAX_SIZE
)
mqtt_state: dict = {
    "connected": False,
    "messages_received": 0,
    "messages_rejected": 0,
    "last_message_at": None,
    "last_error": None,
}


def sensor_stream_key(batch: dict) -> tuple[str, str, str]:
    """장치 재부팅 후 1부터 다시 시작하는 배치 순번을 별도 스트림으로 구분한다."""
    return (
        str(batch["device_id"]),
        str(batch["rail_side"]),
        str(batch["boot_id"]),
    )


def record_sensor_node_batch(batch: dict) -> None:
    """MQTT 텔레메트리를 기준으로 좌·우 노드의 최신 상태를 기록한다."""
    side = str(batch["rail_side"])
    previous = sensor_node_state.get(side, {})
    same_boot = previous.get("boot_id") == batch.get("boot_id")
    batch_seq = int(batch["batch_seq"])
    dropped_batches = int(batch.get("dropped_batches", 0))
    if same_boot:
        batch_seq = max(batch_seq, int(previous.get("last_batch_seq", -1)))
        dropped_batches = max(
            dropped_batches, int(previous.get("dropped_batches", 0))
        )
    sensor_node_state[side] = {
        "device_id": str(batch["device_id"]),
        "rail_side": side,
        "boot_id": batch.get("boot_id"),
        "firmware_version": batch.get("firmware_version"),
        "last_batch_seq": batch_seq,
        "dropped_batches": dropped_batches,
        "status_flags": int(batch.get("status_flags", 0)),
        "last_seen": time.time(),
        "connected": True,
        "transport": "mqtt",
    }


def record_sensor_node_status(status: dict) -> None:
    """Retained online 상태와 LWT offline 상태를 노드 진단 정보에 반영한다."""
    side = str(status["rail_side"])
    previous = sensor_node_state.get(side, {})
    sensor_node_state[side] = {
        **previous,
        "device_id": str(status["device_id"]),
        "rail_side": side,
        "boot_id": status.get("boot_id", previous.get("boot_id")),
        "firmware_version": status.get(
            "firmware_version", previous.get("firmware_version")
        ),
        "status_flags": int(
            status.get("status_flags", previous.get("status_flags", 0))
        ),
        "last_status_at": time.time(),
        "connected": status["status"] == "online",
        "transport": "mqtt",
    }


# ─────────────────────────────────────────────
#  AI 추론: PyTorch RBF 레일 변형 대리 모델
#  모델 정의는 ml/train_rbf_surrogate.py (centers=64, output_dim=1).
#  입력은 MPU6050·LR18·엔코더 롤링 윈도우의 특징 공학 결과다.
# ─────────────────────────────────────────────
ml_state: dict = {
    "model": None,
    "device": None,
    "x_mean": None,
    "x_std": None,
    "y_mean": None,
    "y_std": None,
}

# 좌/우 레일별 특징 공학 롤링 윈도우
feature_windows: dict[str, dict[str, deque]] = {
    side: {
        "accel": deque(maxlen=WINDOW_LEN),
        "gyro": deque(maxlen=WINDOW_LEN),
        "distance": deque(maxlen=WINDOW_LEN),
        "position_time": deque(maxlen=2),
    }
    for side in RAIL_SIDES
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
        if checkpoint.get("model_contract_version") != 2:
            raise ValueError("현재 센서용 model_contract_version=2 모델이 아닙니다.")
        checkpoint_features = checkpoint.get("feature_names")
        if checkpoint_features != FEATURE_NAMES:
            raise ValueError(
                "모델 feature_names가 현재 센서 계약과 다릅니다. "
                "ml/train_rbf_surrogate.py로 다시 학습하세요."
            )

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


def preprocess_and_extract_features(
    data: dict, side: str = "left"
) -> tuple[list[float | None], float]:
    """
    MPU6050·LR18·엔코더 원시값을 롤링 창에 적재하고,
    웨이블릿·RMS·peak-to-peak·파고율·거리 변화·속도 특징을 만든다.
    """
    windows = feature_windows.setdefault(
        side,
        {
            "accel": deque(maxlen=WINDOW_LEN),
            "gyro": deque(maxlen=WINDOW_LEN),
            "distance": deque(maxlen=WINDOW_LEN),
            "position_time": deque(maxlen=2),
        },
    )

    accel_values = [data.get(key) for key in ("accel_x", "accel_y", "accel_z")]
    if all(isinstance(value, (int, float)) for value in accel_values):
        windows["accel"].append(
            dynamic_accel_magnitude(*(float(value) for value in accel_values))
        )

    gyro_values = [data.get(key) for key in ("gyro_x", "gyro_y", "gyro_z")]
    if all(isinstance(value, (int, float)) for value in gyro_values):
        windows["gyro"].append(
            gyro_magnitude(*(float(value) for value in gyro_values))
        )

    sensor_distance = data.get("sensor_distance_mm")
    if isinstance(sensor_distance, (int, float)):
        windows["distance"].append(float(sensor_distance))

    position = data.get("position_mm")
    received_at = data.get("_received_at")
    if isinstance(position, (int, float)) and isinstance(
        received_at, (int, float)
    ):
        windows["position_time"].append((float(position), float(received_at)))

    speed_mm_s = 0.0
    if len(windows["position_time"]) == 2:
        previous, current = windows["position_time"]
        elapsed = current[1] - previous[1]
        if elapsed > 0.0:
            speed_mm_s = abs(current[0] - previous[0]) / elapsed

    features = extract_engineered_features(
        np.asarray(windows["accel"], dtype=np.float64),
        np.asarray(windows["gyro"], dtype=np.float64),
        np.asarray(windows["distance"], dtype=np.float64),
        speed_mm_s,
    )
    crest_index = FEATURE_NAMES.index("crest_factor")
    demo_target = data.get("_demo_crest_target")
    if demo_target is not None:
        features[crest_index] = float(demo_target)
    crest = features[crest_index]
    data["_engineered_features"] = dict(zip(FEATURE_NAMES, features))
    return features, float(crest or 0.0)


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
    특징 공학 → RBF → 하부 주행 레일 변형 지표(스칼라).

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
    position_mm = sample.get("position_mm")
    distance_x = (
        float(position_mm) / 10.0
        if isinstance(position_mm, (int, float))
        else None
    )
    return {
        "ts": sample.get("_received_at"),
        "distance_x": distance_x,
        "position_mm": position_mm,
        "sensor_distance_mm": sample.get("sensor_distance_mm"),
        "adc_raw": sample.get("adc_raw"),
        "adc_voltage_v": sample.get("adc_voltage_v"),
        "sensor_voltage_v": sample.get("sensor_voltage_v"),
        "accel_x": sample.get("accel_x"),
        "accel_y": sample.get("accel_y"),
        "accel_z": sample.get("accel_z"),
        "gyro_x": sample.get("gyro_x"),
        "gyro_y": sample.get("gyro_y"),
        "gyro_z": sample.get("gyro_z"),
        "CREST": crest,
        "PRED_RAIL_DEFORM": pred_rail_deform,
        "rail_risk": rail_risk,
        "rail_length_cm": RAIL_LENGTH_CM,
        "segment_count": RAIL_SEGMENT_COUNT,
        "device_id": sample.get("device_id") or f"{DEVICE_ID}-{side}",
        "rail_side": side,
        "sample_seq": sample.get("sample_seq"),
        "batch_seq": sample.get("batch_seq"),
        "dropped_batches": sample.get("dropped_batches"),
        "firmware_version": sample.get("firmware_version"),
        "boot_id": sample.get("boot_id"),
        "status_flags": sample.get("status_flags"),
        "features": sample.get("_engineered_features"),
    }


def update_downlink_snapshot(source: str, side_payloads: dict[str, dict]) -> dict:
    """독립적으로 도착한 좌·우 ESP32 결과를 최신 양측 스냅샷으로 결합한다."""
    for side, payload in side_payloads.items():
        if side in RAIL_SIDES:
            latest_ws_payload_by_side[side] = payload
    return {
        "source": source,
        **{
            side: latest_ws_payload_by_side[side]
            for side in RAIL_SIDES
            if side in latest_ws_payload_by_side
        },
    }


async def enqueue_sensor_item(item: dict) -> None:
    if sensor_queue.full():
        try:
            sensor_queue.get_nowait()
            sensor_queue.task_done()
            logger.warning("큐 오버플로 — 가장 오래된 항목 드롭")
        except asyncio.QueueEmpty:
            pass
    await sensor_queue.put(item)


# ─────────────────────────────────────────────
#  MQTT 센서 업링크: Mosquitto → 계약 검증 → 기존 Queue
# ─────────────────────────────────────────────
def mqtt_topic_device(topic: str, suffix: str) -> str | None:
    prefix_parts = MQTT_TOPIC_PREFIX.split("/")
    topic_parts = topic.split("/")
    if (
        len(topic_parts) != len(prefix_parts) + 2
        or topic_parts[: len(prefix_parts)] != prefix_parts
        or topic_parts[-1] != suffix
    ):
        return None
    return topic_parts[-2]


async def process_mqtt_message(
    topic: str,
    payload_bytes: bytes,
    received_at: float,
) -> int:
    """MQTT 메시지 하나를 검증해 기존 센서 Queue에 넣고 수락 샘플 수를 반환한다."""
    if len(payload_bytes) > MQTT_MAX_PAYLOAD_BYTES:
        raise SensorContractError("MQTT payload exceeds configured size limit")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SensorContractError("MQTT payload must be valid UTF-8 JSON") from exc

    telemetry_device = mqtt_topic_device(topic, "telemetry")
    if telemetry_device is not None:
        if not isinstance(payload, dict) or payload.get("device_id") != telemetry_device:
            raise SensorContractError("MQTT topic device_id does not match payload")
        queue_items = normalize_sensor_batch(
            payload,
            received_at,
            source="mqtt",
        )
        key = sensor_stream_key(payload)
        batch_seq = int(payload["batch_seq"])
        last_seq = sensor_last_batch_seq.get(key, -1)
        record_sensor_node_batch(payload)
        if batch_seq <= last_seq:
            logger.info(
                "MQTT 중복 배치 건너뜀: device=%s boot=%s batch=%d",
                payload["device_id"],
                payload["boot_id"],
                batch_seq,
            )
            return 0
        for item in queue_items:
            await enqueue_sensor_item(item)
        sensor_last_batch_seq[key] = batch_seq
        return len(queue_items)

    status_device = mqtt_topic_device(topic, "status")
    if status_device is not None:
        if not isinstance(payload, dict) or payload.get("type") != "node_status":
            raise SensorContractError("MQTT status payload must be node_status")
        if payload.get("device_id") != status_device:
            raise SensorContractError("MQTT status topic device_id does not match payload")
        if payload.get("rail_side") not in RAIL_SIDES:
            raise SensorContractError(f"rail_side must be one of {RAIL_SIDES}")
        if payload.get("status") not in {"online", "offline"}:
            raise SensorContractError("MQTT node status must be online or offline")
        record_sensor_node_status(payload)
        return 0

    raise SensorContractError("MQTT topic is outside the sensor contract")


def enqueue_mqtt_ingest(topic: str, payload: bytes, received_at: float) -> None:
    """Paho 네트워크 스레드가 이벤트 루프에 넘긴 원시 메시지를 제한 큐에 적재한다."""
    if mqtt_ingest_queue.full():
        try:
            mqtt_ingest_queue.get_nowait()
            mqtt_ingest_queue.task_done()
            mqtt_state["messages_rejected"] += 1
            logger.warning("MQTT 수신 큐 오버플로 — 가장 오래된 메시지 드롭")
        except asyncio.QueueEmpty:
            pass
    mqtt_ingest_queue.put_nowait((topic, payload, received_at))


async def mqtt_ingest_consumer(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set() or not mqtt_ingest_queue.empty():
        try:
            topic, payload, received_at = await asyncio.wait_for(
                mqtt_ingest_queue.get(),
                timeout=0.5,
            )
        except asyncio.TimeoutError:
            continue
        try:
            await process_mqtt_message(topic, payload, received_at)
        except SensorContractError as exc:
            mqtt_state["messages_rejected"] += 1
            mqtt_state["last_error"] = str(exc)
            logger.warning("MQTT 센서 메시지 거부 (%s): %s", topic, exc)
        finally:
            mqtt_ingest_queue.task_done()


async def mqtt_subscriber(stop_event: asyncio.Event) -> None:
    """Paho MQTT 네트워크 루프를 실행하고 센서 토픽을 QoS 1로 구독한다."""
    if not MQTT_HOST or not MQTT_USERNAME or not MQTT_PASSWORD:
        mqtt_state["last_error"] = "MQTT host or credentials are not configured"
        logger.error("MQTT 연결 설정이 비어 있어 센서 구독을 시작하지 않습니다.")
        return

    event_loop = asyncio.get_running_loop()
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=MQTT_CLIENT_ID,
        clean_session=False,
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    if MQTT_TLS:
        client.tls_set(ca_certs=MQTT_CA_CERT or None)

    def on_connect(
        mqtt_client: mqtt.Client,
        userdata: object,
        connect_flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            mqtt_state["connected"] = False
            mqtt_state["last_error"] = f"MQTT connect failed: {reason_code}"
            logger.error("%s", mqtt_state["last_error"])
            return
        mqtt_client.subscribe(
            [(MQTT_TELEMETRY_TOPIC, 1), (MQTT_STATUS_TOPIC, 1)]
        )
        mqtt_state["connected"] = True
        mqtt_state["last_error"] = None
        logger.info(
            "MQTT 연결 완료: %s:%d, topics=%s,%s",
            MQTT_HOST,
            MQTT_PORT,
            MQTT_TELEMETRY_TOPIC,
            MQTT_STATUS_TOPIC,
        )

    def on_disconnect(
        mqtt_client: mqtt.Client,
        userdata: object,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        mqtt_state["connected"] = False
        if reason_code.is_failure:
            mqtt_state["last_error"] = f"MQTT disconnected: {reason_code}"
            logger.warning("%s", mqtt_state["last_error"])

    def on_message(
        mqtt_client: mqtt.Client,
        userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        received_at = time.time()
        mqtt_state["messages_received"] += 1
        mqtt_state["last_message_at"] = received_at
        event_loop.call_soon_threadsafe(
            enqueue_mqtt_ingest,
            message.topic,
            bytes(message.payload),
            received_at,
        )

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=MQTT_KEEPALIVE_SECONDS)
    client.loop_start()
    try:
        await stop_event.wait()
    finally:
        client.disconnect()
        await asyncio.to_thread(client.loop_stop)
        mqtt_state["connected"] = False


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
                    "boot_id": None,
                    "batch_seq": sample_seq,
                    "dropped_batches": 0,
                    "status_flags": 0,
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


def build_influx_point(
    sample: dict,
    *,
    side: str,
    source: str,
    pred_rail_deform: float | None,
    crest: float | None,
) -> Point:
    """현재 센서 계약과 특징 공학 결과를 InfluxDB Point로 변환한다."""
    device_id = str(sample.get("device_id") or f"{DEVICE_ID}-{side}")
    point = (
        Point(MEASUREMENT)
        .tag("device_id", device_id)
        .tag("rail_side", side)
        .tag("source", source)
    )
    firmware_version = sample.get("firmware_version")
    if firmware_version:
        point = point.tag("firmware_version", str(firmware_version))
    boot_id = sample.get("boot_id")
    if boot_id:
        point = point.tag("boot_id", str(boot_id))

    float_fields = {
        "position_mm": "position_mm",
        "sensor_distance_mm": "sensor_distance_mm",
        "adc_voltage_v": "adc_voltage_v",
        "sensor_voltage_v": "sensor_voltage_v",
        "accel_x": "mpu_accel_x",
        "accel_y": "mpu_accel_y",
        "accel_z": "mpu_accel_z",
        "gyro_x": "mpu_gyro_x",
        "gyro_y": "mpu_gyro_y",
        "gyro_z": "mpu_gyro_z",
    }
    integer_fields = {
        "adc_raw": "adc_raw",
        "sample_seq": "sample_seq",
        "uptime_us": "uptime_us",
        "batch_seq": "batch_seq",
        "dropped_batches": "dropped_batches",
        "status_flags": "status_flags",
    }
    for sensor_key, influx_field in float_fields.items():
        value = sample.get(sensor_key)
        if isinstance(value, (int, float)):
            point = point.field(influx_field, float(value))
    for sensor_key, influx_field in integer_fields.items():
        value = sample.get(sensor_key)
        if isinstance(value, int) and not isinstance(value, bool):
            point = point.field(influx_field, value)

    engineered = sample.get("_engineered_features")
    if isinstance(engineered, dict):
        for feature_name in FEATURE_NAMES:
            value = engineered.get(feature_name)
            if isinstance(value, (int, float)):
                point = point.field(f"feature_{feature_name}", float(value))

    if pred_rail_deform is not None:
        point = point.field("pred_rail_deform", float(pred_rail_deform))
    if crest is not None:
        point = point.field("crest_factor", float(crest))

    received_at = sample.get("_received_at")
    if isinstance(received_at, (int, float)) and received_at > 0:
        point = point.time(
            int(float(received_at) * 1_000_000_000),
            WritePrecision.NS,
        )
    return point


# ─────────────────────────────────────────────
#  Consumer Task: 큐에서 꺼내기 → InfluxDB 저장
# ─────────────────────────────────────────────
async def influx_consumer(stop_event: asyncio.Event) -> None:
    logger.info(
        "Consumer 시작: InfluxDB=%s  bucket=%s  org=%s",
        INFLUX_URL, INFLUX_BUCKET, INFLUX_ORG,
    )
    if not INFLUX_WRITE_ENABLED:
        logger.warning(
            "INFLUX_TOKEN 또는 INFLUX_ORG가 없어 DB 쓰기를 비활성화합니다."
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
            side_payloads: dict[str, dict] = {}

            for side, sample in samples.items():
                pred_rail_deform, crest = predict_rail_deform(sample, side)
                point = build_influx_point(
                    sample,
                    side=side,
                    source=source,
                    pred_rail_deform=pred_rail_deform,
                    crest=crest,
                )

                if INFLUX_WRITE_ENABLED:
                    try:
                        await write_api.write(bucket=INFLUX_BUCKET, record=point)
                        logger.debug("InfluxDB 저장 완료 (%s)", side)
                    except Exception as exc:
                        logger.error(
                            "InfluxDB 쓰기 실패 (건너뜀, %s): %s", side, exc
                        )

                risk = normalize_risk(pred_rail_deform, crest)
                position_mm = sample.get("position_mm")
                position_cm = (
                    float(position_mm) / 10.0
                    if isinstance(position_mm, (int, float))
                    else None
                )
                rail_risk = update_rail_risk(position_cm, risk, side)
                side_payloads[side] = build_side_ws_payload(
                    sample,
                    side=side,
                    pred_rail_deform=pred_rail_deform,
                    crest=crest,
                    rail_risk=rail_risk,
                )

            await ws_manager.broadcast(
                update_downlink_snapshot(source, side_payloads)
            )

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
    else:
        tasks.append(
            asyncio.create_task(
                mqtt_ingest_consumer(stop_event), name="mqtt-ingest-consumer"
            )
        )
        tasks.append(
            asyncio.create_task(
                mqtt_subscriber(stop_event), name="mqtt-subscriber"
            )
        )
    consumer_task = asyncio.create_task(influx_consumer(stop_event), name="influx-consumer")
    tasks.append(consumer_task)
    logger.info(
        "백그라운드 태스크 시작 (demo_mode=%s, mqtt=%s:%d)",
        DEMO_MODE,
        MQTT_HOST,
        MQTT_PORT,
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
UNITY_STATIC = FRONTEND_DIR / "unity"
mimetypes.add_type("application/wasm", ".wasm")


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
        "influx_write_enabled": INFLUX_WRITE_ENABLED,
        "queue_size": sensor_queue.qsize(),
        "queue_max": QUEUE_MAX_SIZE,
        "ws_clients": ws_manager.client_count,
        "mqtt": {
            **mqtt_state,
            "host": MQTT_HOST,
            "port": MQTT_PORT,
            "tls": MQTT_TLS,
            "telemetry_topic": MQTT_TELEMETRY_TOPIC,
            "status_topic": MQTT_STATUS_TOPIC,
            "auth_configured": bool(MQTT_USERNAME and MQTT_PASSWORD),
            "ingest_queue_size": mqtt_ingest_queue.qsize(),
        },
        "sensor_nodes": sensor_node_state,
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
async def rail_risk_reset(side: Optional[str] = None):
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
#  화면 다운링크 WebSocket 엔드포인트
#  센서 업링크는 Mosquitto MQTTS 토픽을 사용한다.
# ─────────────────────────────────────────────
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


if UNITY_STATIC.is_dir():
    app.mount(
        "/unity",
        StaticFiles(directory=str(UNITY_STATIC), html=True),
        name="unity",
    )
