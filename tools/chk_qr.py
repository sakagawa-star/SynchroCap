import argparse
import csv
import math
import re
import shutil
from pathlib import Path

import cv2
import numpy as np

PAYLOAD_RE = re.compile(r"(?P<t>\d+\.\d+),f=(?P<f>\d+)")


def parse_args():
    parser = argparse.ArgumentParser(description="Decode QR payloads from extracted PNG frames.")
    parser.add_argument(
        "--frames-dir",
        required=True,
        help="Directory containing sequential PNG frames.",
    )
    parser.add_argument(
        "--out-csv",
        default="decoded_frames.csv",
        help="Path to output CSV (default: decoded_frames.csv).",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=1280,
        help="Resize long side to at most this value before decode (default: 1280).",
    )
    parser.add_argument(
        "--save-fail",
        action="store_true",
        help="If set, copy decode-failed frames to fail directory.",
    )
    parser.add_argument(
        "--fail-dir",
        default="fail_frames",
        help="Directory to store decode-failed frames (default: fail_frames).",
    )
    parser.add_argument(
        "--roi-upscale",
        type=float,
        default=3.0,
        help="Upscale factor applied to ROI before decoding (default: 3.0).",
    )
    parser.add_argument(
        "--roi-margin",
        type=float,
        default=0.2,
        help="Fractional margin added around detected ROI (default: 0.2).",
    )
    parser.add_argument(
        "--lost-reset",
        type=int,
        default=30,
        help="Consecutive decode failures before ROI is reset (default: 30).",
    )
    return parser.parse_args()


def prepare_image(img: np.ndarray, max_size: int) -> tuple[np.ndarray, float]:
    """Copy, resize (if needed) and convert BGR image to grayscale."""
    img = img.copy()  # avoid backend instability
    h, w = img.shape[:2]
    long_side = max(h, w)
    scale = 1.0
    if long_side > max_size:
        scale = max_size / float(long_side)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return gray, scale


def clamp_roi(x0: float, y0: float, x1: float, y1: float, width: int, height: int) -> tuple[int, int, int, int]:
    """Clamp ROI to image bounds and ensure non-zero area (x1, y1 are exclusive)."""
    x0_i = max(0, int(math.floor(x0)))
    y0_i = max(0, int(math.floor(y0)))
    x1_i = min(width, int(math.ceil(x1)))
    y1_i = min(height, int(math.ceil(y1)))
    if x1_i <= x0_i:
        x1_i = min(width, x0_i + 1)
    if y1_i <= y0_i:
        y1_i = min(height, y0_i + 1)
    return x0_i, y0_i, x1_i, y1_i


def expand_roi(x0: float, y0: float, x1: float, y1: float, margin: float, width: int, height: int) -> tuple[int, int, int, int]:
    """Expand ROI by margin (fractional) and clamp to image bounds."""
    w = max(1.0, x1 - x0)
    h = max(1.0, y1 - y0)
    x0 -= w * margin
    y0 -= h * margin
    x1 += w * margin
    y1 += h * margin
    return clamp_roi(x0, y0, x1, y1, width, height)


def bbox_from_points(points: np.ndarray | None) -> tuple[float, float, float, float] | None:
    if points is None:
        return None
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    x_min = float(np.min(pts[:, 0]))
    y_min = float(np.min(pts[:, 1]))
    x_max = float(np.max(pts[:, 0]))
    y_max = float(np.max(pts[:, 1]))
    return x_min, y_min, x_max, y_max


def decode_with_detector(detector: cv2.QRCodeDetector, img: np.ndarray):
    data, points, _ = detector.detectAndDecode(img)
    if not data:
        return "", None, None, False, points
    payload = data.strip()
    m = PAYLOAD_RE.match(payload)
    if m:
        unix_t = float(m.group("t"))
        payload_frame = int(m.group("f"))
        return payload, unix_t, payload_frame, True, points
    return payload, None, None, True, points


def preprocess_roi_for_retry(roi_gray: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    eq = clahe.apply(roi_gray)
    blurred = cv2.GaussianBlur(eq, (3, 3), 0)
    thresh = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11,
        2,
    )
    return thresh


def decode_roi(detector: cv2.QRCodeDetector, roi_gray: np.ndarray, roi_upscale: float):
    """Decode QR inside ROI with optional upscale and a secondary retry."""
    upscale = max(1.0, float(roi_upscale))

    def _attempt(img: np.ndarray):
        return decode_with_detector(detector, img)

    roi_proc = roi_gray
    if upscale > 1.0:
        roi_proc = cv2.resize(roi_gray, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_NEAREST)
    payload, unix_t, payload_frame, ok, points = _attempt(roi_proc)
    if not ok:
        retry = preprocess_roi_for_retry(roi_gray)
        retry_proc = retry
        if upscale > 1.0:
            retry_proc = cv2.resize(retry, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_NEAREST)
        payload, unix_t, payload_frame, ok, points = _attempt(retry_proc)
    if not ok:
        return "", None, None, False, None
    if points is not None:
        pts = np.asarray(points, dtype=float).reshape(-1, 2) / upscale
        points = pts.reshape(1, -1, 2)
    return payload, unix_t, payload_frame, True, points


