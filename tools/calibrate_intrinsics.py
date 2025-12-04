#!/usr/bin/env python3
from __future__ import annotations
import argparse
import csv
import glob
import json
import os
import sys
from dataclasses import dataclass

import cv2
import numpy as np
import toml
SUBPIX_CRITERIA = (
    cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
    30,
    0.001,
)
FISHEYE_CRITERIA = (
    cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
    100,
    1e-6,
)


class CalibrationError(RuntimeError):
    """Raised for predictable calibration failures."""


@dataclass
class CameraSpec:
    name: str
    pattern: str
    model: str  # "standard" or "fisheye"
    dirname: str


@dataclass
class CalibrationResult:
    name: str
    model: str
    images_used: int
    rms: float
    matrix: np.ndarray
    distortions: list[float]
    image_size: tuple[int, int]
    toml_name: str
    per_image_errors: list[tuple[str, float]]
    per_image_mean: float
    per_image_max: float


def parse_pattern_value(value: str) -> tuple[int, int]:
    parts = value.split(",")
    if len(parts) != 2:
        raise CalibrationError(
            "Pattern must be provided as 'cols,rows' with two integers."
        )
    try:
        cols = int(parts[0].strip())
        rows = int(parts[1].strip())
    except ValueError as exc:
        raise CalibrationError(
            "Pattern values must be integers greater than 1."
        ) from exc
    if cols <= 1 or rows <= 1:
        raise CalibrationError("Pattern values must both be greater than 1.")
    return cols, rows


def parse_square_value(value: str) -> float:
    try:
        size = float(value)
    except ValueError as exc:
        raise CalibrationError("Square size must be a positive number.") from exc
    if size <= 0:
        raise CalibrationError("Square size must be greater than 0.")
    return size


def parse_camera_arg(entry: str) -> CameraSpec:
    if "=" not in entry or ":" not in entry:
        raise CalibrationError(
            f"Invalid --camera format '{entry}'. Expected name=glob:model."
        )
    name, rest = entry.split("=", 1)
    pattern, model = rest.rsplit(":", 1)
    name = name.strip()
    pattern = pattern.strip()
    model = model.strip().lower()
    if not name:
        raise CalibrationError("Camera name cannot be empty.")
    if not pattern:
        raise CalibrationError(f"Camera '{name}' glob cannot be empty.")
    if model not in {"standard", "fisheye"}:
        raise CalibrationError(
            f"Camera '{name}' model must be 'standard' or 'fisheye'."
        )
    pattern_dir = os.path.dirname(os.path.normpath(pattern))
    dirname = os.path.basename(pattern_dir)
    if not dirname:
        dirname = name
    return CameraSpec(name=name, pattern=pattern, model=model, dirname=dirname)


def collect_image_paths(spec: CameraSpec) -> list[str]:
    paths = sorted(glob.glob(spec.pattern))
    if not paths:
        raise CalibrationError(
            f"No images matched pattern '{spec.pattern}' for camera '{spec.name}'."
        )
    return paths


def make_object_points(pattern_size: tuple[int, int], square_size: float) -> np.ndarray:
    cols, rows = pattern_size
    objp = np.zeros((cols * rows, 3), np.float32)
    grid = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp[:, :2] = grid * square_size
    return objp


def detect_corners(
    image_paths: list[str],
    pattern_size: tuple[int, int],
    use_fast_check: bool,
) -> tuple[list[np.ndarray], list[str], tuple[int, int]]:
    img_points: list[np.ndarray] = []
    used_images: list[str] = []
    image_size: tuple[int, int] | None = None
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
    if use_fast_check:
        flags |= cv2.CALIB_CB_FAST_CHECK

    for path in image_paths:
        image = cv2.imread(path)
        if image is None:
            print(f"Warning: unable to read image '{path}', skipping.", file=sys.stderr)
            continue
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(gray, pattern_size, flags)
        if not found:
            continue
        corners_refined = cv2.cornerSubPix(
            gray,
            corners,
            winSize=(11, 11),
            zeroZone=(-1, -1),
            criteria=SUBPIX_CRITERIA,
        )
        img_points.append(corners_refined)
        used_images.append(path)
        if image_size is None:
            h, w = gray.shape
            image_size = (w, h)

    if not img_points or image_size is None:
        raise CalibrationError(
            "No valid chessboard detections were found in the provided images."
        )
    return img_points, used_images, image_size


