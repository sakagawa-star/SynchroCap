"""SynchroCap Raw file validation tool.

Provides subcommands for inspecting, validating and viewing SRAW format files
produced by the SynchroCap recording pipeline.

Usage:
    python s13_raw_tool.py dump <raw_file> [--all]
    python s13_raw_tool.py validate <session_dir>
    python s13_raw_tool.py sync-check <session_dir> [--threshold-ms 1.0]
    python s13_raw_tool.py view <raw_file> [--frame N]
"""

import argparse
import csv
import glob
import os
import re
import struct
import sys
from typing import BinaryIO, Dict, Iterator, List, NamedTuple, Optional, Tuple

# ---------------------------------------------------------------------------
# SRAW format constants (from feat-002 design.md)
# ---------------------------------------------------------------------------

SRAW_MAGIC = b'SRAW'
FRAM_MAGIC = b'FRAM'
SRAW_VERSION = 1

FILE_HEADER_FORMAT = '<4sI16sqHHHH'  # 40 bytes
FILE_HEADER_SIZE = struct.calcsize(FILE_HEADER_FORMAT)  # 40
FRAME_HEADER_FORMAT = '<4sIQq'  # 24 bytes
FRAME_HEADER_SIZE = struct.calcsize(FRAME_HEADER_FORMAT)  # 24

PIXEL_FORMAT_NAMES = {
    0: "BayerGR8",
    1: "BayerGR16",
    2: "BGR8",
}

# Bytes per pixel for payload_size validation
PIXEL_FORMAT_BPP = {
    0: 1,   # BayerGR8: 1 byte/pixel
    1: 2,   # BayerGR16: 2 bytes/pixel
    2: 3,   # BGR8: 3 bytes/pixel
}

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_ERROR = 2

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class FileHeader(NamedTuple):
    magic: bytes
    version: int
    camera_serial: str
    recording_start_ns: int
    width: int
    height: int
    pixel_format: int
    reserved: int


class FrameHeader(NamedTuple):
    magic: bytes
    payload_size: int
    frame_index: int
    timestamp_ns: int


class FrameInfo(NamedTuple):
    frame_index: int
    timestamp_ns: int
    payload_size: int
    file_offset: int


class SessionFiles(NamedTuple):
    serial: str
    raw_files: List[str]
    csv_path: Optional[str]


# ---------------------------------------------------------------------------
# Common parsers
# ---------------------------------------------------------------------------


def read_file_header(f: BinaryIO) -> FileHeader:
    data = f.read(FILE_HEADER_SIZE)
    if len(data) < FILE_HEADER_SIZE:
        raise ValueError(f"File too small for FileHeader (got {len(data)} bytes, need {FILE_HEADER_SIZE})")
    magic, version, serial_bytes, start_ns, w, h, pf, reserved = struct.unpack(
        FILE_HEADER_FORMAT, data
    )
    serial = serial_bytes.split(b'\x00')[0].decode('ascii', errors='replace')
    return FileHeader(magic, version, serial, start_ns, w, h, pf, reserved)


def read_frame_header(f: BinaryIO) -> Optional[FrameHeader]:
    data = f.read(FRAME_HEADER_SIZE)
    if len(data) < FRAME_HEADER_SIZE:
        return None
    magic, payload_size, frame_index, timestamp_ns = struct.unpack(
        FRAME_HEADER_FORMAT, data
    )
    return FrameHeader(magic, payload_size, frame_index, timestamp_ns)


def iter_frame_infos(f: BinaryIO) -> Iterator[FrameInfo]:
    """Iterate FrameInfos from current position (after FileHeader). Skips payloads."""
    while True:
        offset = f.tell()
        fh = read_frame_header(f)
        if fh is None:
            break
        yield FrameInfo(fh.frame_index, fh.timestamp_ns, fh.payload_size, offset)
        f.seek(fh.payload_size, os.SEEK_CUR)


# ---------------------------------------------------------------------------
# Session file discovery
# ---------------------------------------------------------------------------

_RAW_PATTERN = re.compile(r'^cam(\d+)_(\d+)\.raw$')
_CSV_PATTERN = re.compile(r'^cam(\d+)\.csv$')


