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

    # Normal (non-wide-angle) lens: 5-coefficient model
    python tools/offline_calibration.py <image_dir> <serial> --lens normal

    # Use manufacturer spec as an intrinsic guess (K not fixed)
    python tools/offline_calibration.py <image_dir> <serial> \
        --use-spec-guess --focal-mm 3.5 --pixel-pitch-mm 0.003

    # Also fix the aspect ratio fx/fy (1.0 for square pixels)
    python tools/offline_calibration.py <image_dir> <serial> \
        --use-spec-guess --focal-mm 3.5 --pixel-pitch-mm 0.003 \
        --fix-aspect-ratio
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy

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
        "--lens",
        choices=["normal", "wide"],
        default="wide",
        help="Lens type: 'normal' = 5-coefficient model (k1,k2,p1,p2,k3), "
             "'wide' = rational 8-coefficient model (default: wide)",
    )
    parser.add_argument(
        "--use-spec-guess",
        action="store_true",
        help="Build an initial camera matrix from manufacturer spec values "
             "(--focal-mm, --pixel-pitch-mm) and pass it as an intrinsic "
             "guess (CALIB_USE_INTRINSIC_GUESS). The matrix is NOT fixed; it "
             "is only the optimization starting point.",
    )
    parser.add_argument(
        "--focal-mm",
        type=float,
        default=None,
        help="Lens focal length in mm (required with --use-spec-guess). "
             "e.g. 3.5",
    )
    parser.add_argument(
        "--pixel-pitch-mm",
        type=float,
        default=None,
        help="Sensor pixel pitch in mm, assumed square (required with "
             "--use-spec-guess). e.g. 0.003",
    )
    parser.add_argument(
        "--fix-aspect-ratio",
        action="store_true",
        help="Fix the aspect ratio fx/fy to the spec value (1.0 for square "
             "pixels) during optimization (CALIB_FIX_ASPECT_RATIO). Requires "
             "--use-spec-guess. Scale (absolute focal length) and principal "
             "point remain free.",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory for TOML/JSON. Defaults to <image_dir>.",
    )
    return parser.parse_args()


def _build_initial_camera_matrix(
    focal_mm: float, pixel_pitch_mm: float, image_size: tuple[int, int]
) -> numpy.ndarray:
    """Build initial camera matrix K from manufacturer spec values.

    fx = fy = focal_mm / pixel_pitch_mm (square pixels assumed),
    cx = W / 2, cy = H / 2.

    Args:
        focal_mm: Lens focal length in mm.
        pixel_pitch_mm: Sensor pixel pitch in mm (square pixels).
        image_size: Image size (width, height) in pixels.

    Returns:
        3x3 camera matrix, float64.
    """
    w, h = image_size
    f_px = focal_mm / pixel_pitch_mm
    return numpy.array([
        [f_px,  0.0,  w / 2.0],
        [ 0.0, f_px,  h / 2.0],
        [ 0.0,  0.0,      1.0],
    ], dtype=numpy.float64)


def main() -> int:
    args = parse_args()

    # Argument-only validation (before any image detection work).
    if args.fix_aspect_ratio and not args.use_spec_guess:
        print(
            "Error: --fix-aspect-ratio requires --use-spec-guess",
            file=sys.stderr,
        )
        return 1
    if args.use_spec_guess:
        if args.focal_mm is None or args.pixel_pitch_mm is None:
            print(
                "Error: --use-spec-guess requires --focal-mm and "
                "--pixel-pitch-mm",
                file=sys.stderr,
            )
            return 1
        if args.focal_mm <= 0 or args.pixel_pitch_mm <= 0:
            print(
                "Error: --focal-mm and --pixel-pitch-mm must be positive",
                file=sys.stderr,
            )
            return 1

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

    # Build initial camera matrix from spec values (image_size is now known).
    initial_camera_matrix = None
    if args.use_spec_guess:
        initial_camera_matrix = _build_initial_camera_matrix(
            args.focal_mm, args.pixel_pitch_mm, image_size
        )
        K0 = initial_camera_matrix
        w, h = image_size
        print(f"\nInitial camera matrix (from spec, used as intrinsic guess):")
        print(
            f"  focal={args.focal_mm}mm  pixel_pitch={args.pixel_pitch_mm}mm  "
            f"image={w}x{h}"
        )
        print(
            f"  fx={K0[0,0]:.2f}  fy={K0[1,1]:.2f}  "
            f"cx={K0[0,2]:.2f}  cy={K0[1,2]:.2f}"
        )
        print(f"  (NOT fixed; optimization starting point only)")
        if args.fix_aspect_ratio:
            ratio = K0[0, 0] / K0[1, 1]
            print(
                f"  aspect ratio fx/fy FIXED at {ratio:.3f} "
                f"(scale and principal point remain free)"
            )

    # Calibrate
    engine = CalibrationEngine()
    calib_result = engine.calibrate(
        object_points_list,
        image_points_list,
        image_size,
        lens_model=args.lens,
        initial_camera_matrix=initial_camera_matrix,
        fix_aspect_ratio=args.fix_aspect_ratio,
    )

    # Display results
    print(f"\n{'=' * 50}")
    print(f"RMS reprojection error: {calib_result.rms_error:.4f} px")
    print(f"\nCamera matrix:")
    K = calib_result.camera_matrix
    print(f"  fx={K[0,0]:.2f}  fy={K[1,1]:.2f}  cx={K[0,2]:.2f}  cy={K[1,2]:.2f}")
    print(f"\nDistortion coefficients ({calib_result.dist_coeffs.shape[1]} coefficients):")
    d = calib_result.dist_coeffs.flatten()
    labels = ["k1", "k2", "p1", "p2", "k3", "k4", "k5", "k6"]
    for label, val in zip(labels, d):
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
