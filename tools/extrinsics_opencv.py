#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import toml

SUBPIX_CRITERIA = (
    cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
    30,
    0.001,
)


class ExtrinsicsError(RuntimeError):
    """Raised for predictable failures while estimating extrinsics."""


@dataclass
class CameraSpec:
    name: str
    pattern: str
    model: str  # only "standard" is supported


@dataclass
class IntrinsicsEntry:
    name: str
    matrix: np.ndarray
    distortions: np.ndarray
    size: Tuple[int, int]


@dataclass
class PoseResult:
    name: str
    image_path: str
    rms: float
    reproj_mean: float
    reproj_max: float
    num_points: int
    rotation_cb: np.ndarray
    translation_cb: np.ndarray


def parse_pattern_value(value: str) -> Tuple[int, int]:
    parts = value.split(",")
    if len(parts) != 2:
        raise ExtrinsicsError("Pattern must be provided as 'cols,rows'.")
    try:
        cols = int(parts[0].strip())
        rows = int(parts[1].strip())
    except ValueError as exc:
        raise ExtrinsicsError("Pattern values must be integers.") from exc
    if cols <= 1 or rows <= 1:
        raise ExtrinsicsError("Pattern values must both be greater than 1.")
    return cols, rows


def parse_square_value(value: str) -> float:
    try:
        square = float(value)
    except ValueError as exc:
        raise ExtrinsicsError("Square size must be a positive number.") from exc
    if square <= 0.0:
        raise ExtrinsicsError("Square size must be greater than 0.")
    return square


def parse_camera_arg(entry: str) -> CameraSpec:
    if "=" not in entry or ":" not in entry:
        raise ExtrinsicsError(
            f"Invalid --camera format '{entry}'. Expected name=glob:model."
        )
    name, rest = entry.split("=", 1)
    pattern, model = rest.rsplit(":", 1)
    name = name.strip()
    pattern = pattern.strip()
    model = model.strip().lower()
    if not name:
        raise ExtrinsicsError("Camera name cannot be empty.")
    if not pattern:
        raise ExtrinsicsError(f"Camera '{name}' glob cannot be empty.")
    if model != "standard":
        raise ExtrinsicsError(
            f"Camera '{name}' model must be 'standard'. Fisheye is unsupported."
        )
    return CameraSpec(name=name, pattern=pattern, model=model)


def collect_image_paths(spec: CameraSpec) -> List[str]:
    paths = sorted(glob.glob(spec.pattern))
    if not paths:
        raise ExtrinsicsError(
            f"No images matched pattern '{spec.pattern}' for camera '{spec.name}'."
        )
    return paths


def make_object_points(pattern_size: Tuple[int, int], square_size: float) -> np.ndarray:
    cols, rows = pattern_size
    obj = np.zeros((cols * rows, 3), np.float64)
    grid = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    obj[:, :2] = grid * square_size
    return obj


def parse_size_entry(value: List[float], camera_name: str) -> Tuple[int, int]:
    if len(value) != 2:
        raise ExtrinsicsError(
            f"Camera '{camera_name}' intrinsics must include two size values."
        )
    width = _parse_dimension_value(value[0], camera_name, "width")
    height = _parse_dimension_value(value[1], camera_name, "height")
    return width, height


def _parse_dimension_value(value: float, camera_name: str, label: str) -> int:
    if isinstance(value, (int, float)):
        if value <= 0:
            raise ExtrinsicsError(
                f"Camera '{camera_name}' {label} must be a positive number."
            )
        rounded = int(round(float(value)))
        if abs(rounded - float(value)) > 1e-6:
            raise ExtrinsicsError(
                f"Camera '{camera_name}' {label} must be an integer value."
            )
        return rounded
    raise ExtrinsicsError(
        f"Camera '{camera_name}' {label} must be a numeric value."
    )