def discover_session_files(session_dir: str) -> Dict[str, SessionFiles]:
    """Discover Raw/CSV files in a session directory, grouped by serial."""
    serials_raw: Dict[str, List[Tuple[int, str]]] = {}
    serials_csv: Dict[str, str] = {}

    for entry in os.listdir(session_dir):
        m = _RAW_PATTERN.match(entry)
        if m:
            serial = m.group(1)
            start_frame = int(m.group(2))
            serials_raw.setdefault(serial, []).append((start_frame, os.path.join(session_dir, entry)))
            continue
        m = _CSV_PATTERN.match(entry)
        if m:
            serial = m.group(1)
            serials_csv[serial] = os.path.join(session_dir, entry)

    all_serials = sorted(set(list(serials_raw.keys()) + list(serials_csv.keys())))
    result: Dict[str, SessionFiles] = {}
    for serial in all_serials:
        raw_list = serials_raw.get(serial, [])
        raw_list.sort(key=lambda x: x[0])
        result[serial] = SessionFiles(
            serial=serial,
            raw_files=[path for _, path in raw_list],
            csv_path=serials_csv.get(serial),
        )
    return result


# ---------------------------------------------------------------------------
# CSV reader
# ---------------------------------------------------------------------------


def read_csv_timestamps(csv_path: str) -> List[Tuple[str, int]]:
    """Read (frame_number, device_timestamp_ns) from CSV."""
    rows: List[Tuple[str, int]] = []
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            return rows
        for row in reader:
            if len(row) < 2:
                continue
            rows.append((row[0], int(row[1])))
    return rows


# ---------------------------------------------------------------------------
# Subcommand: dump
# ---------------------------------------------------------------------------

def _format_pixel_format(pf: int) -> str:
    name = PIXEL_FORMAT_NAMES.get(pf, "Unknown")
    return f"{name} ({pf})"


def cmd_dump(args: argparse.Namespace) -> int:
    raw_file = args.raw_file
    show_all = args.all

    if not os.path.isfile(raw_file):
        print(f"Error: file not found: {raw_file}", file=sys.stderr)
        return EXIT_ERROR

    with open(raw_file, "rb") as f:
        try:
            fh = read_file_header(f)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return EXIT_ERROR

        print("=== FileHeader ===")
        print(f"  magic:              {fh.magic.decode('ascii', errors='replace')}")
        print(f"  version:            {fh.version}")
        print(f"  camera_serial:      {fh.camera_serial}")
        print(f"  recording_start_ns: {fh.recording_start_ns}")
        print(f"  width:              {fh.width}")
        print(f"  height:             {fh.height}")
        print(f"  pixel_format:       {_format_pixel_format(fh.pixel_format)}")
        print()

        frames = list(iter_frame_infos(f))
        total = len(frames)

        print(f"=== Frames ({total} total) ===")

        if show_all or total <= 20:
            for i, fi in enumerate(frames):
                print(f"  [{i:>4}] frame_index={fi.frame_index:<8}  "
                      f"timestamp_ns={fi.timestamp_ns}  payload={fi.payload_size}")
        else:
            head = 10
            tail = 10
            for i in range(head):
                fi = frames[i]
                print(f"  [{i:>4}] frame_index={fi.frame_index:<8}  "
                      f"timestamp_ns={fi.timestamp_ns}  payload={fi.payload_size}")
            omitted = total - head - tail
            print(f"  ... ({omitted} frames omitted) ...")
            for i in range(total - tail, total):
                fi = frames[i]
                print(f"  [{i:>4}] frame_index={fi.frame_index:<8}  "
                      f"timestamp_ns={fi.timestamp_ns}  payload={fi.payload_size}")

    return EXIT_OK


# ---------------------------------------------------------------------------
# Subcommand: validate
# ---------------------------------------------------------------------------