def calibrate_standard(
    obj_points: list[np.ndarray],
    img_points: list[np.ndarray],
    image_size: tuple[int, int],
    use_rational: bool,
) -> tuple[float, np.ndarray, np.ndarray, list[np.ndarray], list[np.ndarray]]:
    flags = cv2.CALIB_RATIONAL_MODEL if use_rational else 0
    rms, matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        obj_points,
        img_points,
        image_size,
        None,
        None,
        flags=flags,
    )
    return rms, matrix, dist_coeffs, rvecs, tvecs


def calibrate_fisheye(
    obj_points: list[np.ndarray],
    img_points: list[np.ndarray],
    image_size: tuple[int, int],
) -> tuple[float, np.ndarray, np.ndarray, list[np.ndarray], list[np.ndarray]]:
    obj_cv = [pts.reshape(-1, 1, 3).astype(np.float64) for pts in obj_points]
    img_cv = [pts.reshape(-1, 1, 2).astype(np.float64) for pts in img_points]
    matrix = np.eye(3, dtype=np.float64)
    dist = np.zeros((4, 1), dtype=np.float64)
    rms, matrix, dist, rvecs, tvecs = cv2.fisheye.calibrate(
        obj_cv,
        img_cv,
        image_size,
        matrix,
        dist,
        flags=cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC,
        criteria=FISHEYE_CRITERIA,
    )
    return rms, matrix, dist, rvecs, tvecs


def format_matrix(matrix: np.ndarray) -> str:
    rows = []
    for row in matrix:
        rows.append("[" + ", ".join(f"{val:.6f}" for val in row) + "]")
    return "[" + ", ".join(rows) + "]"


def compute_per_image_errors(
    matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    obj_points: list[np.ndarray],
    img_points: list[np.ndarray],
    rvecs: list[np.ndarray],
    tvecs: list[np.ndarray],
    image_paths: list[str],
    model: str,
) -> list[tuple[str, float]]:
    errors: list[tuple[str, float]] = []
    for obj, img, rvec, tvec, path in zip(
        obj_points, img_points, rvecs, tvecs, image_paths
    ):
        obj_arr = np.ascontiguousarray(obj, dtype=np.float64)
        img_arr = np.ascontiguousarray(img, dtype=np.float64)
        if model == "fisheye":
            projected, _ = cv2.fisheye.projectPoints(
                obj_arr.reshape(-1, 1, 3),
                rvec,
                tvec,
                matrix,
                dist_coeffs,
            )
        else:
            projected, _ = cv2.projectPoints(
                obj_arr,
                rvec,
                tvec,
                matrix,
                dist_coeffs,
            )
        diff = img_arr - projected
        rms = float(np.sqrt(np.mean(np.sum(diff**2, axis=2))))
        errors.append((path, rms))
    return errors


def write_csv(results: list[CalibrationResult], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["name", "rms", "fx", "fy", "cx", "cy", "model", "dist_json"])
        for res in results:
            fx = float(res.matrix[0, 0])
            fy = float(res.matrix[1, 1])
            cx = float(res.matrix[0, 2])
            cy = float(res.matrix[1, 2])
            writer.writerow(
                [
                    res.name,
                    f"{res.rms:.6f}",
                    f"{fx:.6f}",
                    f"{fy:.6f}",
                    f"{cx:.6f}",
                    f"{cy:.6f}",
                    res.model,
                    json.dumps(res.distortions),
                ]
            )


def write_per_image_errors(
    per_image_records: list[tuple[str, float]], path: str
) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["image_path", "rms_px"])
        for image_path, rms in per_image_records:
            writer.writerow([image_path, f"{rms:.6f}"])


def update_pose2sim(results: list[CalibrationResult], path: str) -> None:
    data: dict = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            data = toml.load(fh)
    for res in results:
        fx = float(res.matrix[0, 0])
        fy = float(res.matrix[1, 1])
        cx = float(res.matrix[0, 2])
        cy = float(res.matrix[1, 2])
        width, height = res.image_size
        toml_name = res.toml_name
        data[toml_name] = {
            "name": toml_name,
            "size": [float(width), float(height)],
            "matrix": [
                [fx, 0.0, cx],
                [0.0, fy, cy],
                [0.0, 0.0, 1.0],
            ],
            "distortions": list(res.distortions),
            "fisheye": res.model == "fisheye",
        }
    with open(path, "w", encoding="utf-8") as fh:
        toml.dump(data, fh)


