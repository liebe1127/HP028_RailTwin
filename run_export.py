"""한 번의 전원(boot_id)에 쌓인 InfluxDB 샘플을 CSV 한 파일로 만든다.

Grafana 그래프는 화면 픽셀에 맞춰 평균을 낸 뒤 시간을 초까지만 적는다.
이 모듈은 그 평균을 거치지 않고, 보드가 보낸 uptime_us로 좌·우를 한 줄에 맞춘다.
"""

from __future__ import annotations

import csv
import html
import io
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import quote

from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync

from sensor_contract import BOOT_ID_PATTERN

SEOUL = timezone(timedelta(hours=9))
MAX_ROWS = 200_000

# build_influx_point가 쓰는 필드. 헤더 순서는 실험에서 먼저 보는 값이다.
EXPORT_FIELDS: tuple[str, ...] = (
    "position_mm",
    "sensor_distance_mm",
    "mpu_accel_x",
    "mpu_accel_y",
    "mpu_accel_z",
    "mpu_gyro_x",
    "mpu_gyro_y",
    "mpu_gyro_z",
    "mpu_temp_c",
    "adc_raw",
    "adc_voltage_v",
    "sensor_voltage_v",
    "sample_seq",
    "batch_seq",
    "dropped_batches",
    "status_flags",
    "tilt_deg",
    "roll_deg",
    "delta_mm",
    "distance_delta_mm",
    "m_mm",
    "dm_dx",
    "ddelta_dx",
    "apeak",
    "magnitude_mm",
    "abnormal_score",
)
INTEGER_FIELDS = frozenset(
    {
        "adc_raw",
        "sample_seq",
        "batch_seq",
        "dropped_batches",
        "status_flags",
    }
)
META_FIELDS = ("device_id", "firmware_version", "source")
SIDES = ("left", "right")

SAMPLE_FLUX = """
from(bucket: bucket)
  |> range(start: -90d)
  |> filter(fn: (r) => r._measurement == "crane_sensor" and r.boot_id == boot_id)
  |> sort(columns: ["_time"])
"""

INDEX_FLUX = """
from(bucket: bucket)
  |> range(start: -90d)
  |> filter(fn: (r) => r._measurement == "crane_sensor" and r._field == "position_mm")
  |> filter(fn: (r) => exists r.boot_id and r.boot_id != "")
  |> group(columns: ["boot_id"])
  |> min(column: "_time")
  |> group()
"""


class ExportTooLarge(Exception):
    """한 전원 구간의 샘플이 CSV 한 파일로 받기엔 너무 많을 때."""


def validate_boot_id(boot_id: str) -> str:
    if not isinstance(boot_id, str) or not BOOT_ID_PATTERN.fullmatch(boot_id):
        raise ValueError("boot_id")
    return boot_id.lower()


def format_seoul(moment: datetime) -> str:
    """마이크로초까지 적힌 서울 시각. 예: 2026-09-26T21:08:41.123456+09:00"""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(SEOUL)
    return local.strftime("%Y-%m-%dT%H:%M:%S.%f") + "+09:00"


def format_cell(field: str, value: Any) -> str:
    if value is None or value == "":
        return ""
    if field == "uptime_us" or field in INTEGER_FIELDS:
        return str(int(round(float(value))))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = f"{float(value):.8f}".rstrip("0").rstrip(".")
        return "0" if text in {"", "-0"} else text
    return str(value)


def csv_headers() -> list[str]:
    headers = [
        "time",
        "uptime_us",
        "boot_id",
        "time_left",
        "time_right",
    ]
    for meta in META_FIELDS:
        for side in SIDES:
            headers.append(f"{side}_{meta}")
    for field in EXPORT_FIELDS:
        for side in SIDES:
            headers.append(f"{side}_{field}")
    return headers


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    return None


def join_samples(samples: Iterable[dict]) -> list[dict]:
    """같은 uptime_us의 왼쪽·오른쪽을 한 줄로 합친다."""
    ordered = sorted(
        (sample for sample in samples if sample.get("rail_side") in SIDES),
        key=lambda sample: sample.get("time") or datetime.min.replace(tzinfo=timezone.utc),
    )
    joined: dict[tuple, dict] = {}
    keys: list[tuple] = []
    for sample in ordered:
        side = str(sample["rail_side"])
        uptime = _as_int(sample.get("uptime_us"))
        if uptime is None:
            moment = sample.get("time")
            stamp = moment.isoformat() if isinstance(moment, datetime) else str(moment)
            key = ("missing", side, stamp)
        else:
            key = ("uptime", uptime)
        if key not in joined:
            joined[key] = {"uptime_us": uptime}
            keys.append(key)
        row = joined[key]
        moment = sample.get("time")
        if isinstance(moment, datetime):
            row[f"time_{side}"] = moment
        for meta in META_FIELDS:
            if sample.get(meta) is not None:
                row[f"{side}_{meta}"] = sample[meta]
        for field in EXPORT_FIELDS:
            if sample.get(field) is not None:
                row[f"{side}_{field}"] = sample[field]
    rows = [joined[key] for key in keys]
    rows.sort(
        key=lambda row: (
            row["uptime_us"] is None,
            row["uptime_us"] if row["uptime_us"] is not None else 0,
        )
    )
    if len(rows) > MAX_ROWS:
        raise ExportTooLarge(
            f"이 전원 구간의 샘플이 {MAX_ROWS}줄을 넘습니다. "
            "보드를 끄고 다시 켜서 주행을 나눈 뒤 받으세요."
        )
    return rows