def _validate_camera(serial: str, sf: SessionFiles) -> Tuple[int, int]:
    """Validate one camera's files. Returns (pass_count, fail_count)."""
    passes = 0
    fails = 0

    def _pass(check_id: str, msg: str) -> None:
        nonlocal passes
        print(f"  [PASS] {check_id}: {msg}")
        passes += 1

    def _fail(check_id: str, msg: str) -> None:
        nonlocal fails
        print(f"  [FAIL] {check_id}: {msg}")
        fails += 1

    if not sf.raw_files:
        print(f"  [SKIP] No raw files found")
        return passes, fails

    # Collect all frame infos across split files
    all_frames: List[FrameInfo] = []
    file_headers: List[FileHeader] = []
    file_frame_counts: List[Tuple[str, int]] = []

    for raw_path in sf.raw_files:
        basename = os.path.basename(raw_path)
        try:
            with open(raw_path, "rb") as f:
                fh = read_file_header(f)
                file_headers.append(fh)
                file_frames = list(iter_frame_infos(f))
                file_frame_counts.append((basename, len(file_frames)))
                all_frames.extend(file_frames)
        except (ValueError, OSError) as e:
            print(f"  [ERROR] Failed to read {basename}: {e}")
            fails += 1
            continue

    if not file_headers:
        return passes, fails

    # Print file summary
    raw_desc = ", ".join(f"{name} ({count} frames)" for name, count in file_frame_counts)
    print(f"  Raw files: {raw_desc}")
    if sf.csv_path:
        csv_rows = read_csv_timestamps(sf.csv_path)
        print(f"  CSV file:  {os.path.basename(sf.csv_path)} ({len(csv_rows)} rows)")
    else:
        csv_rows = None
        print(f"  CSV file:  (not found)")

    # V1: FileHeader magic
    all_magic_ok = all(fh.magic == SRAW_MAGIC for fh in file_headers)
    if all_magic_ok:
        _pass("V1", "FileHeader magic")
    else:
        bad = [os.path.basename(sf.raw_files[i]) for i, fh in enumerate(file_headers) if fh.magic != SRAW_MAGIC]
        _fail("V1", f"FileHeader magic mismatch in: {', '.join(bad)}")

    # V2: FileHeader version
    all_ver_ok = all(fh.version == SRAW_VERSION for fh in file_headers)
    if all_ver_ok:
        _pass("V2", "FileHeader version")
    else:
        bad = [os.path.basename(sf.raw_files[i]) for i, fh in enumerate(file_headers) if fh.version != SRAW_VERSION]
        _fail("V2", f"FileHeader version mismatch in: {', '.join(bad)}")

    # V3: FrameHeader magic
    bad_magic_frames = [fi for fi in all_frames if fi.frame_index is not None
                        and False]  # Need actual magic check — re-read from FrameInfo
    # Note: iter_frame_infos doesn't store magic. We need to check during iteration.
    # Re-scan for magic check
    magic_errors: List[str] = []
    for raw_path in sf.raw_files:
        try:
            with open(raw_path, "rb") as f:
                f.seek(FILE_HEADER_SIZE)
                while True:
                    fh = read_frame_header(f)
                    if fh is None:
                        break
                    if fh.magic != FRAM_MAGIC:
                        magic_errors.append(
                            f"frame_index={fh.frame_index} in {os.path.basename(raw_path)}"
                        )
                    f.seek(fh.payload_size, os.SEEK_CUR)
        except OSError:
            pass

    if not magic_errors:
        _pass("V3", f"FrameHeader magic ({len(all_frames)} frames checked)")
    else:
        _fail("V3", f"FrameHeader magic mismatch: {magic_errors[0]}" +
              (f" (+{len(magic_errors)-1} more)" if len(magic_errors) > 1 else ""))

    # V4: payload_size == width * height * bpp
    ref_header = file_headers[0]
    bpp = PIXEL_FORMAT_BPP.get(ref_header.pixel_format, 1)
    expected_payload = ref_header.width * ref_header.height * bpp
    bad_payload = [fi for fi in all_frames if fi.payload_size != expected_payload]
    if not bad_payload:
        _pass("V4", f"payload_size == {expected_payload} ({ref_header.width}*{ref_header.height}*{bpp})")
    else:
        first = bad_payload[0]
        _fail("V4", f"payload_size mismatch at frame_index={first.frame_index}: "
              f"expected {expected_payload}, got {first.payload_size}" +
              (f" (+{len(bad_payload)-1} more)" if len(bad_payload) > 1 else ""))

    # V5: frame_index continuity
    gap_found = False
    for i, fi in enumerate(all_frames):
        if fi.frame_index != i:
            _fail("V5", f"frame_index gap at position {i} (expected {i}, got {fi.frame_index})")
            gap_found = True
            break
    if not gap_found:
        last_idx = len(all_frames) - 1 if all_frames else -1
        _pass("V5", f"frame_index continuous (0..{last_idx})")

    # V6: timestamp_ns monotonically increasing
    ts_error = False
    for i in range(1, len(all_frames)):
        if all_frames[i].timestamp_ns <= all_frames[i - 1].timestamp_ns:
            _fail("V6", f"timestamp_ns not increasing at frame_index={all_frames[i].frame_index}: "
                  f"{all_frames[i].timestamp_ns} <= {all_frames[i-1].timestamp_ns}")
            ts_error = True
            break
    if not ts_error:
        _pass("V6", "timestamp_ns monotonically increasing")

    # V7, V8: CSV comparison
    if csv_rows is None:
        print(f"  [SKIP] V7: CSV file not found")
        print(f"  [SKIP] V8: CSV file not found")
    else:
        # V7: row count
        if len(csv_rows) == len(all_frames):
            _pass("V7", f"CSV rows ({len(csv_rows)}) == Raw frames ({len(all_frames)})")
        else:
            _fail("V7", f"CSV rows ({len(csv_rows)}) != Raw frames ({len(all_frames)})")

        # V8: timestamp match
        min_len = min(len(csv_rows), len(all_frames))
        ts_mismatch = None
        for i in range(min_len):
            csv_ts = csv_rows[i][1]
            raw_ts = all_frames[i].timestamp_ns
            if csv_ts != raw_ts:
                ts_mismatch = (i, csv_ts, raw_ts)
                break
        if ts_mismatch is None:
            _pass("V8", f"CSV timestamps match Raw timestamps ({min_len} checked)")
        else:
            idx, csv_ts, raw_ts = ts_mismatch
            _fail("V8", f"timestamp mismatch at frame {idx}: CSV={csv_ts} Raw={raw_ts}")

    return passes, fails


