"""
ESP32-S3 → MacBook 시리얼 수신 프로토타입
ADXL345(가속도) + HC-SR04(초음파 거리) 데이터를 실시간으로 수신합니다.

[맥북에서 포트 이름 찾는 방법]
터미널에서 아래 명령어를 실행하면 연결된 시리얼 포트 목록이 출력됩니다.
  $ ls /dev/cu.*
출력 예시:
  /dev/cu.usbmodem1101        ← USB CDC (Arduino, ESP32-S3 native USB)
  /dev/cu.usbserial-10        ← CP2102 / CH340 USB-UART 칩 사용 시
ESP32-S3를 C to C 케이블로 직결한 경우 보통 /dev/cu.usbmodem... 형태입니다.
"""

import serial
import serial.tools.list_ports
import time

# ─────────────────────────────────────────────
# 설정값 (환경에 맞게 수정하세요)
# ─────────────────────────────────────────────

# 맥북에서 $ ls /dev/cu.* 실행 후 확인한 포트 이름으로 바꿔주세요.
SERIAL_PORT = "/dev/cu.usbmodem1101"

BAUD_RATE = 115200          # ESP32 펌웨어와 동일하게 맞춤
READ_TIMEOUT = 2.0          # readline() 최대 대기 시간 (초)
RECONNECT_DELAY = 3.0       # 연결 끊김 후 재시도 대기 시간 (초)

# ─────────────────────────────────────────────


def parse_sensor_line(raw_line: str) -> dict | None:
    """
    ESP32가 보내는 한 줄 데이터를 파싱합니다.

    예상 포맷 (ESP32 펌웨어 출력 예시):
      AX:0.12,AY:-0.05,AZ:9.81,DIST:23.45
    포맷이 다를 경우 이 함수만 수정하면 됩니다.

    Returns:
        dict  - 파싱 성공 시 필드 딕셔너리
        None  - 빈 줄이거나 파싱 실패 시
    """
    if not raw_line:
        return None

    try:
        fields = {}
        for token in raw_line.split(","):
            key, _, value = token.partition(":")
            key = key.strip()
            value = value.strip()
            # 펌웨어가 측정 실패 시 "ERR" 문자열을 보내는 경우를 처리
            if value == "ERR":
                fields[key] = None
            else:
                fields[key] = float(value)
        return fields if fields else None
    except ValueError:
        return None


def format_sensor_data(data: dict) -> str:
    """파싱된 데이터를 터미널 출력용 문자열로 변환합니다."""
    parts = []
    accel_keys = [("AX", "m/s²"), ("AY", "m/s²"), ("AZ", "m/s²")]
    for key, unit in accel_keys:
        if key in data:
            parts.append(f"{key}: {data[key]:+7.3f} {unit}")

    if "DIST" in data:
        dist_val = data["DIST"]
        if dist_val is None:
            parts.append("DIST:    ERR cm")
        else:
            parts.append(f"DIST: {dist_val:6.2f} cm")

    return "  |  ".join(parts) if parts else str(data)


def open_serial(port: str, baud: int, timeout: float) -> serial.Serial:
    """시리얼 포트를 열고 Serial 객체를 반환합니다."""
    ser = serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=timeout,
    )
    return ser


def main() -> None:
    print("=" * 60)
    print("  ESP32-S3 시리얼 수신기 시작")
    print(f"  포트: {SERIAL_PORT}  |  보드레이트: {BAUD_RATE}")
    print("  종료하려면 Ctrl+C 를 누르세요.")
    print("=" * 60)

    ser: serial.Serial | None = None

    try:
        ser = open_serial(SERIAL_PORT, BAUD_RATE, READ_TIMEOUT)
        print(f"[OK] {SERIAL_PORT} 포트 연결 성공\n")

        while True:
            try:
                raw_bytes = ser.readline()

                # readline()이 timeout 내에 데이터를 못 받으면 빈 bytes 반환
                if not raw_bytes:
                    print("[WARN] 수신 타임아웃 — ESP32 응답 없음")
                    continue

                # utf-8 디코딩 + 앞뒤 공백·줄바꿈 제거
                raw_line = raw_bytes.decode("utf-8", errors="replace").strip()

                if not raw_line:
                    continue

                # 화면 출력 (원본)
                timestamp = time.strftime("%H:%M:%S")
                print(f"[{timestamp}] RAW: {raw_line}")

                # 구조화 파싱
                parsed = parse_sensor_line(raw_line)
                if parsed:
                    print(f"         ↳  {format_sensor_data(parsed)}")

                # ──────────────────────────────────────────────────────
                # TODO: 여기서 데이터를 FastAPI 큐(Queue)로 전달하거나 DB에 저장
                #
                # 예시 1 – FastAPI asyncio.Queue 연동:
                #   await sensor_queue.put(parsed)
                #
                # 예시 2 – InfluxDB write:
                #   influx_client.write(bucket, org, build_influx_point(parsed))
                # ──────────────────────────────────────────────────────

            except serial.SerialException as exc:
                # 케이블 분리, 포트 점유 해제 등 통신 중 에러
                print(f"\n[ERROR] 시리얼 통신 오류: {exc}")
                print(f"  {RECONNECT_DELAY:.0f}초 후 재연결을 시도합니다...")

                if ser and ser.is_open:
                    ser.close()

                time.sleep(RECONNECT_DELAY)

                try:
                    ser = open_serial(SERIAL_PORT, BAUD_RATE, READ_TIMEOUT)
                    print(f"[OK] 재연결 성공\n")
                except serial.SerialException as reconnect_exc:
                    print(f"[ERROR] 재연결 실패: {reconnect_exc}")
                    print("  케이블과 포트 이름을 확인한 후 프로그램을 다시 실행하세요.")
                    raise SystemExit(1) from reconnect_exc

            except UnicodeDecodeError as exc:
                # 드물지만 바이너리 노이즈가 섞일 때 발생
                print(f"[WARN] 디코딩 오류 (라인 건너뜀): {exc}")
                continue

    except KeyboardInterrupt:
        # Ctrl+C 로 정상 종료
        print("\n\n[INFO] 사용자 종료 요청 (Ctrl+C)")

    except serial.SerialException as exc:
        # 초기 포트 열기 실패
        print(f"\n[ERROR] 포트를 열 수 없습니다: {exc}")
        print(f"  1. $ ls /dev/cu.*  로 포트 이름을 확인하세요.")
        print(f"  2. SERIAL_PORT 변수를 올바른 값으로 수정하세요.")
        print(f"  3. 다른 프로그램(Arduino IDE 시리얼 모니터 등)이 포트를 점유하고 있지 않은지 확인하세요.")

    finally:
        # 어떤 경로로 종료되든 포트를 안전하게 닫음
        if ser and ser.is_open:
            ser.close()
            print("[INFO] 시리얼 포트 정상 종료.")


if __name__ == "__main__":
    main()