def load_intrinsics(path: str) -> Dict[str, IntrinsicsEntry]:
    if not os.path.exists(path):
        raise ExtrinsicsError(f"Intrinsics file '{path}' was not found.")
    with open(path, "r", encoding="utf-8") as fh:
        data = toml.load(fh)
    if not isinstance(data, dict) or not data:
        raise ExtrinsicsError(f"Intrinsics file '{path}' does not contain cameras.")
    intrinsics: Dict[str, IntrinsicsEntry] = {}
    for name, entry in data.items():
        if not isinstance(entry, dict):
            raise ExtrinsicsError(
                f"Camera '{name}' intrinsics entry must be a table."
            )
        if entry.get("fisheye"):
            raise ExtrinsicsError(
                f"Camera '{name}' intrinsics set fisheye=true which is unsupported."
            )
        try:
            matrix_data = entry["matrix"]
            distortions = entry["distortions"]
            size_entry = entry["size"]
        except KeyError as exc:
            raise ExtrinsicsError(
                f"Camera '{name}' intrinsics entry is missing {exc.args[0]}."
            ) from exc
        matrix = np.array(matrix_data, dtype=np.float64)
        if matrix.shape != (3, 3):
            raise ExtrinsicsError(
                f"Camera '{name}' intrinsics matrix must be 3x3."
            )
        dist_array = np.array(distortions, dtype=np.float64).reshape(-1, 1)
        # OpenCV solvePnP / projectPoints は 4/5/8/12/14 を許容（rational など）
        if dist_array.size not in {4, 5, 8, 12, 14}:
            raise ExtrinsicsError(
                f"Camera '{name}' distortions must have 4, 5, 8, 12, or 14 coefficients (got {dist_array.size})."
            )
        width, height = parse_size_entry(size_entry, name)
        intrinsics[name] = IntrinsicsEntry(
            name=name,
            matrix=np.ascontiguousarray(matrix, dtype=np.float64),
            distortions=np.ascontiguousarray(dist_array, dtype=np.float64),
            size=(width, height),
        )
    return intrinsics


def compute_pose_for_image(
    image_path: str,
    camera_name: str,
    intr: IntrinsicsEntry,
    obj_points: np.ndarray,
    pattern_size: Tuple[int, int],
    use_fast_check: bool,
    pnp_flag: int,
    refine_mode: str,
    subpix_iter: int,
    subpix_eps: float,
) -> Optional[PoseResult]:
    image = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if image is None:
        raise ExtrinsicsError(
            f"Unable to read image '{image_path}' for camera '{camera_name}'."
        )
    height, width = image.shape[:2]
    expected_width, expected_height = intr.size
    if (width, height) != (expected_width, expected_height):
        raise ExtrinsicsError(
            f"Image '{image_path}' for camera '{camera_name}' has size "
            f"{width}x{height}, expected {expected_width}x{expected_height}."
        )
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
    if use_fast_check:
        flags |= cv2.CALIB_CB_FAST_CHECK
    found, corners = cv2.findChessboardCorners(gray, pattern_size, flags)
    if not found:
        return None
    corners_refined = cv2.cornerSubPix(
        gray,
        corners,
        winSize=(11, 11),
        zeroZone=(-1, -1),
        criteria=(
            SUBPIX_CRITERIA[0],
            subpix_iter,
            subpix_eps,
        ),
    )
    obj_cv = np.ascontiguousarray(obj_points, dtype=np.float64)
    img_cv = np.ascontiguousarray(corners_refined, dtype=np.float64)
    success, rvec, tvec = cv2.solvePnP(
        obj_cv,
        img_cv,
        intr.matrix,
        intr.distortions,
        flags=pnp_flag,
    )
    if not success:
        raise ExtrinsicsError(
            f"solvePnP failed for image '{image_path}' on camera '{camera_name}'."
        )
    if refine_mode == "lm":
        if not hasattr(cv2, "solvePnPRefineLM"):
            raise ExtrinsicsError("solvePnPRefineLM is not available in this OpenCV build.")
        rvec, tvec = cv2.solvePnPRefineLM(
            obj_cv,
            img_cv,
            intr.matrix,
            intr.distortions,
            rvec,
            tvec,
        )
    projected, _ = cv2.projectPoints(
        obj_cv,
        rvec,
        tvec,
        intr.matrix,
        intr.distortions,
    )
    diff = img_cv - projected
    diff_sq = np.sum(diff**2, axis=2)
    rms = float(np.sqrt(np.mean(diff_sq)))
    per_point = np.sqrt(diff_sq)
    reproj_mean = float(np.mean(per_point))
    reproj_max = float(np.max(per_point))
    r_matrix, _ = cv2.Rodrigues(rvec)
    r_cb = r_matrix.T
    t_cb = -r_cb @ tvec
    rvec_cb, _ = cv2.Rodrigues(r_cb)
    return PoseResult(
        name=camera_name,
        image_path=image_path,
        rms=rms,
        reproj_mean=reproj_mean,
        reproj_max=reproj_max,
        num_points=img_cv.shape[0],
        rotation_cb=rvec_cb.reshape(3),
        translation_cb=t_cb.reshape(3),
    )


