"""
main.py
갠트리 크레인 레일 변형 예측 FastAPI 서버
주행 진동·가속도 수집 → 특징 공학 → RBF로 하부 레일 변형(단차·침하·뒤틀림) 지표 추론

아키텍처:
  [ESP32-S3] --serial--> [Producer Task] --asyncio.Queue--> [Consumer Task] --> [InfluxDB]
       or                                                                  --> [RBF 레일 변형 추론]
  [더미 스트리머]                                                            --> [rail_risk 구간 히트맵] --> [WebSocket /ws]

실행:
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload

WebSocket 테스트:
  websocat ws://localhost:8000/ws
  # 또는 브라우저 콘솔: new WebSocket("ws://localhost:8000/ws")

환경 변수 (.env 파일 또는 shell export):
  SERIAL_PORT      /dev/cu.usbmodem1101
  BAUD_RATE        115200
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
import os
import time
from collections import deque
from contextlib import asynccontextmanager

import numpy as np
import serial
import torch
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client import Point

from ml.train_rbf_surrogate import (
    FEATURE_NAMES,
    WINDOW_LEN,
    RBFSurrogateModel,
    accel_dynamic_magnitude,
    compute_crest_from_window,
)

# ─────────────────────────────────────────────
#  환경 변수 로드 (.env 파일 우선, 없으면 shell 환경변수 사용)
# ─────────────────────────────────────────────
load_dotenv()

SERIAL_PORT: str = os.getenv("SERIAL_PORT", "/dev/cu.usbmodem1101")
BAUD_RATE: int = int(os.getenv("BAUD_RATE", "115200"))
READ_TIMEOUT: float = 2.0
RECONNECT_DELAY: float = 3.0

INFLUX_URL: str = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN: str = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG: str = os.getenv("INFLUX_ORG", "")
INFLUX_BUCKET: str = os.getenv("INFLUX_BUCKET", "crane_data")
DEVICE_ID: str = os.getenv("DEVICE_ID", "esp32-s3")

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

# 서버 메모리에 유지되는 구간별 위험도 (0.0=정상 ~ 1.0=높음). 주행하며 max로 누적.
rail_risk_state: list[float] = [0.0] * RAIL_SEGMENT_COUNT

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


# ─────────────────────────────────────────────
#  유틸리티: 시리얼 포트 열기
# ─────────────────────────────────────────────
def open_serial(port: str, baud: int, timeout: float) -> serial.Serial:
    return serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=timeout,
    )


# ─────────────────────────────────────────────
#  유틸리티: 센서 라인 파싱
#  입력 예시:
#    "AAX:0.12,AAY:-0.05,AAZ:9.81,DIST:23.45,MAX:0.01,MAY:-0.02,MAZ:9.80,GX:0.5,GY:1.2,GZ:-0.3"
#  반환: {"AAX": 0.12, ..., "DIST": 23.45, "MAX": 0.01, ..., "GZ": -0.3}
#        ERR 이거나 숫자 변환 실패 시 해당 키의 값은 None
#
#  AA* : ADXL345 가속도 (m/s²) | DIST : HC-SR04 거리 (cm)
#  MA* : MPU-6050 가속도 (m/s²) | G*  : MPU-6050 자이로 (rad/s)
# ─────────────────────────────────────────────
EXPECTED_KEYS = {"AAX", "AAY", "AAZ", "DIST", "MAX", "MAY", "MAZ", "GX", "GY", "GZ"}


def parse_sensor_line(raw_line: str) -> dict | None:
    if not raw_line:
        return None

    fields: dict = {}
    for token in raw_line.split(","):
        key, sep, value = token.partition(":")
        key = key.strip()
        value = value.strip()

        if not sep or key not in EXPECTED_KEYS:
            continue  # 콜론 누락 또는 알 수 없는 키는 건너뜀

        if value == "ERR" or value == "":
            fields[key] = None
            continue

        try:
            fields[key] = float(value)
        except ValueError:
            fields[key] = None  # 필드 단위로만 무효 처리, 라인 전체는 버리지 않음

    return fields if fields else None


# ─────────────────────────────────────────────
#  AI 추론: RBF 레일 변형 대리 모델 (ml/train_rbf_surrogate.py 산출물)
#  ml_state는 서버 시작 시 lifespan에서 채워지고, 모델 로드 실패 시에도
#  None으로 남아 predict_rail_deform()이 조용히 스킵하도록 설계됨
# ─────────────────────────────────────────────
ml_state: dict = {
    "model": None,
    "device": None,
    "x_mean": None,
    "x_std": None,
    "y_mean": None,
    "y_std": None,
}

# 웨이블릿 디노이징 / 파고율 계산용 가속도 롤링 윈도우
accel_window: deque[float] = deque(maxlen=WINDOW_LEN)


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


def extract_crest_feature(data: dict) -> float:
    """
    가속도 동적 진폭을 롤링 윈도우에 쌓고,
    sym3 웨이블릿 디노이징 후 파고율(Crest Factor)을 계산한다.

    시연용 더미 데이터가 `_demo_crest_target`을 넘기면 그 값을 우선 사용한다
    (위험 구간 CREST≥5.0을 안정적으로 재현하기 위함).
    """
    mag = accel_dynamic_magnitude(
        float(data.get("AAX") or 0.0),
        float(data.get("AAY") or 0.0),
        float(data.get("AAZ") or 9.8),
        float(data.get("MAX") or 0.0),
        float(data.get("MAY") or 0.0),
        float(data.get("MAZ") or 9.8),
    )
    accel_window.append(mag)
    window_arr = np.asarray(accel_window, dtype=np.float64)
    crest = compute_crest_from_window(window_arr)

    demo_target = data.get("_demo_crest_target")
    if demo_target is not None:
        return float(demo_target)
    return crest


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


def update_rail_risk(distance_cm: float | None, risk: float) -> list[float]:
    """현재 위치에 해당하는 구간의 rail_risk를 max 누적 갱신 후 복사본 반환."""
    global rail_risk_state
    if RAIL_SEGMENT_COUNT <= 0 or RAIL_LENGTH_CM <= 0:
        return list(rail_risk_state)
    if distance_cm is None:
        return list(rail_risk_state)

    seg_len = RAIL_LENGTH_CM / RAIL_SEGMENT_COUNT
    idx = int(float(distance_cm) / seg_len)
    idx = max(0, min(idx, RAIL_SEGMENT_COUNT - 1))
    rail_risk_state[idx] = max(rail_risk_state[idx], float(np.clip(risk, 0.0, 1.0)))
    return list(rail_risk_state)


def predict_rail_deform(data: dict) -> tuple[float | None, float | None]:
    """
    센서 원시값 + 웨이블릿/파고율 특징을 결합해 RBF 대리 모델로
    하부 주행 레일 변형 지표를 추론한다.

    Returns:
        (pred_rail_deform, crest) — 실패 시 해당 값은 None
    """
    model = ml_state.get("model")
    crest: float | None = None

    try:
        crest = extract_crest_feature(data)
    except Exception as exc:
        logger.error("파고율 특징 추출 실패 (건너뜀): %s", exc)
        crest = None

    if model is None:
        return None, crest

    try:
        device = ml_state["device"]
        x_mean = ml_state["x_mean"]
        x_std = ml_state["x_std"]
        y_mean = ml_state["y_mean"]
        y_std = ml_state["y_std"]

        # FEATURE_NAMES 순서: 센서 10개 + CREST
        raw_values: list[float] = []
        for i, key in enumerate(FEATURE_NAMES):
            if key == "CREST":
                if crest is None:
                    raw_values.append(float(x_mean[0, i].item()))
                else:
                    raw_values.append(float(crest))
                continue

            val = data.get(key)
            raw_values.append(float(x_mean[0, i].item()) if val is None else float(val))

        x = torch.tensor([raw_values], dtype=torch.float32, device=device)
        x_norm = (x - x_mean) / x_std

        with torch.no_grad():
            pred_norm = model(x_norm)

        pred = float(pred_norm.item() * y_std.item() + y_mean.item())
        return pred, crest
    except Exception as exc:
        logger.error("AI 추론 실패 (건너뜀): %s", exc)
        return None, crest


# ─────────────────────────────────────────────
#  시리얼 포트 사용 가능 여부 확인
# ─────────────────────────────────────────────
def serial_port_available(port: str) -> bool:
    """실제 ESP32가 연결되어 포트를 열 수 있으면 True."""
    try:
        ser = open_serial(port, BAUD_RATE, READ_TIMEOUT)
        ser.close()
        return True
    except Exception:
        return False


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

        aax = float(np.sin(np.radians(roll_deg)) * G_MS2 + np.random.normal(0.0, 0.05))
        aay = float(np.sin(np.radians(pitch_deg)) * G_MS2 + np.random.normal(0.0, 0.05))
        aaz = float(9.8 + peak_g * G_MS2 + np.random.normal(0.0, 0.1))

        max_ = aax + float(np.random.normal(0.0, 0.08))
        may = aay + float(np.random.normal(0.0, 0.08))
        maz = aaz + float(np.random.normal(0.0, 0.08))

        gx = float(np.radians(roll_deg) + np.random.normal(0.0, 0.02))
        gy = float(np.radians(pitch_deg) + np.random.normal(0.0, 0.02))
        gz = float(np.random.normal(0.0, 0.05))

        # 위험 임계치 5.0 이상으로 치솟도록 시연용 파고율 지정
        demo_crest = float(5.0 + 3.0 * impact + np.random.uniform(0.0, 1.0))
    else:
        # 정상 주행: 거의 0에 가까운 미세 가우시안 노이즈
        aax = float(np.random.normal(0.0, 0.005))
        aay = float(np.random.normal(0.0, 0.005))
        aaz = float(9.8 + np.random.normal(0.0, 0.005))
        max_ = float(np.random.normal(0.0, 0.005))
        may = float(np.random.normal(0.0, 0.005))
        maz = float(9.8 + np.random.normal(0.0, 0.005))
        gx = float(np.random.normal(0.0, 0.005))
        gy = float(np.random.normal(0.0, 0.005))
        gz = float(np.random.normal(0.0, 0.005))
        # 정상 범위 파고율 1.0~1.5
        demo_crest = float(np.random.uniform(1.05, 1.45))

    return {
        "AAX": aax,
        "AAY": aay,
        "AAZ": aaz,
        "DIST": float(distance_x),
        "MAX": max_,
        "MAY": may,
        "MAZ": maz,
        "GX": gx,
        "GY": gy,
        "GZ": gz,
        "_demo_crest_target": demo_crest,
        "_source": "demo",
    }


# ─────────────────────────────────────────────
#  더미 스트리머 Task: 시연용 센서 데이터 생성 → 큐 적재
# ─────────────────────────────────────────────
async def dummy_sensor_streamer(stop_event: asyncio.Event) -> None:
    """
    ESP32 미연결 시 1m 플라스틱 크레인 시연용 더미 데이터를 10Hz로 생성한다.
    Consumer가 RBF 추론 후 WebSocket으로 distance_x / CREST / PRED_RAIL_DEFORM을 전송한다.
    """
    logger.info(
        "더미 스트리머 시작 (시연 모드): %.0fcm 레일, %.0fHz, 위험구간 %s~%scm",
        DEMO_RAIL_LENGTH_CM,
        1.0 / DEMO_HZ_INTERVAL,
        DEMO_DANGER_START_CM,
        DEMO_DANGER_END_CM,
    )

    distance_x = 0.0

    while not stop_event.is_set():
        sample = generate_crane_demo_sample(distance_x)
        sample["_received_at"] = time.time()

        if sensor_queue.full():
            try:
                sensor_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        await sensor_queue.put(sample)

        zone = "DANGER" if DEMO_DANGER_START_CM <= distance_x <= DEMO_DANGER_END_CM else "OK"
        logger.info(
            "더미 → x=%.0fcm [%s] crest_target=%.2f",
            distance_x,
            zone,
            sample["_demo_crest_target"],
        )

        distance_x += 1.0
        if distance_x > DEMO_RAIL_LENGTH_CM:
            distance_x = 0.0

        await asyncio.sleep(DEMO_HZ_INTERVAL)

    logger.info("더미 스트리머 종료")


# ─────────────────────────────────────────────
#  Producer Task: 시리얼 읽기 → 큐에 적재
#  readline()은 블로킹 I/O이므로 asyncio.to_thread로 감쌈
# ─────────────────────────────────────────────
async def serial_producer(stop_event: asyncio.Event) -> None:
    logger.info("Producer 시작: 포트=%s, 보드레이트=%d", SERIAL_PORT, BAUD_RATE)
    ser: serial.Serial | None = None

    while not stop_event.is_set():
        # ── 포트 열기 (실패 시 재시도) ──
        if ser is None or not ser.is_open:
            try:
                ser = await asyncio.to_thread(open_serial, SERIAL_PORT, BAUD_RATE, READ_TIMEOUT)
                logger.info("시리얼 포트 연결 성공: %s", SERIAL_PORT)
            except serial.SerialException as exc:
                logger.error("포트 열기 실패: %s — %s초 후 재시도", exc, RECONNECT_DELAY)
                await asyncio.sleep(RECONNECT_DELAY)
                continue

        # ── 1줄 읽기 (블로킹 → to_thread로 이벤트 루프 비블로킹) ──
        try:
            raw_bytes: bytes = await asyncio.to_thread(ser.readline)
        except serial.SerialException as exc:
            logger.warning("시리얼 통신 오류: %s — 재연결 시도", exc)
            try:
                ser.close()
            except Exception:
                pass
            ser = None
            await asyncio.sleep(RECONNECT_DELAY)
            continue

        if not raw_bytes:
            logger.debug("수신 타임아웃 (ESP32 응답 없음)")
            continue

        try:
            raw_line = raw_bytes.decode("utf-8", errors="replace").strip()
        except Exception:
            continue

        if not raw_line:
            continue

        parsed = parse_sensor_line(raw_line)
        if parsed is None:
            logger.debug("파싱 실패 (건너뜀): %s", raw_line)
            continue

        parsed["_received_at"] = time.time()  # 호스트 수신 타임스탬프
        logger.info("수신 → %s", raw_line)

        # ── 큐 적재 (가득 찬 경우 가장 오래된 항목 드롭) ──
        if sensor_queue.full():
            try:
                sensor_queue.get_nowait()
                logger.warning("큐 오버플로 — 가장 오래된 항목 드롭")
            except asyncio.QueueEmpty:
                pass
        await sensor_queue.put(parsed)

    # ── 종료 처리 ──
    if ser and ser.is_open:
        ser.close()
        logger.info("시리얼 포트 정상 종료")


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
            # ── 큐에서 데이터 꺼내기 (0.5초 타임아웃으로 종료 시그널 주기적 확인) ──
            try:
                data: dict = await asyncio.wait_for(sensor_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            # ── InfluxDB Point 구성 ──
            point = (
                Point(MEASUREMENT)
                .tag("device_id", DEVICE_ID)
            )

            field_map = {
                "AAX": "adxl_accel_x", "AAY": "adxl_accel_y", "AAZ": "adxl_accel_z",
                "DIST": "distance_cm",
                "MAX": "mpu_accel_x", "MAY": "mpu_accel_y", "MAZ": "mpu_accel_z",
                "GX": "mpu_gyro_x", "GY": "mpu_gyro_y", "GZ": "mpu_gyro_z",
            }
            for sensor_key, influx_field in field_map.items():
                val = data.get(sensor_key)
                if val is not None:
                    point = point.field(influx_field, float(val))

            # ── AI 추론: 웨이블릿 디노이징 + 파고율 → RBF 레일 변형 예측 ──
            pred_rail_deform, crest = predict_rail_deform(data)
            if pred_rail_deform is not None:
                point = point.field("pred_rail_deform", pred_rail_deform)
            if crest is not None:
                point = point.field("crest_factor", float(crest))

            # ── InfluxDB 쓰기 (실패해도 서버 다운 없이 에러 로그만 기록) ──
            try:
                await write_api.write(bucket=INFLUX_BUCKET, record=point)
                logger.debug("InfluxDB 저장 완료")
            except Exception as exc:
                logger.error("InfluxDB 쓰기 실패 (건너뜀): %s", exc)

            # ── 레일 구간 위험도 히트맵 갱신 (Godot 세그먼트 시각화용) ──
            risk = normalize_risk(pred_rail_deform, crest)
            rail_risk = update_rail_risk(data.get("DIST"), risk)

            # ── WebSocket 브로드캐스트 ──
            # 연결된 클라이언트가 없으면 broadcast() 내부에서 즉시 반환됨
            ws_payload = {
                "ts": data.get("_received_at"),
                "distance_x": data.get("DIST"),  # Godot / 시연용 크레인 위치 (cm)
                "AAX": data.get("AAX"),
                "AAY": data.get("AAY"),
                "AAZ": data.get("AAZ"),
                "DIST": data.get("DIST"),
                "MAX": data.get("MAX"),
                "MAY": data.get("MAY"),
                "MAZ": data.get("MAZ"),
                "GX": data.get("GX"),
                "GY": data.get("GY"),
                "GZ": data.get("GZ"),
                "CREST": crest,
                "PRED_RAIL_DEFORM": pred_rail_deform,
                "rail_risk": rail_risk,  # 구간별 0~1 위험도 배열
                "rail_length_cm": RAIL_LENGTH_CM,
                "segment_count": RAIL_SEGMENT_COUNT,
                "device_id": DEVICE_ID,
                "source": data.get("_source", "serial"),
            }
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

    # 시리얼 포트가 없으면 시연용 더미 스트리머로 대체
    port_ok = await asyncio.to_thread(serial_port_available, SERIAL_PORT)
    if port_ok:
        producer_task = asyncio.create_task(serial_producer(stop_event), name="serial-producer")
        logger.info("시리얼 포트 감지 → 실제 ESP32 Producer 시작 (%s)", SERIAL_PORT)
    else:
        producer_task = asyncio.create_task(
            dummy_sensor_streamer(stop_event), name="dummy-streamer"
        )
        logger.warning(
            "시리얼 포트 미연결 (%s) → 1m 플라스틱 크레인 시연용 더미 스트리머 시작",
            SERIAL_PORT,
        )

    consumer_task = asyncio.create_task(influx_consumer(stop_event), name="influx-consumer")
    logger.info("백그라운드 태스크 시작 (data-source=%s, Consumer)", producer_task.get_name())

    try:
        yield  # ← 서버 가동 중
    finally:
        logger.info("서버 종료 요청 — 태스크 종료 대기 중...")
        stop_event.set()

        await asyncio.gather(producer_task, consumer_task, return_exceptions=True)
        logger.info("모든 백그라운드 태스크 종료 완료")


# ─────────────────────────────────────────────
#  FastAPI 앱
# ─────────────────────────────────────────────
app = FastAPI(
    title="Crane Rail Deformation API",
    description="갠트리 크레인 주행 진동 계측 및 하부 레일 변형(단차·침하·뒤틀림) 예측 서버",
    version="0.2.0",
    lifespan=lifespan,
)


# ─────────────────────────────────────────────
#  엔드포인트
# ─────────────────────────────────────────────
@app.get("/", summary="헬스체크")
async def health_check():
    """서버 상태 및 큐 적재 현황을 반환합니다."""
    return {
        "status": "ok",
        "serial_port": SERIAL_PORT,
        "influx_url": INFLUX_URL,
        "influx_bucket": INFLUX_BUCKET,
        "queue_size": sensor_queue.qsize(),
        "queue_max": QUEUE_MAX_SIZE,
        "ws_clients": ws_manager.client_count,
        "ai_model_loaded": ml_state.get("model") is not None,
        "ai_model_device": str(ml_state.get("device")) if ml_state.get("device") else None,
        "demo_mode": not serial_port_available(SERIAL_PORT),
    }


@app.get("/queue/size", summary="큐 현재 크기 조회")
async def queue_size():
    return {"queue_size": sensor_queue.qsize()}


# ─────────────────────────────────────────────
#  WebSocket 엔드포인트
#  클라이언트: ws://localhost:8000/ws
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