def _preferred_time(row: dict) -> datetime | None:
    left = row.get("time_left")
    if isinstance(left, datetime):
        return left
    right = row.get("time_right")
    if isinstance(right, datetime):
        return right
    return None


def csv_filename(boot_id: str, first_time: datetime | None, label: str | None = None) -> str:
    """목록과 같은 실험 이름 뒤에 서울 시각과 전원 번호를 붙인다."""
    boot_id = validate_boot_id(boot_id)
    stamp = ""
    if first_time is not None:
        local = first_time.astimezone(SEOUL) if first_time.tzinfo else first_time.replace(tzinfo=timezone.utc).astimezone(SEOUL)
        stamp = local.strftime("%Y%m%d-%H%M%S")
    if label and stamp:
        return f"{label}-{stamp}-{boot_id}.csv"
    if label:
        return f"{label}-{boot_id}.csv"
    if stamp:
        return f"run-{stamp}-{boot_id}.csv"
    return f"run-{boot_id}.csv"


def content_disposition(filename: str, boot_id: str) -> str:
    """한글 파일 이름을 브라우저가 유지하도록 UTF-8 이름을 같이 보낸다."""
    quoted = quote(filename, safe="")
    return f"attachment; filename=\"run-{boot_id}.csv\"; filename*=UTF-8''{quoted}"


def render_csv(rows: list[dict], boot_id: str, label: str | None = None) -> tuple[str, str]:
    """CSV 본문과 파일 이름을 만든다. 이름은 실험 이름, 첫 샘플 시각, 전원 번호다."""
    boot_id = validate_boot_id(boot_id)
    headers = csv_headers()
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    first_time: datetime | None = None
    for row in rows:
        moment = _preferred_time(row)
        if first_time is None and moment is not None:
            first_time = moment
        values: list[str] = [
            format_seoul(moment) if moment is not None else "",
            format_cell("uptime_us", row.get("uptime_us")),
            boot_id,
            format_seoul(row["time_left"]) if isinstance(row.get("time_left"), datetime) else "",
            format_seoul(row["time_right"]) if isinstance(row.get("time_right"), datetime) else "",
        ]
        for meta in META_FIELDS:
            for side in SIDES:
                cell = row.get(f"{side}_{meta}")
                values.append("" if cell is None else str(cell))
        for field in EXPORT_FIELDS:
            for side in SIDES:
                values.append(format_cell(field, row.get(f"{side}_{field}")))
        writer.writerow(values)

    return buffer.getvalue(), csv_filename(boot_id, first_time, label)


def experiment_labels(starts: Iterable[tuple[str, datetime]]) -> list[dict]:
    """같은 서울 날짜 안에서 시작 시각 순으로 N차 실험 이름을 붙인다."""
    grouped: dict[tuple[int, int], list[tuple[datetime, str]]] = {}
    for boot_id, started in starts:
        try:
            safe_id = validate_boot_id(str(boot_id))
        except ValueError:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        local = started.astimezone(SEOUL)
        grouped.setdefault((local.month, local.day), []).append((local, safe_id))

    runs: list[dict] = []
    for bucket in grouped.values():
        bucket.sort(key=lambda item: item[0])
        for index, (local, boot_id) in enumerate(bucket, start=1):
            runs.append(
                {
                    "boot_id": boot_id,
                    "label": f"{local.month}월 {local.day}일 {index}차 실험",
                    "started_at": format_seoul(local),
                }
            )
    runs.sort(key=lambda item: item["started_at"], reverse=True)
    return runs


