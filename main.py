"""
main.py
갠트리 크레인 레일 이상 구간 FastAPI 서버
주행 중 간격·기울기·위치 수집 → 규칙 판정 → 웹 대시보드·Unity WebGL

아키텍처:
  [ESP32-C3] --MQTT QoS 1--> [Mosquitto] --> [MQTT Subscriber] --> [asyncio.Queue]
  [더미 스트리머] -----------------------------------------------------------> [Consumer Task]
                                                                                 --> [InfluxDB]
                                                                                 --> [4분류 규칙 판정]
                                                                                 --> [left/right rail_risk · defects · motion]
                                                                                 --> [WebSocket /ws]

실행:
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload

환경 변수 (.env 파일 또는 shell export):
  MQTT_HOST, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD, MQTT_TLS
  DEMO_MODE, MIRROR_RIGHT_TO_LEFT
  INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET
  DEVICE_ID, RAIL_LENGTH_CM, RAIL_SEGMENT_COUNT
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import numpy as np
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client import Point, WritePrecision

from rail_defect import DefectRuleEngine
from run_export import (
    ExportTooLarge,
    build_download,
    content_disposition,
    experiment_labels,
    fetch_run_samples,
    fetch_run_starts,
    render_runs_page,
    validate_boot_id,
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
demo_stop_event: asyncio.Event | None = None
demo_task: asyncio.Task | None = None
# 중간 시연: left ESP32가 없으면 right WS 페이로드를 left에 복제 (대시보드·Unity 공통)
MIRROR_RIGHT_TO_LEFT: bool = os.getenv(
    "MIRROR_RIGHT_TO_LEFT", "true"
).strip().lower() in {
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

# 시연용 더미 스트리머 (1m 축소 레일, 갠트리 크레인 주행)
DEMO_HZ_INTERVAL = 0.1          # 10Hz
DEMO_RAIL_LENGTH_CM = 100.0
DEMO_JOINT_CM = (20.0, 25.0)
DEMO_VERTICAL_CM = (45.0, 70.0)
DEMO_CROSS_CM = (80.0, 90.0)
G_MS2 = 9.80665

# 레일 구간 이상 히트맵 (웹·Unity WebGL)
RAIL_LENGTH_CM: float = float(os.getenv("RAIL_LENGTH_CM", str(DEMO_RAIL_LENGTH_CM)))
RAIL_SEGMENT_COUNT: int = int(os.getenv("RAIL_SEGMENT_COUNT", "20"))

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
mimetypes.add_type("application/wasm", ".wasm")

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
#  규칙 판정: 이음부 단차 / 수직 변형 / 좌우 높이차
# ─────────────────────────────────────────────
defect_engine = DefectRuleEngine(
    segment_count=RAIL_SEGMENT_COUNT,
    rail_length_cm=RAIL_LENGTH_CM,
)
mqtt_command_client: mqtt.Client | None = None
last_motion_command: str | None = None


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
    """누적 단계 색과 4분류 기준선을 초기화한다. 판정은 좌·우 쌍이라 항상 같이 지운다."""
    del side
    for s in RAIL_SIDES:
        rail_risk_state[s] = [0.0] * RAIL_SEGMENT_COUNT
    defect_engine.reset()
    return {s: list(rail_risk_state[s]) for s in RAIL_SIDES}


def publish_position_zero() -> bool:
    """대시보드 위치 리셋. 보드 엔코더를 0으로 만든다."""
    client = mqtt_command_client
    if client is None or not mqtt_state.get("connected"):
        return False
    payload = json.dumps({"action": "zero"}, ensure_ascii=False)
    for device_id in ("rail-left-01", "rail-right-01"):
        client.publish(
            f"{MQTT_TOPIC_PREFIX}/{device_id}/command",
            payload,
            qos=1,
            retain=False,
        )
    return True


def publish_motion_command(motion: str) -> None:
    """주의는 감속, 위험 진입 전은 정지. 토픽 rail/v1/nodes/{id}/command."""
    global last_motion_command
    if motion not in {"cruise", "slow", "stop"} or motion == last_motion_command:
        return
    last_motion_command = motion
    client = mqtt_command_client
    if client is None or not mqtt_state.get("connected"):
        return
    payload = json.dumps({"motion": motion}, ensure_ascii=False)
    for device_id in ("rail-left-01", "rail-right-01"):
        client.publish(
            f"{MQTT_TOPIC_PREFIX}/{device_id}/command",
            payload,
            qos=1,
            retain=False,
        )


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
    evaluation: dict,
    rail_risk: list[float],
    defects: list[dict],
) -> dict:
    """웹·Unity left/right 객체 하나에 넣을 레일별 페이로드."""
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
        "roll_deg": evaluation.get("tilt_deg", evaluation.get("roll_deg")),
        "distance_delta_mm": evaluation.get("delta_mm", evaluation.get("distance_delta_mm")),
        "m_mm": evaluation.get("m_mm"),
        "delta_mm": evaluation.get("delta_mm"),
        "dm_dx": evaluation.get("dm_dx"),
        "ddelta_dx": evaluation.get("ddelta_dx"),
        "apeak": evaluation.get("apeak"),
        "tilt_deg": evaluation.get("tilt_deg"),
        "defect_type": evaluation.get("defect_type"),
        "stage": evaluation.get("stage"),
        "motion": evaluation.get("motion"),
        "magnitude_mm": evaluation.get("magnitude_mm"),
        "limit_mm": evaluation.get("limit_mm"),
        "limit_source": evaluation.get("limit_source"),
        "remaining_s": evaluation.get("remaining_s"),
        "rate_mm_per_s": evaluation.get("rate_mm_per_s"),
        "relative_fast": evaluation.get("relative_fast"),
        "pass_count": evaluation.get("pass_count"),
        "abnormal_score": evaluation.get("score"),
        "defects": defects,
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
    }


def update_downlink_snapshot(source: str, side_payloads: dict[str, dict]) -> dict:
    """독립적으로 도착한 좌·우 ESP32 결과를 최신 양측 스냅샷으로 결합한다."""
    for side, payload in side_payloads.items():
        if side in RAIL_SIDES:
            latest_ws_payload_by_side[side] = payload
    snapshot = {
        "source": source,
        "motion": _snapshot_motion(side_payloads),
        "simulation": source == "demo",
        **{
            side: latest_ws_payload_by_side[side]
            for side in RAIL_SIDES
            if side in latest_ws_payload_by_side
        },
    }
    return apply_right_to_left_mirror(snapshot)


def _snapshot_motion(side_payloads: dict[str, dict]) -> str:
    rank = {"cruise": 0, "slow": 1, "stop": 2}
    chosen = "cruise"
    for payload in side_payloads.values():
        motion = payload.get("motion")
        if motion in rank and rank[motion] > rank[chosen]:
            chosen = motion
    return chosen


def apply_right_to_left_mirror(snapshot: dict) -> dict:
    """시연용: left 노드가 끊겨 있으면 right 페이로드를 left에 복제해 /ws로 보낸다."""
    if not MIRROR_RIGHT_TO_LEFT:
        return snapshot
    right = snapshot.get("right")
    if not isinstance(right, dict):
        return snapshot
    left_connected = bool(sensor_node_state.get("left", {}).get("connected"))
    if left_connected:
        return snapshot

    left = dict(right)
    left["rail_side"] = "left"
    left["device_id"] = "rail-left-01 (right 복제)"
    left["_mirrored_from"] = "right"
    risk = right.get("rail_risk")
    if isinstance(risk, list):
        mirrored_risk = [float(v) for v in risk]
        left["rail_risk"] = mirrored_risk
        rail_risk_state["left"] = list(mirrored_risk)

    out = dict(snapshot)
    out["left"] = left
    out["mirror_right_to_left"] = True
    latest_ws_payload_by_side["left"] = left
    return out


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
        if demo_is_running():
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
    global mqtt_command_client
    mqtt_command_client = client
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
#  시연용 더미 센서 샘플 생성 (축소 레일 위 갠트리 주행)
# ─────────────────────────────────────────────
def demo_levels(lap: int) -> tuple[float, float, float]:
    """같은 구간을 다시 지날수록 결함이 커지는 시연용 크기. 화면에는 시뮬레이션으로 표시한다."""
    step = max(lap - 1, 0)
    return 1.2 + 0.35 * step, 1.3 + 0.35 * step, 6.0 + 0.40 * step


def generate_crane_demo_sample(distance_x: float, side: str, lap: int) -> dict:
    """
    1m 레일의 세 구간을 서로 다른 지문으로 만든다.

    - 20~25cm 이음부 단차: 양쪽 간격이 짧게 뛰고 세로 가속도가 튄다
    - 45~70cm 수직 변형: 양쪽 간격만 완만히 늘고 충격은 없다
    - 80~90cm 좌우 높이차: 왼쪽 간격만 늘고 기울기 부호가 같다
    """
    joint_mm, vertical_mm, cross_mm = demo_levels(lap)
    gap = 4.0
    accel_x = 0.0
    accel_z = G_MS2
    if DEMO_JOINT_CM[0] <= distance_x < DEMO_JOINT_CM[1]:
        risen = 1.0 if distance_x >= DEMO_JOINT_CM[0] + 1.0 else 0.0
        gap = 4.0 + joint_mm * risen
        if DEMO_JOINT_CM[0] <= distance_x <= DEMO_JOINT_CM[0] + 1.5:
            accel_z = G_MS2 + 8.0
    elif DEMO_VERTICAL_CM[0] <= distance_x <= DEMO_VERTICAL_CM[1]:
        span = DEMO_VERTICAL_CM[1] - DEMO_VERTICAL_CM[0]
        gap = 4.0 + vertical_mm * ((distance_x - DEMO_VERTICAL_CM[0]) / span)
    elif DEMO_CROSS_CM[0] <= distance_x <= DEMO_CROSS_CM[1]:
        if side == "left":
            gap = 4.0 + cross_mm
        roll_deg = 4.0
        accel_x = float(np.sin(np.radians(roll_deg)) * G_MS2)
        accel_z = float(np.cos(np.radians(roll_deg)) * G_MS2)
    else:
        gap = float(4.0 + np.random.normal(0.0, 0.01))
        accel_x = float(np.random.normal(0.0, 0.01))
        accel_z = float(G_MS2 + np.random.normal(0.0, 0.01))

    accel_y = float(np.random.normal(0.0, 0.01))
    sensor_distance_mm = float(gap)
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
        "gyro_x": float(np.random.normal(0.0, 0.005)),
        "gyro_y": float(np.random.normal(0.0, 0.005)),
        "gyro_z": float(np.random.normal(0.0, 0.005)),
        "_source": "demo",
    }


# ─────────────────────────────────────────────
#  더미 스트리머 Task: 시연용 센서 데이터 생성 → 큐 적재
# ─────────────────────────────────────────────
async def dummy_sensor_streamer(stop_event: asyncio.Event) -> None:
    """
    ESP32 미연결 시 1m 축소 레일 위 갠트리 주행 더미 데이터를 10Hz로 생성한다.
    Consumer가 규칙 판정 후 WebSocket으로 left/right 페이로드를 전송한다.
    """
    logger.info(
        "더미 스트리머 시작 (시연 모드): %.0fcm 레일, %.0fHz, 이음부 %.0f~%.0fcm / 수직 %.0f~%.0fcm / 좌우높이 %.0f~%.0fcm",
        DEMO_RAIL_LENGTH_CM,
        1.0 / DEMO_HZ_INTERVAL,
        DEMO_JOINT_CM[0],
        DEMO_JOINT_CM[1],
        DEMO_VERTICAL_CM[0],
        DEMO_VERTICAL_CM[1],
        DEMO_CROSS_CM[0],
        DEMO_CROSS_CM[1],
    )

    distance_x = 0.0
    sample_seq = 1
    lap = 1

    while not stop_event.is_set():
        ts = time.time()
        left = generate_crane_demo_sample(distance_x, "left", lap)
        right = generate_crane_demo_sample(distance_x, "right", lap)
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
        record_sensor_node_batch(left)
        record_sensor_node_batch(right)

        zone = "OK"
        if DEMO_JOINT_CM[0] <= distance_x < DEMO_JOINT_CM[1]:
            zone = "JOINT"
        elif DEMO_VERTICAL_CM[0] <= distance_x <= DEMO_VERTICAL_CM[1]:
            zone = "VERTICAL"
        elif DEMO_CROSS_CM[0] <= distance_x <= DEMO_CROSS_CM[1]:
            zone = "CROSS"
        logger.info(
            "더미 → lap=%d x=%.0fcm [%s] left_gap=%.2fmm right_gap=%.2fmm",
            lap,
            distance_x,
            zone,
            left["sensor_distance_mm"],
            right["sensor_distance_mm"],
        )

        distance_x += 1.0
        if distance_x > DEMO_RAIL_LENGTH_CM:
            distance_x = 0.0
            lap += 1
        sample_seq += 1

        await asyncio.sleep(DEMO_HZ_INTERVAL)

    logger.info("더미 스트리머 종료")


def demo_is_running() -> bool:
    return demo_task is not None and not demo_task.done()


def start_demo_streamer() -> bool:
    """보드 없이 화면을 보여줄 때 더미 주행을 켠다. 이미 켜져 있으면 그대로 둔다."""
    global demo_stop_event, demo_task
    if demo_is_running():
        return False
    reset_rail_risk_state()
    demo_stop_event = asyncio.Event()
    demo_task = asyncio.create_task(
        dummy_sensor_streamer(demo_stop_event), name="dummy-streamer"
    )
    return True


async def stop_demo_streamer() -> bool:
    """더미 주행만 멈춘다. MQTT 수신과 서버는 유지한다."""
    global demo_stop_event, demo_task
    if not demo_is_running() or demo_stop_event is None or demo_task is None:
        return False
    demo_stop_event.set()
    await demo_task
    demo_task = None
    return True


def build_influx_point(
    sample: dict,
    *,
    side: str,
    source: str,
    evaluation: dict,
) -> Point:
    """현재 센서 계약과 규칙 판정 결과를 InfluxDB Point로 변환한다."""
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
        "temp_c": "mpu_temp_c",
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

    for key, influx_field in (
        ("tilt_deg", "tilt_deg"),
        ("roll_deg", "roll_deg"),
        ("delta_mm", "delta_mm"),
        ("distance_delta_mm", "distance_delta_mm"),
        ("m_mm", "m_mm"),
        ("dm_dx", "dm_dx"),
        ("ddelta_dx", "ddelta_dx"),
        ("apeak", "apeak"),
        ("magnitude_mm", "magnitude_mm"),
        ("score", "abnormal_score"),
    ):
        value = evaluation.get(key)
        if isinstance(value, (int, float)):
            point = point.field(influx_field, float(value))

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
            if "left" in samples and "right" in samples:
                evaluation = defect_engine.evaluate_pair(samples["left"], samples["right"])
            elif samples:
                side, sample = next(iter(samples.items()))
                evaluation = defect_engine.evaluate_side(sample, side)
            else:
                evaluation = {"ready": False}

            if source != "demo" and evaluation.get("ready") and evaluation.get("motion"):
                publish_motion_command(str(evaluation["motion"]))

            for side, sample in samples.items():
                point = build_influx_point(
                    sample,
                    side=side,
                    source=source,
                    evaluation=evaluation,
                )

                if INFLUX_WRITE_ENABLED:
                    try:
                        await write_api.write(bucket=INFLUX_BUCKET, record=point)
                        logger.debug("InfluxDB 저장 완료 (%s)", side)
                    except Exception as exc:
                        logger.error(
                            "InfluxDB 쓰기 실패 (건너뜀, %s): %s", side, exc
                        )

                risk_key = "rail_risk_left" if side == "left" else "rail_risk_right"
                rail_risk = list(evaluation.get(risk_key) or rail_risk_state.get(side) or [])
                if len(rail_risk) == RAIL_SEGMENT_COUNT:
                    rail_risk_state[side] = rail_risk
                defects = list(evaluation.get("defects") or [])
                side_payloads[side] = build_side_ws_payload(
                    sample,
                    side=side,
                    evaluation=evaluation,
                    rail_risk=rail_risk,
                    defects=defects,
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
    stop_event = asyncio.Event()
    tasks: list[asyncio.Task] = []
    if DEMO_MODE:
        start_demo_streamer()
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
        if demo_stop_event is not None:
            demo_stop_event.set()
        if demo_task is not None:
            tasks.append(demo_task)

        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("모든 백그라운드 태스크 종료 완료")


# ─────────────────────────────────────────────
#  FastAPI 앱
# ─────────────────────────────────────────────
app = FastAPI(
    title="Crane Rail Monitoring API",
    description="갠트리 크레인 주행 중 하부 레일 이상 구간 규칙 판정 서버",
    version="0.4.0",
    lifespan=lifespan,
)

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
DASHBOARD_HTML = FRONTEND_DIR / "index.html"
UNITY_STATIC = FRONTEND_DIR / "unity"


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
        "rule_engine": True,
        "unity_webgl": (UNITY_STATIC / "Build").is_dir(),
        "demo_mode": DEMO_MODE,
        "demo_running": demo_is_running(),
        "mirror_right_to_left": MIRROR_RIGHT_TO_LEFT,
    }


@app.get("/queue/size", summary="큐 현재 크기 조회")
async def queue_size():
    return {"queue_size": sensor_queue.qsize()}


def _influx_read_args() -> dict:
    return {
        "url": INFLUX_URL,
        "token": INFLUX_TOKEN,
        "org": INFLUX_ORG,
        "bucket": INFLUX_BUCKET,
    }


@app.get("/runs", response_class=HTMLResponse, summary="저장된 주행 CSV 목록")
async def runs_page():
    """최근 90일의 전원 구간마다 CSV 한 파일 링크를 보여 준다."""
    if not INFLUX_WRITE_ENABLED:
        return HTMLResponse(
            render_runs_page([], "InfluxDB 연결 정보가 없어 주행을 읽을 수 없습니다."),
            status_code=503,
        )
    try:
        starts = await fetch_run_starts(**_influx_read_args())
    except Exception:
        logger.exception("주행 목록 조회 실패")
        return HTMLResponse(
            render_runs_page([], "InfluxDB에서 주행 목록을 읽지 못했습니다."),
            status_code=502,
        )
    return HTMLResponse(render_runs_page(experiment_labels(starts)))


@app.get("/runs/{boot_id}.csv", summary="주행 하나의 전체 항목 CSV")
async def download_run_csv(boot_id: str):
    """간격·위치·가속도·자이로·온도·판정값을 평균 없이 한 파일로 받는다."""
    try:
        safe_id = validate_boot_id(boot_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="boot_id 형식이 아닙니다") from None
    if not INFLUX_WRITE_ENABLED:
        raise HTTPException(status_code=503, detail="InfluxDB 연결 정보가 없습니다")
    try:
        samples = await fetch_run_samples(**_influx_read_args(), boot_id=safe_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="boot_id 형식이 아닙니다") from None
    except Exception:
        logger.exception("주행 CSV 조회 실패 boot_id=%s", safe_id)
        raise HTTPException(status_code=502, detail="InfluxDB에서 이 주행을 읽지 못했습니다") from None
    if not samples:
        raise HTTPException(status_code=404, detail="이 주행에 저장된 샘플이 없습니다")
    label = None
    try:
        starts = await fetch_run_starts(**_influx_read_args())
        label = next(
            (item["label"] for item in experiment_labels(starts) if item["boot_id"] == safe_id),
            None,
        )
    except Exception:
        logger.exception("주행 이름 조회 실패 boot_id=%s", safe_id)
    try:
        body, filename = build_download(samples, safe_id, label)
    except ExportTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": content_disposition(filename, safe_id)},
    )


@app.get("/dashboard", summary="레일 변형 웹 대시보드")
async def dashboard():
    """같은 FastAPI 프로세스에서 frontend/index.html 을 연다."""
    if not DASHBOARD_HTML.is_file():
        return {"error": "frontend/index.html 이 서버에 없습니다"}
    return FileResponse(DASHBOARD_HTML)


@app.post("/demo", summary="시연용 더미 주행 켜기/끄기")
async def set_demo(body: dict):
    """보드 없이 대시보드를 보여줄 때 더미 주행을 켜거나 끈다."""
    running = bool(body.get("running"))
    if running:
        start_demo_streamer()
    else:
        await stop_demo_streamer()
    logger.info("더미 주행 %s", "시작" if demo_is_running() else "정지")
    return {"ok": True, "demo_running": demo_is_running()}


@app.post("/position/reset", summary="대차 위치를 시작점으로 되돌린다")
async def position_reset():
    """보드 엔코더를 0으로 만든다. 실물을 시작 자리에 둔 뒤에 누른다."""
    if not publish_position_zero():
        return {"ok": False, "error": "보드로 위치 리셋 명령을 보내지 못했습니다"}
    logger.info("위치 리셋 명령을 보드에 보냈습니다")
    return {"ok": True}


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
