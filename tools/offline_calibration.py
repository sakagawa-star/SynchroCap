#!/usr/bin/env python3
"""Offline intrinsic calibration from saved ChArUco images.

Reuses the SynchroCap app modules (BoardDetector, CalibrationEngine,
CalibrationExporter) to run calibration without a live camera.

Usage:
    python tools/offline_calibration.py <image_dir> <serial> [options]

Example:
    python tools/offline_calibration.py \
        src/synchroCap/captures/20260318-141544/intrinsics/cam05520125 \
        05520125

    # Custom board settings
    python tools/offline_calibration.py \
        src/synchroCap/captures/20260318-141544/intrinsics/cam05520125 \
        05520125 \
        --cols 5 --rows 7 --square-mm 30.0 --marker-mm 22.0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

# Add src/synchroCap to import path
_src_dir = Path(__file__).resolve().parent.parent / "src" / "synchroCap"
sys.path.insert(0, str(_src_dir))

from board_detector import BoardDetector
from calibration_engine import CalibrationEngine
from calibration_exporter import CalibrationExporter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline intrinsic calibration from saved ChArUco images.",
    )
    parser.add_argument(
        "image_dir",
        help="Directory containing PNG images of ChArUco board.",
    )
    parser.add_argument(
        "serial",
        help="Camera serial number (used for export file naming).",
    )
    parser.add_argument("--cols", type=int, default=5, help="Board columns (default: 5)")
    parser.add_argument("--rows", type=int, default=7, help="Board rows (default: 7)")
    parser.add_argument(
        "--square-mm", type=float, default=30.0, help="Square size in mm (default: 30.0)"
    )
    parser.add_argument(
        "--marker-mm", type=float, default=22.0, help="Marker size in mm (default: 22.0)"
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory for TOML/JSON. Defaults to <image_dir>.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image_dir = Path(args.image_dir)
    if not image_dir.is_dir():
        print(f"Error: {image_dir} is not a directory", file=sys.stderr)
        return 1

    # Collect PNG images
    image_paths = sorted(image_dir.glob("*.png"))
    if not image_paths:
        print(f"Error: No PNG files found in {image_dir}", file=sys.stderr)
        return 1
    print(f"Found {len(image_paths)} PNG images in {image_dir}")

    # Detect board in each image
    detector = BoardDetector(
        board_type="charuco",
        cols=args.cols,
        rows=args.rows,
        square_mm=args.square_mm,
        marker_mm=args.marker_mm,
    )

    object_points_list = []
    image_points_list = []
    image_size = None
    skipped = []

    for path in image_paths:
        frame = cv2.imread(str(path))
        if frame is None:
            skipped.append((path.name, "failed to read"))
            continue
        if image_size is None:
            h, w = frame.shape[:2]
            image_size = (w, h)

        result = detector.detect(frame)
        if not result.success:
            skipped.append((path.name, result.failure_reason))
            continue

        object_points_list.append(result.object_points)
        image_points_list.append(result.image_points)
        print(f"  {path.name}: {result.num_corners} corners detected")

    print(f"\nDetection: {len(object_points_list)} / {len(image_paths)} images OK")
    if skipped:
        print(f"Skipped {len(skipped)} images:")
        for name, reason in skipped:
            print(f"  {name}: {reason}")

    if len(object_points_list) < CalibrationEngine.MIN_CAPTURES:
        print(
            f"\nError: Need at least {CalibrationEngine.MIN_CAPTURES} "
            f"valid detections, got {len(object_points_list)}",
            file=sys.stderr,
        )
        return 1

    # Calibrate
    engine = CalibrationEngine()
    calib_result = engine.calibrate(object_points_list, image_points_list, image_size)

    # Display results
    print(f"\n{'=' * 50}")
    print(f"RMS reprojection error: {calib_result.rms_error:.4f} px")
    print(f"\nCamera matrix:")
    K = calib_result.camera_matrix
    print(f"  fx={K[0,0]:.2f}  fy={K[1,1]:.2f}  cx={K[0,2]:.2f}  cy={K[1,2]:.2f}")
    print(f"\nDistortion coefficients ({calib_result.dist_coeffs.shape[1]} coefficients):")
    d = calib_result.dist_coeffs.flatten()
    labels = ["k1", "k2", "p1", "p2", "k3", "k4", "k5", "k6"]
    for i, (label, val) in enumerate(zip(labels, d)):
        print(f"  {label} = {val:.6f}")
    print(f"\nPer-image errors:")
    for i, err in enumerate(calib_result.per_image_errors):
        print(f"  image {i+1:03d}: {err:.4f} px")
    print(f"{'=' * 50}")

    # Export
    output_dir = Path(args.output_dir) if args.output_dir else image_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    exporter = CalibrationExporter()
    created = exporter.export(
        result=calib_result,
        serial=args.serial,
        image_size=image_size,
        num_images=len(object_points_list),
        output_dir=output_dir,
    )
    print(f"\nExported:")
    for p in created:
        print(f"  {p}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
