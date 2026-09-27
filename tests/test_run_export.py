import csv
import unittest
from datetime import datetime, timezone
from pathlib import Path

import run_export
from run_export import (
    SAMPLE_FLUX,
    ExportTooLarge,
    build_download,
    content_disposition,
    csv_filename,
    experiment_labels,
    format_seoul,
    join_samples,
    render_runs_page,
    validate_boot_id,
)


def sample(side: str, uptime_us: int, moment: datetime, **fields) -> dict:
    row = {
        "time": moment,
        "rail_side": side,
        "uptime_us": uptime_us,
        "device_id": f"rail-{side}-01",
        "firmware_version": "0.6.2-draft",
        "source": "mqtt",
        "position_mm": 10.0,
        "sensor_distance_mm": 4.2,
        "mpu_accel_z": 9.8,
        "mpu_gyro_y": 0.02,
        "mpu_temp_c": 28.5,
        "adc_raw": 1000,
        "sample_seq": 7,
    }
    row.update(fields)
    return row


class RunExportTests(unittest.TestCase):
    def test_one_uptime_is_one_row_with_both_sides(self) -> None:
        left_time = datetime(2026, 9, 26, 12, 8, 41, 123456, tzinfo=timezone.utc)
        right_time = datetime(2026, 9, 26, 12, 8, 41, 130000, tzinfo=timezone.utc)
        rows = join_samples(
            [
                sample("left", 12_503_400, left_time, sensor_distance_mm=9.12),
                sample("right", 12_503_400, right_time, sensor_distance_mm=8.73),
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["left_sensor_distance_mm"], 9.12)
        self.assertEqual(rows[0]["right_sensor_distance_mm"], 8.73)
        self.assertEqual(rows[0]["uptime_us"], 12_503_400)

        body, filename = build_download(
            [
                sample("left", 12_503_400, left_time, sensor_distance_mm=9.12),
                sample("right", 12_503_400, right_time, sensor_distance_mm=8.73),
            ],
            "b12ced2f",
        )
        table = list(csv.DictReader(body.splitlines()))
        self.assertEqual(len(table), 1)
        row = table[0]
        self.assertEqual(row["time"], "2026-09-26T21:08:41.123456+09:00")
        self.assertEqual(row["time_right"], "2026-09-26T21:08:41.130000+09:00")
        self.assertEqual(row["uptime_us"], "12503400")
        self.assertEqual(row["left_sensor_distance_mm"], "9.12")
        self.assertEqual(row["right_sensor_distance_mm"], "8.73")
        self.assertEqual(row["left_position_mm"], "10")
        self.assertEqual(row["left_mpu_accel_z"], "9.8")
        self.assertEqual(row["right_mpu_gyro_y"], "0.02")
        self.assertEqual(row["left_mpu_temp_c"], "28.5")
        self.assertEqual(row["left_adc_raw"], "1000")
        self.assertEqual(row["boot_id"], "b12ced2f")
        self.assertEqual(filename, "run-20260926-210841-b12ced2f.csv")
        named = csv_filename(
            "b12ced2f",
            left_time,
            "9월 26일 1차 실험",
        )
        self.assertEqual(named, "9월 26일 1차 실험-20260926-210841-b12ced2f.csv")
        header = content_disposition(named, "b12ced2f")
        self.assertIn("filename*=UTF-8''", header)
        self.assertIn("%EC%9D%BC%201%EC%B0%A8%20%EC%8B%A4%ED%97%98", header)
        self.assertNotIn("aggregateWindow", SAMPLE_FLUX)
        self.assertIn("boot_id == boot_id", SAMPLE_FLUX)

    def test_header_has_every_stored_field_for_both_sides(self) -> None:
        body, _ = build_download([], "a1b2c3d4")
        header = body.splitlines()[0].split(",")
        for field in run_export.EXPORT_FIELDS:
            self.assertIn(f"left_{field}", header)
            self.assertIn(f"right_{field}", header)
        self.assertIn("time", header)
        self.assertIn("uptime_us", header)

    def test_samples_20ms_apart_stay_separate(self) -> None:
        start = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
        later = datetime(2026, 9, 26, 12, 0, 0, 20000, tzinfo=timezone.utc)
        body, _ = build_download(
            [
                sample("left", 1_000_000, start),
                sample("right", 1_000_000, start),
                sample("left", 1_020_000, later),
                sample("right", 1_020_000, later),
            ],
            "a1b2c3d4",
        )
        table = list(csv.DictReader(body.splitlines()))
        self.assertEqual([row["uptime_us"] for row in table], ["1000000", "1020000"])
        self.assertTrue(table[1]["time"].endswith(".020000+09:00"))

    def test_same_day_runs_are_numbered_in_start_order(self) -> None:
        runs = experiment_labels(
            [
                ("bbbbbbbb", datetime(2026, 9, 26, 11, 0, tzinfo=timezone.utc)),
                ("aaaaaaaa", datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc)),
                ("cccccccc", datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)),
            ]
        )
        by_id = {run["boot_id"]: run["label"] for run in runs}
        self.assertEqual(by_id["aaaaaaaa"], "9월 26일 1차 실험")
        self.assertEqual(by_id["bbbbbbbb"], "9월 26일 2차 실험")
        self.assertEqual(by_id["cccccccc"], "9월 25일 1차 실험")
        page = render_runs_page(runs)
        self.assertIn('href="/runs/aaaaaaaa.csv"', page)
        self.assertLess(page.index("2차 실험"), page.index("9월 26일 1차 실험"))

    def test_rejects_boot_id_injection(self) -> None:
        with self.assertRaises(ValueError):
            validate_boot_id('abcd" |> drop())')

    def test_rejects_more_than_max_rows(self) -> None:
        original = run_export.MAX_ROWS
        run_export.MAX_ROWS = 1
        try:
            moment = datetime(2026, 9, 26, tzinfo=timezone.utc)
            with self.assertRaises(ExportTooLarge):
                join_samples(
                    [
                        sample("left", 1, moment),
                        sample("left", 2, moment),
                    ]
                )
        finally:
            run_export.MAX_ROWS = original

    def test_dashboard_links_to_the_csv_page(self) -> None:
        html = (
            Path(__file__).resolve().parents[1] / "frontend" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn('href="/runs"', html)
        self.assertNotIn("temp_c", html)

    def test_seoul_format_keeps_microseconds(self) -> None:
        moment = datetime(2026, 9, 26, 12, 8, 41, 1, tzinfo=timezone.utc)
        self.assertEqual(format_seoul(moment), "2026-09-26T21:08:41.000001+09:00")


if __name__ == "__main__":
    unittest.main()