def process_camera(
    spec: CameraSpec,
    intr: IntrinsicsEntry,
    obj_points: np.ndarray,
    pattern_size: Tuple[int, int],
    use_fast_check: bool,
    image_index: Optional[int],
    select_best: bool,
    pnp_flag: int,
    refine_mode: str,
    subpix_iter: int,
    subpix_eps: float,
) -> PoseResult:
    paths = collect_image_paths(spec)
    if image_index is not None:
        if image_index < 0 or image_index >= len(paths):
            raise ExtrinsicsError(
                f"--image-index {image_index} is out of range for camera "
                f"'{spec.name}' with {len(paths)} images."
            )
        pose = compute_pose_for_image(
            paths[image_index],
            spec.name,
            intr,
            obj_points,
            pattern_size,
            use_fast_check,
            pnp_flag,
            refine_mode,
            subpix_iter,
            subpix_eps,
        )
        if pose is None:
            raise ExtrinsicsError(
                f"Chessboard was not detected in image '{paths[image_index]}' "
                f"for camera '{spec.name}'."
            )
        return pose
    if select_best:
        best_pose: Optional[PoseResult] = None
        for path in paths:
            pose = compute_pose_for_image(
                path,
                spec.name,
                intr,
                obj_points,
                pattern_size,
                use_fast_check,
                pnp_flag,
                refine_mode,
                subpix_iter,
                subpix_eps,
            )
            if pose is None:
                continue
            if best_pose is None or pose.rms < best_pose.rms:
                best_pose = pose
        if best_pose is None:
            raise ExtrinsicsError(
                f"No valid chessboard detections were found for camera '{spec.name}'."
            )
        return best_pose
    pose = compute_pose_for_image(
        paths[0],
        spec.name,
        intr,
        obj_points,
        pattern_size,
        use_fast_check,
        pnp_flag,
        refine_mode,
        subpix_iter,
        subpix_eps,
    )
    if pose is None:
        raise ExtrinsicsError(
            f"Chessboard was not detected in image '{paths[0]}' "
            f"for camera '{spec.name}'."
        )
    return pose


def write_summary_csv(results: List[PoseResult], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["name", "image_path", "rms_px", "num_points", "reproj_mean_px", "reproj_max_px"]
        )
        for res in results:
            writer.writerow(
                [
                    res.name,
                    res.image_path,
                    f"{res.rms:.6f}",
                    res.num_points,
                    f"{res.reproj_mean:.6f}",
                    f"{res.reproj_max:.6f}",
                ]
            )


