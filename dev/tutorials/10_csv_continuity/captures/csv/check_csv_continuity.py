#!/usr/bin/env python3
# Usage:
#   python3 check_csv_continuity.py -f 30
#   python3 check_csv_continuity.py -f 30 --files cam1.csv cam2.csv cam3.csv cam4.csv

import argparse
import csv
import os
import sys


DEFAULT_FILES = ["cam1.csv", "cam2.csv", "cam3.csv", "cam4.csv"]
TOLERANCE_MS = 5.0


class CsvReadError(Exception):
    pass


def read_csv_rows(path):
    if not os.path.exists(path):
        raise CsvReadError(f"file not found: {path}")

    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise CsvReadError(f"missing header: {path}")
        if "frame_number" not in reader.fieldnames or "device_timestamp_ns" not in reader.fieldnames:
            raise CsvReadError(f"missing required columns in header: {path}")

        for row_idx, row in enumerate(reader, start=2):
            frame_raw = row.get("frame_number")
            ts_raw = row.get("device_timestamp_ns")
            if frame_raw is None or ts_raw is None:
                raise CsvReadError(f"missing required columns at line {row_idx} in {path}")
            try:
                int(frame_raw)
                ts = int(ts_raw)
            except Exception as exc:
                raise CsvReadError(f"parse error at line {row_idx} in {path}: {exc}")

            rows.append((row_idx, frame_raw, ts))

    return rows


def detect_drop_intervals(rows, expected_dt_ms):
    issues = []
    lower = expected_dt_ms - TOLERANCE_MS
    upper = expected_dt_ms + TOLERANCE_MS

    for i in range(1, len(rows)):
        prev_line, prev_frame, prev_ts = rows[i - 1]
        cur_line, cur_frame, cur_ts = rows[i]
        dt_ms = (cur_ts - prev_ts) / 1e6
        if dt_ms < lower or dt_ms > upper:
            diff = dt_ms - expected_dt_ms
            issues.append(
                {
                    "prev_line": prev_line,
                    "cur_line": cur_line,
                    "prev_frame": prev_frame,
                    "cur_frame": cur_frame,
                    "prev_ts": prev_ts,
                    "cur_ts": cur_ts,
                    "dt_ms": dt_ms,
                    "diff_ms": diff,
                }
            )

    return issues


def format_issue(issue):
    return (
        f"  - lines {issue['prev_line']}->{issue['cur_line']} "
        f"(frames {issue['prev_frame']}->{issue['cur_frame']}): "
        f"ts {issue['prev_ts']}->{issue['cur_ts']} "
        f"dt_ms={issue['dt_ms']:.3f} diff={issue['diff_ms']:+.3f} ms"
    )


def main():
    parser = argparse.ArgumentParser(description="Detect dropped/abnormal frame intervals in camera CSVs.")
    parser.add_argument(
        "-f",
        "--fps",
        type=float,
        required=True,
        help="Expected FPS (e.g., 30)",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        default=DEFAULT_FILES,
        help="CSV files to read (default: cam1.csv cam2.csv cam3.csv cam4.csv)",
    )
    args = parser.parse_args()

    if args.fps <= 0:
        print("error: fps must be > 0")
        return 2

    expected_dt_ms = 1000.0 / args.fps
    had_drops = False

    for path in args.files:
        name = os.path.basename(path)
        try:
            rows = read_csv_rows(path)
        except CsvReadError as exc:
            print(f"error: {exc}")
            return 2

        print(f"{name}:")
        print(f"  - fps={args.fps} expected_dt_ms={expected_dt_ms:.3f} (±{TOLERANCE_MS:.1f} ms)")

        issues = detect_drop_intervals(rows, expected_dt_ms)
        if issues:
            had_drops = True
            print("  - drops:")
            for issue in issues:
                print(format_issue(issue))
            print(f"  - total_drops={len(issues)}")
        else:
            print("  - フレーム落ちなし")
            print("  - total_drops=0")

        print("")

    return 1 if had_drops else 0


if __name__ == "__main__":
    sys.exit(main())