def process_camera(
    spec: CameraSpec,
    intr_pattern_size: tuple[int, int],
    intr_square_size: float,
    use_rational: bool,
    use_fast_check: bool,
) -> CalibrationResult:
    image_paths = collect_image_paths(spec)
    img_pts, used, image_size = detect_corners(
        image_paths, intr_pattern_size, use_fast_check
    )
    total_images = len(image_paths)
    detections = len(used)
    if detections == 0:
        raise CalibrationError(
            f"Camera '{spec.name}' does not have enough valid detections."
        )
    obj_template = make_object_points(intr_pattern_size, intr_square_size)
    obj_pts = [obj_template.copy() for _ in img_pts]
    if spec.model == "standard":
        rms, matrix, dist_array, rvecs, tvecs = calibrate_standard(
            obj_pts, img_pts, image_size, use_rational
        )
    else:
        rms, matrix, dist_array, rvecs, tvecs = calibrate_fisheye(
            obj_pts, img_pts, image_size
        )
    matrix = matrix.astype(np.float64)
    dist_coeffs = np.ascontiguousarray(dist_array).reshape(-1, 1)
    per_image_errors = compute_per_image_errors(
        matrix,
        dist_coeffs,
        obj_pts,
        img_pts,
        rvecs,
        tvecs,
        used,
        spec.model,
    )
    per_image_values = [err for _, err in per_image_errors]
    per_image_mean = float(np.mean(per_image_values))
    per_image_max = float(np.max(per_image_values))
    result = CalibrationResult(
        name=spec.name,
        model=spec.model,
        images_used=detections,
        rms=float(rms),
        matrix=matrix,
        distortions=[float(d) for d in dist_coeffs.ravel()],
        image_size=image_size,
        toml_name=spec.dirname,
        per_image_errors=per_image_errors,
        per_image_mean=per_image_mean,
        per_image_max=per_image_max,
    )
    print(
        f"name={result.name}, images_used={result.images_used}, "
        f"rms={result.rms:.6f} px, dist_len={len(result.distortions)}"
    )
    verdict = (
        "PASS"
        if result.rms < 1.0
        else "WARN"
        if result.rms < 2.0
        else "FAIL"
    )
    print(
        f"total_images={total_images}, detections={result.images_used}, verdict={verdict}"
    )
    print(
        f"per-image RMS (mean={result.per_image_mean:.6f}, "
        f"max={result.per_image_max:.6f})"
    )
    print(f"K = {format_matrix(result.matrix)}")
    print(f"dist = {json.dumps(result.distortions)}\n")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute per-camera intrinsics from chessboard images."
    )
    parser.add_argument(
        "--intr-pattern",
        required=True,
        help="Intrinsics chessboard pattern as 'cols,rows'.",
    )
    parser.add_argument(
        "--intr-square",
        required=True,
        help="Intrinsics chessboard square size in meters.",
    )
    parser.add_argument(
        "--extr-pattern",
        help="Optional extrinsics chessboard pattern as 'cols,rows' (unused, reserved for future use).",
    )
    parser.add_argument(
        "--extr-square",
        help="Optional extrinsics chessboard square size in meters (unused, reserved for future use).",
    )
    parser.add_argument(
        "--rational",
        action="store_true",
        help="Enable CALIB_RATIONAL_MODEL for standard lenses (estimates k4-k6).",
    )
    parser.add_argument(
        "--fast-check",
        choices=["on", "off"],
        default="on",
        help="Toggle FAST_CHECK flag for corner detection (default: on).",
    )
    parser.add_argument(
        "--camera",
        action="append",
        required=True,
        help="Camera spec in the form name=glob:model. Repeat per camera.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        print("SQUARE SIZE UNIT = meters")
        intr_pattern_size = parse_pattern_value(args.intr_pattern)
        intr_square_size = parse_square_value(args.intr_square)
        print(
            f"INFO: intr_pattern=({intr_pattern_size[0]},{intr_pattern_size[1]}), "
            f"intr_square={intr_square_size:.6f} m"
        )
        if args.extr_pattern or args.extr_square:
            print(
                "Warning: --extr-pattern/--extr-square are currently unused "
                "and reserved for future use.",
                file=sys.stderr,
            )
        specs = [parse_camera_arg(entry) for entry in args.camera]
        use_fast_check = args.fast_check == "on"
        per_image_records: list[tuple[str, float]] = []
        results = [
            process_camera(
                spec,
                intr_pattern_size,
                intr_square_size,
                args.rational,
                use_fast_check,
            )
            for spec in specs
        ]
        for res in results:
            per_image_records.extend(res.per_image_errors)
        write_csv(results, "intrinsics_summary.csv")
        update_pose2sim(results, "intrinsics_pose2sim.toml")
        write_per_image_errors(
            per_image_records, "intrinsics_per_image_errors.csv"
        )
        return 0
    except CalibrationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # unexpected issues
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