def render_runs_page(runs: list[dict], message: str | None = None) -> str:
    """다운로드 목록 페이지. 실시간 대시보드와 같은 어두운 화면이다."""
    if message:
        body = f'<p class="message">{html.escape(message)}</p>'
    elif not runs:
        body = "<p class=\"message\">최근 90일에 저장된 주행이 없습니다.</p>"
    else:
        items = []
        for run in runs:
            boot_id = html.escape(run["boot_id"])
            label = html.escape(run["label"])
            started = html.escape(run["started_at"])
            items.append(
                "<li>"
                f'<a href="/runs/{boot_id}.csv">{label}</a>'
                f'<span class="when">{started}</span>'
                "</li>"
            )
        body = "<ul>" + "".join(items) + "</ul>"
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>주행 CSV</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      background: #0b1220;
      color: #e8eef8;
      font-family: "Pretendard", "Noto Sans KR", system-ui, sans-serif;
    }}
    main {{
      max-width: 760px;
      margin: 0 auto;
      padding: 32px 20px 64px;
    }}
    a {{ color: #5eead4; }}
    h1 {{ font-size: 28px; margin: 0 0 8px; }}
    .lead {{ color: #8b9bb4; line-height: 1.55; word-break: keep-all; }}
    .nav {{ margin: 20px 0 28px; display: flex; gap: 16px; }}
    ul {{ list-style: none; padding: 0; margin: 0; }}
    li {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 8px 16px;
      padding: 14px 0;
      border-bottom: 1px solid #243044;
    }}
    .when {{ color: #8b9bb4; font-variant-numeric: tabular-nums; }}
    .message {{ color: #fbbf24; }}
  </style>
</head>
<body>
  <main>
    <h1>주행 CSV</h1>
    <p class="lead">보드를 켜고 끄기까지가 파일 하나입니다. 간격, 위치, 가속도, 자이로, 칩 온도, 판정값이 한 표에 들어 있습니다. 시간 열은 마이크로초까지이고, 왼쪽과 오른쪽은 같은 uptime_us 줄입니다. 최근 90일입니다.</p>
    <p class="nav"><a href="/dashboard">실시간 화면</a><a href="/grafana/" target="_blank" rel="noopener noreferrer">그래프</a></p>
    {body}
  </main>
</body>
</html>
"""


def _records_from_tables(tables: Iterable[Any]) -> list[dict]:
    """Flux 원본 행을 샘플 딕셔너리로 모은다. 한 시각·한쪽의 필드를 한 덩어리로 둔다."""
    grouped: dict[tuple, dict] = {}
    order: list[tuple] = []
    for table in tables:
        for record in table.records:
            values = record.values
            side = values.get("rail_side")
            moment = record.get_time()
            field = record.get_field()
            if side not in SIDES or moment is None or not field:
                continue
            key = (side, moment)
            if key not in grouped:
                grouped[key] = {
                    "time": moment,
                    "rail_side": side,
                    "boot_id": values.get("boot_id"),
                    "device_id": values.get("device_id"),
                    "firmware_version": values.get("firmware_version"),
                    "source": values.get("source"),
                }
                order.append(key)
            if field in EXPORT_FIELDS or field == "uptime_us":
                grouped[key][field] = record.get_value()
    return [grouped[key] for key in order]


def _starts_from_tables(tables: Iterable[Any]) -> list[tuple[str, datetime]]:
    found: list[tuple[str, datetime]] = []
    for table in tables:
        for record in table.records:
            boot_id = record.values.get("boot_id")
            moment = record.get_time()
            if boot_id and isinstance(moment, datetime):
                found.append((str(boot_id), moment))
    return found


async def _query(url: str, token: str, org: str, flux: str, params: dict) -> Any:
    async with InfluxDBClientAsync(url=url, token=token, org=org, timeout=120_000) as client:
        return await client.query_api().query(flux, org=org, params=params)


async def fetch_run_samples(
    *,
    url: str,
    token: str,
    org: str,
    bucket: str,
    boot_id: str,
) -> list[dict]:
    safe_id = validate_boot_id(boot_id)
    safe_bucket = validate_bucket(bucket)
    tables = await _query(
        url,
        token,
        org,
        SAMPLE_FLUX,
        {"bucket": safe_bucket, "boot_id": safe_id},
    )
    return _records_from_tables(tables)


async def fetch_run_starts(
    *,
    url: str,
    token: str,
    org: str,
    bucket: str,
) -> list[tuple[str, datetime]]:
    tables = await _query(
        url,
        token,
        org,
        INDEX_FLUX,
        {"bucket": validate_bucket(bucket)},
    )
    return _starts_from_tables(tables)


def build_download(
    samples: Iterable[dict],
    boot_id: str,
    label: str | None = None,
) -> tuple[str, str]:
    return render_csv(join_samples(samples), boot_id, label)


_BUCKET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_bucket(bucket: str) -> str:
    if not isinstance(bucket, str) or not _BUCKET_PATTERN.fullmatch(bucket):
        raise ValueError("bucket")
    return bucket
