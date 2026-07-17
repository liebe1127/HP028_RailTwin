"""
main.py
크레인 IoT 센서 데이터 수집 FastAPI 서버

아키텍처:
  [ESP32-S3] --serial--> [Producer Task] --asyncio.Queue--> [Consumer Task] --> [InfluxDB]
                                                                             --> [WebSocket /ws]

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
"""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager

import serial
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client import Point

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

            # ── InfluxDB 쓰기 (실패해도 서버 다운 없이 에러 로그만 기록) ──
            try:
                await write_api.write(bucket=INFLUX_BUCKET, record=point)
                logger.debug("InfluxDB 저장 완료")
            except Exception as exc:
                logger.error("InfluxDB 쓰기 실패 (건너뜀): %s", exc)

            # ── WebSocket 브로드캐스트 ──
            # 연결된 클라이언트가 없으면 broadcast() 내부에서 즉시 반환됨
            ws_payload = {
                "ts": data.get("_received_at"),
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
                "device_id": DEVICE_ID,
            }
            await ws_manager.broadcast(ws_payload)

            sensor_queue.task_done()

    logger.info("Consumer 종료")


# ─────────────────────────────────────────────
#  FastAPI lifespan: 서버 시작/종료 시 백그라운드 태스크 관리
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = asyncio.Event()

    producer_task = asyncio.create_task(serial_producer(stop_event), name="serial-producer")
    consumer_task = asyncio.create_task(influx_consumer(stop_event), name="influx-consumer")

    logger.info("백그라운드 태스크 2개 시작 (Producer, Consumer)")

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
    title="Crane IoT Sensor API",
    description="ESP32-S3 센서 데이터 수집 및 InfluxDB 저장 서버",
    version="0.1.0",
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