def points_to_full_roi(points: np.ndarray | None, offset_x: int, offset_y: int, scale: float, full_w: int, full_h: int):
    if points is None:
        return None
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    pts[:, 0] = (pts[:, 0] + float(offset_x)) / max(scale, 1e-8)
    pts[:, 1] = (pts[:, 1] + float(offset_y)) / max(scale, 1e-8)
    bbox = bbox_from_points(pts)
    if bbox is None:
        return None
    return clamp_roi(bbox[0], bbox[1], bbox[2], bbox[3], full_w, full_h)


def decode_using_last_roi(
    detector: cv2.QRCodeDetector,
    gray: np.ndarray,
    last_roi: tuple[int, int, int, int],
    scale: float,
    full_w: int,
    full_h: int,
    roi_margin: float,
    roi_upscale: float,
):
    expanded_full = expand_roi(
        last_roi[0],
        last_roi[1],
        last_roi[2],
        last_roi[3],
        roi_margin,
        full_w,
        full_h,
    )
    x0f, y0f, x1f, y1f = expanded_full
    x0s, y0s, x1s, y1s = clamp_roi(
        x0f * scale,
        y0f * scale,
        x1f * scale,
        y1f * scale,
        gray.shape[1],
        gray.shape[0],
    )
    roi_gray = gray[y0s:y1s, x0s:x1s]
    if roi_gray.size == 0:
        return "", None, None, False, None
    payload, unix_t, payload_frame, ok, points = decode_roi(detector, roi_gray, roi_upscale)
    if not ok:
        return "", None, None, False, None
    new_roi = points_to_full_roi(points, x0s, y0s, scale, full_w, full_h)
    return payload, unix_t, payload_frame, True, new_roi


def decode_full_frame(
    detector: cv2.QRCodeDetector,
    gray: np.ndarray,
    scale: float,
    full_w: int,
    full_h: int,
    roi_margin: float,
    roi_upscale: float,
):
    found, points = detector.detect(gray)
    if found and points is not None:
        bbox = bbox_from_points(points)
        if bbox is not None:
            x0, y0, x1, y1 = bbox
            x0e, y0e, x1e, y1e = expand_roi(x0, y0, x1, y1, roi_margin, gray.shape[1], gray.shape[0])
            roi_gray = gray[y0e:y1e, x0e:x1e]
            if roi_gray.size > 0:
                payload, unix_t, payload_frame, ok, roi_points = decode_roi(detector, roi_gray, roi_upscale)
                if ok:
                    new_roi = points_to_full_roi(roi_points, x0e, y0e, scale, full_w, full_h)
                    return payload, unix_t, payload_frame, True, new_roi
    # Final fallback: try full frame decode without ROI expansion
    payload, unix_t, payload_frame, ok, points = decode_roi(detector, gray, roi_upscale=1.0)
    if ok:
        new_roi = points_to_full_roi(points, 0, 0, scale, full_w, full_h)
        return payload, unix_t, payload_frame, True, new_roi
    return "", None, None, False, None


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
    last_roi = None
    lost_counter = 0

    for idx, frame_path in enumerate(png_paths):
        img = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        if img is None:
            raw_payload, unix_t, payload_frame, decode_ok = "", None, None, False
            new_roi = None
        else:
            full_h, full_w = img.shape[:2]
            gray, scale = prepare_image(img, args.max_size)
            raw_payload, unix_t, payload_frame, decode_ok, new_roi = "", None, None, False, None

            if last_roi is not None:
                raw_payload, unix_t, payload_frame, decode_ok, new_roi = decode_using_last_roi(
                    detector,
                    gray,
                    last_roi,
                    scale,
                    full_w,
                    full_h,
                    args.roi_margin,
                    args.roi_upscale,
                )

            if not decode_ok:
                raw_payload, unix_t, payload_frame, decode_ok, new_roi = decode_full_frame(
                    detector,
                    gray,
                    scale,
                    full_w,
                    full_h,
                    args.roi_margin,
                    args.roi_upscale,
                )

        if decode_ok:
            lost_counter = 0
            if new_roi is not None:
                last_roi = new_roi
        else:
            lost_counter += 1
            if lost_counter >= args.lost_reset:
                last_roi = None
                lost_counter = 0

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