def update_extrinsics_file(path: str, results: List[PoseResult]) -> None:
    data: Dict[str, dict] = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            loaded = toml.load(fh)
        if isinstance(loaded, dict):
            data = loaded
    for res in results:
        data[res.name] = {
            "rotation": [float(val) for val in res.rotation_cb],
            "translation": [float(val) for val in res.translation_cb],
        }
    with open(path, "w", encoding="utf-8") as fh:
        toml.dump(data, fh)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate camera extrinsics with fixed intrinsics using OpenCV solvePnP."
    )
    parser.add_argument(
        "--extr-pattern",
        required=True,
        help="Extrinsics chessboard pattern as 'cols,rows'.",
    )
    parser.add_argument(
        "--extr-square",
        required=True,
        help="Extrinsics chessboard square size in meters.",
    )
    parser.add_argument(
        "--intrinsics",
        required=True,
        help="Path to intrinsics_pose2sim.toml.",
    )
    parser.add_argument(
        "--camera",
        action="append",
        required=True,
        help="Camera spec in the form name=glob:standard. Repeat per camera.",
    )
    parser.add_argument(
        "--image-index",
        type=int,
        help="Zero-based index into the sorted image list for each camera.",
    )
    parser.add_argument(
        "--select",
        choices=["best"],
        help="Select best image based on minimum reprojection RMS (use 'best').",
    )
    parser.add_argument(
        "--fast-check",
        choices=["on", "off"],
        default="on",
        help="Toggle FAST_CHECK flag for corner detection (default: on).",
    )
    parser.add_argument(
        "--pnp",
        choices=["iterative", "ippe", "ippe_square"],
        default="iterative",
        help="PnP method to use for solvePnP (default: iterative).",
    )
    parser.add_argument(
        "--refine",
        choices=["none", "lm"],
        default="none",
        help="Optional refinement step after solvePnP (default: none).",
    )
    parser.add_argument(
        "--subpix-iter",
        type=int,
        default=30,
        help="Maximum cornerSubPix iterations (default: 30).",
    )
    parser.add_argument(
        "--subpix-eps",
        type=float,
        default=1e-3,
        help="cornerSubPix epsilon termination (default: 1e-3).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        pattern_size = parse_pattern_value(args.extr_pattern)
        square_size = parse_square_value(args.extr_square)
        if args.image_index is not None and args.select:
            raise ExtrinsicsError("--image-index and --select best cannot be used together.")
        camera_specs = [parse_camera_arg(entry) for entry in args.camera]
        intrinsics = load_intrinsics(args.intrinsics)
        obj_points = make_object_points(pattern_size, square_size)
        use_fast_check = args.fast_check == "on"
        select_best = args.select == "best"
        if args.subpix_iter <= 0:
            raise ExtrinsicsError("--subpix-iter must be a positive integer.")
        if args.subpix_eps <= 0:
            raise ExtrinsicsError("--subpix-eps must be a positive value.")
        if args.pnp in ("ippe", "ippe_square"):
            needed = "SOLVEPNP_IPPE_SQUARE" if args.pnp == "ippe_square" else "SOLVEPNP_IPPE"
            if not hasattr(cv2, needed):
                raise ExtrinsicsError(f"This OpenCV build does not provide cv2.{needed}.")
        pnp_flag = {
            "iterative": cv2.SOLVEPNP_ITERATIVE,
            "ippe": cv2.SOLVEPNP_IPPE,
            "ippe_square": cv2.SOLVEPNP_IPPE_SQUARE,
        }[args.pnp]
        refine_mode = args.refine
        results: List[PoseResult] = []
        for spec in camera_specs:
            if spec.name not in intrinsics:
                raise ExtrinsicsError(
                    f"Camera '{spec.name}' is missing from '{args.intrinsics}'."
                )
            pose = process_camera(
                spec,
                intrinsics[spec.name],
                obj_points,
                pattern_size,
                use_fast_check,
                args.image_index,
                select_best,
                pnp_flag,
                refine_mode,
                args.subpix_iter,
                args.subpix_eps,
            )
            verdict = (
                "PASS"
                if pose.rms < 1.0
                else "WARN"
                if pose.rms < 2.0
                else "FAIL"
            )
            print(
                f"name={pose.name}, image={pose.image_path}, "
                f"rms={pose.rms:.6f} px, mean={pose.reproj_mean:.6f}, "
                f"max={pose.reproj_max:.6f}, points={pose.num_points}"
            )
            print(f"verdict={verdict}")
            results.append(pose)
        write_summary_csv(results, "extrinsics_summary.csv")
        update_extrinsics_file("extrinsics_pose2sim.toml", results)
        return 0
    except ExtrinsicsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # unexpected errors
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
