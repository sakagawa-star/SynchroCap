import argparse
import csv
import re
import shutil
from pathlib import Path

import cv2

PAYLOAD_RE = re.compile(r"(?P<t>\d+\.\d+),f=(?P<f>\d+)")


def parse_args():
    parser = argparse.ArgumentParser(description="Decode QR payloads from extracted PNG frames.")
    parser.add_argument("--frames-dir", required=True,
                        help="Directory containing sequential PNG frames.")
    parser.add_argument("--out-csv", default="decoded_frames.csv",
                        help="Path to output CSV (default: decoded_frames.csv).")
    parser.add_argument("--max-size", type=int, default=1280,
                        help="Resize long side to at most this value before decode (default: 1280).")
    parser.add_argument("--save-fail", action="store_true",
                        help="If set, copy decode-failed frames to fail directory.")
    parser.add_argument("--fail-dir", default="fail_frames",
                        help="Directory to store decode-failed frames (default: fail_frames).")
    return parser.parse_args()


def prepare_image(img, max_size):
    img = img.copy()  # avoid backend instability
    h, w = img.shape[:2]
    long_side = max(h, w)
    if long_side > max_size:
        scale = max_size / float(long_side)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return gray


def decode_frame(detector, img, max_size):
    if img is None:
        return "", None, None, False
    gray = prepare_image(img, max_size)
    data, _, _ = detector.detectAndDecode(gray)
    if not data:
        return "", None, None, False
    payload = data.strip()
    m = PAYLOAD_RE.match(payload)
    if m:
        unix_t = float(m.group("t"))
        payload_frame = int(m.group("f"))
        return payload, unix_t, payload_frame, True
    return payload, None, None, True


def main():
    args = parse_args()
    frames_dir = Path(args.frames_dir)
    if not frames_dir.is_dir():
        raise SystemExit(f"Frames directory not found: {frames_dir}")

    png_paths = sorted(frames_dir.glob("*.png"))
    if not png_paths:
        raise SystemExit(f"No PNG frames found in directory: {frames_dir}")

    fail_dir = Path(args.fail_dir)
    if args.save_fail:
        fail_dir.mkdir(parents=True, exist_ok=True)

    detector = cv2.QRCodeDetector()

    rows = []
    payload_frames = []

    for idx, frame_path in enumerate(png_paths):
        img = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        raw_payload, unix_t, payload_frame, decode_ok = decode_frame(detector, img, args.max_size)

        if not decode_ok and args.save_fail:
            shutil.copy2(frame_path, fail_dir / frame_path.name)

        rows.append([
            idx,
            unix_t if unix_t is not None else "",
            payload_frame if payload_frame is not None else "",
            raw_payload,
            decode_ok,
        ])

        if payload_frame is not None:
            payload_frames.append(payload_frame)

    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(["video_frame_idx", "unix_time", "payload_frame", "raw_payload", "decode_ok"])
        writer.writerows(rows)

    drop_lines = []
    if payload_frames:
        prev = payload_frames[0]
        for cur in payload_frames[1:]:
            if cur != prev + 1:
                drop_lines.append(f"{prev} -> {cur} (missing {cur - prev - 1} frames)")
            prev = cur

    drop_path = Path("drop_candidates.txt")
    with drop_path.open("w", encoding="utf-8") as fp:
        if drop_lines:
            fp.write("\n".join(drop_lines))
        else:
            fp.write("No drop candidates detected.\n")

    decode_fail_count = sum(1 for r in rows if not r[4])
    print(f"Frames processed: {len(rows)}, decode failures: {decode_fail_count}")
    print(f"CSV saved to: {out_csv}")
    if drop_lines:
        print("Drop candidates:")
        for line in drop_lines[:50]:
            print(f"  {line}")
        if len(drop_lines) > 50:
            print("  ...")
    else:
        print("No drop candidates detected.")
    if args.save_fail:
        print(f"Failed frames copied to: {fail_dir}")


if __name__ == "__main__":
    main()