def cmd_validate(args: argparse.Namespace) -> int:
    session_dir = args.session_dir

    if not os.path.isdir(session_dir):
        print(f"Error: directory not found: {session_dir}", file=sys.stderr)
        return EXIT_ERROR

    session_map = discover_session_files(session_dir)
    if not session_map:
        print(f"Error: no raw/csv files found in: {session_dir}", file=sys.stderr)
        return EXIT_ERROR

    print(f"=== Validating session: {session_dir} ===")
    print()

    total_pass = 0
    total_fail = 0

    for serial, sf in session_map.items():
        print(f"--- cam{serial} ---")
        p, f_count = _validate_camera(serial, sf)
        total_pass += p
        total_fail += f_count
        print()

    total = total_pass + total_fail
    if total_fail == 0:
        print(f"=== Result: {total_pass}/{total} PASS ({len(session_map)} cameras) ===")
        return EXIT_OK
    else:
        print(f"=== Result: {total_pass}/{total} PASS, {total_fail} FAIL ({len(session_map)} cameras) ===")
        return EXIT_FAIL


# ---------------------------------------------------------------------------
# Subcommand: sync-check
# ---------------------------------------------------------------------------


def cmd_sync_check(args: argparse.Namespace) -> int:
    session_dir = args.session_dir
    threshold_ms = args.threshold_ms
    threshold_ns = int(threshold_ms * 1_000_000)

    if not os.path.isdir(session_dir):
        print(f"Error: directory not found: {session_dir}", file=sys.stderr)
        return EXIT_ERROR

    session_map = discover_session_files(session_dir)

    # Load CSV for each camera
    camera_data: Dict[str, Dict[str, int]] = {}  # serial -> {frame_number: timestamp_ns}
    for serial, sf in session_map.items():
        if sf.csv_path is None:
            print(f"Warning: no CSV for cam{serial}, skipping", file=sys.stderr)
            continue
        rows = read_csv_timestamps(sf.csv_path)
        ts_map: Dict[str, int] = {}
        for frame_num, ts in rows:
            ts_map[frame_num] = ts
        camera_data[serial] = ts_map

    if len(camera_data) < 2:
        print(f"Error: need at least 2 cameras for sync check, found {len(camera_data)}", file=sys.stderr)
        return EXIT_ERROR

    # Find common frame numbers
    serials = sorted(camera_data.keys())
    common_frames = set(camera_data[serials[0]].keys())
    for serial in serials[1:]:
        common_frames &= set(camera_data[serial].keys())

    # Sort frame numbers
    common_frames_sorted = sorted(common_frames, key=lambda x: int(x))

    if not common_frames_sorted:
        print("Error: no common frames across cameras", file=sys.stderr)
        return EXIT_ERROR

    print(f"=== Sync Check: {session_dir} ===")
    print()
    print(f"Cameras: {', '.join(serials)}")
    print(f"Common frames: {len(common_frames_sorted)}")
    print(f"Threshold: {threshold_ms:.3f} ms")
    print()

    # Calculate per-frame diffs
    diffs: List[int] = []  # max-min per frame in ns
    violations: List[Tuple[str, float, str, str]] = []  # (frame_num, diff_ms, max_serial, min_serial)

    for frame_num in common_frames_sorted:
        timestamps = {serial: camera_data[serial][frame_num] for serial in serials}
        ts_values = list(timestamps.values())
        ts_max = max(ts_values)
        ts_min = min(ts_values)
        diff = ts_max - ts_min
        diffs.append(diff)

        if diff > threshold_ns:
            max_serial = [s for s, t in timestamps.items() if t == ts_max][0]
            min_serial = [s for s, t in timestamps.items() if t == ts_min][0]
            diff_ms = diff / 1_000_000.0
            violations.append((frame_num, diff_ms, max_serial, min_serial))

    # Statistics
    mean_ns = sum(diffs) / len(diffs)
    max_ns = max(diffs)
    diffs_sorted = sorted(diffs)
    p99_index = min(int(len(diffs_sorted) * 0.99), len(diffs_sorted) - 1)
    p99_ns = diffs_sorted[p99_index]

    print("--- Statistics (max-min per frame) ---")
    print(f"  mean:  {mean_ns / 1_000_000:.3f} ms")
    print(f"  max:   {max_ns / 1_000_000:.3f} ms")
    print(f"  p99:   {p99_ns / 1_000_000:.3f} ms")
    print()

    MAX_VIOLATIONS_SHOWN = 10
    print(f"--- Threshold violations ({len(violations)} frames) ---")
    if not violations:
        print("  (none)")
    else:
        show_count = min(len(violations), MAX_VIOLATIONS_SHOWN)
        for i in range(show_count):
            frame_num, diff_ms, max_s, min_s = violations[i]
            print(f"  frame={frame_num}  max-min={diff_ms:.3f} ms  (max: {max_s}, min: {min_s})")
        if len(violations) > MAX_VIOLATIONS_SHOWN:
            print(f"  ... ({len(violations) - MAX_VIOLATIONS_SHOWN} more violations omitted)")
    print()

    if not violations:
        print("=== Result: PASS ===")
        return EXIT_OK
    else:
        print(f"=== Result: FAIL ({len(violations)} frames exceed threshold) ===")
        return EXIT_FAIL


# ---------------------------------------------------------------------------
# Subcommand: view
# ---------------------------------------------------------------------------


def read_frame_payload(f: BinaryIO, frame_index: int) -> Tuple[FrameHeader, bytes]:
    """Seek to frame_index (0-based position in file) and return (FrameHeader, payload)."""
    for i in range(frame_index):
        fh = read_frame_header(f)
        if fh is None:
            raise ValueError(f"Frame {frame_index} out of range (file has {i} frames)")
        f.seek(fh.payload_size, os.SEEK_CUR)
    fh = read_frame_header(f)
    if fh is None:
        raise ValueError(f"Frame {frame_index} out of range (file has {frame_index} frames)")
    payload = f.read(fh.payload_size)
    if len(payload) < fh.payload_size:
        raise ValueError(f"Unexpected EOF reading payload (got {len(payload)}, expected {fh.payload_size})")
    return fh, payload


def cmd_view(args: argparse.Namespace) -> int:
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("Error: opencv-python is required for the view command.\n"
              "  Install with: pip install opencv-python", file=sys.stderr)
        return EXIT_ERROR

    raw_file = args.raw_file
    frame_index = args.frame

    if not os.path.isfile(raw_file):
        print(f"Error: file not found: {raw_file}", file=sys.stderr)
        return EXIT_ERROR

    with open(raw_file, "rb") as f:
        try:
            file_hdr = read_file_header(f)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return EXIT_ERROR

        if file_hdr.pixel_format != 0:
            pf_name = PIXEL_FORMAT_NAMES.get(file_hdr.pixel_format, "Unknown")
            print(f"Error: unsupported pixel format: {pf_name} ({file_hdr.pixel_format}). "
                  f"Only BayerGR8 (0) is supported.", file=sys.stderr)
            return EXIT_ERROR

        try:
            frame_hdr, payload = read_frame_payload(f, frame_index)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return EXIT_ERROR

    # Decode BayerGR8 → BGR
    bayer = np.frombuffer(payload, dtype=np.uint8).reshape((file_hdr.height, file_hdr.width))
    bgr = cv2.cvtColor(bayer, cv2.COLOR_BayerGR2BGR)

    # Console output
    basename = os.path.basename(raw_file)
    print(f"=== View: {basename} ===")
    print(f"  FileHeader: {file_hdr.width}x{file_hdr.height} {PIXEL_FORMAT_NAMES[file_hdr.pixel_format]}")
    print(f"  Frame: index={frame_hdr.frame_index}, timestamp_ns={frame_hdr.timestamp_ns}")
    print(f"  Showing frame {frame_index} (press 's' to save, 'q' to quit)")

    # PNG save path
    stem = os.path.splitext(basename)[0]
    png_name = f"{stem}_frame{frame_hdr.frame_index:06d}.png"
    png_path = os.path.join(os.path.dirname(os.path.abspath(raw_file)), png_name)

    # Show
    window_name = f"SynchroCap Raw Viewer - {basename} [frame {frame_index}]"
    cv2.imshow(window_name, bgr)

    while True:
        key = cv2.waitKey(0) & 0xFF
        if key == ord('q') or key == 27:  # 'q' or ESC
            break
        elif key == ord('s'):
            try:
                cv2.imwrite(png_path, bgr)
                print(f"  Saved: {png_path}")
            except Exception as e:
                print(f"  WARNING: Failed to save PNG: {e}", file=sys.stderr)

    cv2.destroyAllWindows()
    return EXIT_OK


# ---------------------------------------------------------------------------
# Main / CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SynchroCap Raw file validation tool"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # dump
    dump_parser = subparsers.add_parser("dump", help="Dump raw file headers")
    dump_parser.add_argument("raw_file", help="Path to .raw file")
    dump_parser.add_argument("--all", action="store_true",
                             help="Show all frame headers")

    # validate
    validate_parser = subparsers.add_parser("validate",
                                             help="Validate session files")
    validate_parser.add_argument("session_dir", help="Path to session directory")

    # sync-check
    sync_parser = subparsers.add_parser("sync-check",
                                         help="Check inter-camera sync")
    sync_parser.add_argument("session_dir", help="Path to session directory")
    sync_parser.add_argument("--threshold-ms", type=float, default=1.0,
                             help="Sync threshold in ms (default: 1.0)")

    # view
    view_parser = subparsers.add_parser("view", help="View a raw frame")
    view_parser.add_argument("raw_file", help="Path to .raw file")
    view_parser.add_argument("--frame", type=int, default=0,
                             help="Frame index to view (default: 0)")

    args = parser.parse_args()

    if args.command == "dump":
        return cmd_dump(args)
    elif args.command == "validate":
        return cmd_validate(args)
    elif args.command == "sync-check":
        return cmd_sync_check(args)
    elif args.command == "view":
        return cmd_view(args)
    else:
        parser.print_help()
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
