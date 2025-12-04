#!/usr/bin/env python3
from __future__ import annotations
import argparse
import csv
import glob
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


class CalibrationError(RuntimeError):
    """Raised for predictable calibration failures."""


@dataclass
class CameraSpec:
    name: str
    pattern: str
    model: str  # "standard" or "fisheye"
    dirname: str


@dataclass
class IntrinsicsEntry:
    name: str
    matrix: np.ndarray
    distortions: np.ndarray
    image_size: tuple[int, int]
    fisheye: bool


@dataclass
class ExtrinsicsResult:
    name: str
    images_used: int
    total_images: int
    image_path: str
    rms: float
    num_points: int
    reproj_mean: float
    reproj_max: float
    rotation: list[float]
    translation: list[float]
    toml_name: str


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


def load_intrinsics(path: str) -> dict[str, IntrinsicsEntry]:
    if not os.path.exists(path):
        raise CalibrationError(f"Intrinsics file '{path}' does not exist.")
    with open(path, "r", encoding="utf-8") as fh:
        data = toml.load(fh)
    if not isinstance(data, dict) or not data:
        raise CalibrationError(
            f"Intrinsics file '{path}' does not contain any camera data."
        )
    entries: dict[str, IntrinsicsEntry] = {}
    for name, section in data.items():
        if not isinstance(section, dict):
            raise CalibrationError(
                f"Intrinsics section '{name}' must be a table of values."
            )
        try:
            matrix_raw = section["matrix"]
            distortions_raw = section["distortions"]
            size_raw = section["size"]
            fisheye = bool(section.get("fisheye", False))
        except KeyError as exc:
            raise CalibrationError(
                f"Intrinsics section '{name}' is missing required field '{exc.args[0]}'."
            ) from exc
        matrix = np.array(matrix_raw, dtype=float)
        if matrix.shape != (3, 3):
            raise CalibrationError(
                f"Intrinsics section '{name}' matrix must be 3x3."
            )
        distortions = np.array(distortions_raw, dtype=float).reshape(-1)
        if fisheye and distortions.size != 4:
            raise CalibrationError(
                f"Intrinsics section '{name}' (fisheye) distortions must contain exactly 4 values."
            )
        if not isinstance(size_raw, (list, tuple)) or len(size_raw) != 2:
            raise CalibrationError(
                f"Intrinsics section '{name}' size must contain width and height."
            )
        width = int(round(float(size_raw[0])))
        height = int(round(float(size_raw[1])))
        entries[name] = IntrinsicsEntry(
            name=name,
            matrix=matrix.astype(np.float64),
            distortions=distortions.astype(np.float64),
            image_size=(width, height),
            fisheye=fisheye,
        )
    return entries


def resolve_intrinsics_section(
    spec: CameraSpec, entries: dict[str, IntrinsicsEntry]
) -> IntrinsicsEntry:
    dirname = spec.dirname
    if dirname in entries:
        return entries[dirname]
    candidates: list[str] = [dirname]
    if dirname.startswith("ext_"):
        remapped = "int_" + dirname[len("ext_") :]
        candidates.append(remapped)
        if remapped in entries:
            return entries[remapped]
    raise CalibrationError(
        f"Could not find intrinsics section for directory '{dirname}' "
        f"(camera '{spec.name}', glob '{spec.pattern}'). Checked: {', '.join(candidates)}."
    )


def detect_corners(
    image_path: str,
    pattern_size: tuple[int, int],
    criteria: tuple[int, int, float],
) -> tuple[np.ndarray, tuple[int, int]]:
    image = cv2.imread(image_path)
    if image is None:
        raise CalibrationError(f"Unable to read image '{image_path}'.")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    flags = (
        cv2.CALIB_CB_ADAPTIVE_THRESH
        | cv2.CALIB_CB_NORMALIZE_IMAGE
        | cv2.CALIB_CB_FAST_CHECK
    )
    found, corners = cv2.findChessboardCorners(gray, pattern_size, flags)
    if not found:
        raise CalibrationError(
            f"Chessboard pattern {pattern_size} was not detected in '{image_path}'."
        )
    corners_refined = cv2.cornerSubPix(
        gray,
        corners,
        winSize=(11, 11),
        zeroZone=(-1, -1),
        criteria=criteria,
    )
    h, w = gray.shape
    return corners_refined, (w, h)


def compute_camera_pose(
    obj_points: np.ndarray,
    img_points: np.ndarray,
    intr: IntrinsicsEntry,
    pnp_flag: int,
    refine_mode: str,
) -> tuple[np.ndarray, np.ndarray, float, float, float]:
    if intr.fisheye:
        raise CalibrationError(
            f"Camera '{intr.name}' is marked as fisheye, which is not supported."
        )
    obj = np.ascontiguousarray(obj_points, dtype=np.float64)
    img = np.ascontiguousarray(img_points, dtype=np.float64)
    success, rvec, tvec = cv2.solvePnP(
        obj,
        img,
        intr.matrix,
        intr.distortions,
        flags=pnp_flag,
    )
    if not success:
        raise CalibrationError(
            f"solvePnP failed for intrinsics section '{intr.name}'."
        )
    if refine_mode == "lm":
        rvec, tvec = cv2.solvePnPRefineLM(
            obj,
            img,
            intr.matrix,
            intr.distortions,
            rvec,
            tvec,
        )
    projected, _ = cv2.projectPoints(
        obj,
        rvec,
        tvec,
        intr.matrix,
        intr.distortions,
    )
    observed = img.reshape(-1, 1, 2)
    deltas = observed - projected
    per_point = np.linalg.norm(deltas.reshape(-1, 2), axis=1)
    rms = float(np.sqrt(np.mean(per_point**2)))
    mean_err = float(np.mean(per_point))
    max_err = float(np.max(per_point))
    return rvec, tvec, rms, mean_err, max_err


def invert_pose(rvec: np.ndarray, tvec: np.ndarray) -> tuple[list[float], list[float]]:
    rot_mat, _ = cv2.Rodrigues(rvec)
    rot_c2w = rot_mat.T
    t_c2w = -rot_c2w @ tvec
    rvec_c2w, _ = cv2.Rodrigues(rot_c2w)
    rotation = [float(val) for val in rvec_c2w.reshape(-1)]
    translation = [float(val) for val in t_c2w.reshape(-1)]
    return rotation, translation


def process_camera(
    spec: CameraSpec,
    intr_entry: IntrinsicsEntry,
    pattern_size: tuple[int, int],
    obj_template: np.ndarray,
    subpix_criteria: tuple[int, int, float],
    pnp_flag: int,
    refine_mode: str,
) -> ExtrinsicsResult:
    if spec.model != "standard":
        raise CalibrationError(
            f"Camera '{spec.name}' model '{spec.model}' is not supported for extrinsics estimation."
        )
    image_paths = collect_image_paths(spec)
    total_images = len(image_paths)
    image_path = image_paths[0]
    img_points, image_size = detect_corners(
        image_path,
        pattern_size,
        subpix_criteria,
    )
    if image_size != intr_entry.image_size:
        # Allow differing numeric types but ensure geometry matches.
        if tuple(map(int, image_size)) != intr_entry.image_size:
            raise CalibrationError(
                f"Image '{image_path}' size {image_size} does not match intrinsics "
                f"{intr_entry.image_size} for section '{intr_entry.name}'."
            )
    obj_points = obj_template.astype(np.float64)
    rvec, tvec, rms, mean_err, max_err = compute_camera_pose(
        obj_points,
        img_points,
        intr_entry,
        pnp_flag,
        refine_mode,
    )
    rotation, translation = invert_pose(rvec, tvec)
    detections = int(len(img_points))
    result = ExtrinsicsResult(
        name=spec.name,
        images_used=1,
        total_images=total_images,
        image_path=image_path,
        rms=rms,
        num_points=detections,
        reproj_mean=mean_err,
        reproj_max=max_err,
        rotation=rotation,
        translation=translation,
        toml_name=intr_entry.name,
    )
    return result


def write_toml(results: list[ExtrinsicsResult], path: str) -> None:
    data: dict = {}
    for res in results:
        data[res.toml_name] = {
            "rotation": [float(val) for val in res.rotation],
            "translation": [float(val) for val in res.translation],
        }
    with open(path, "w", encoding="utf-8") as fh:
        toml.dump(data, fh)


def write_csv(results: list[ExtrinsicsResult], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "name",
                "image_path",
                "rms_px",
                "num_points",
                "reproj_mean_px",
                "reproj_max_px",
            ]
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate per-camera extrinsics from chessboard images."
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
        help="Path to the intrinsics_pose2sim.toml file.",
    )
    parser.add_argument(
        "--camera",
        action="append",
        required=True,
        help="Camera spec in the form name=glob:model. Repeat per camera.",
    )
    parser.add_argument(
        "--pnp",
        choices=["iterative", "ippe", "ippe_square"],
        default="iterative",
        help="PnP method to use (default: iterative).",
    )
    parser.add_argument(
        "--refine",
        choices=["none", "lm"],
        default="lm",
        help="Optional refinement step applied after solvePnP (default: lm).",
    )
    parser.add_argument(
        "--subpix-iter",
        type=int,
        default=30,
        help="Maximum iterations for cornerSubPix (default: 30).",
    )
    parser.add_argument(
        "--subpix-eps",
        type=float,
        default=1e-3,
        help="Epsilon termination for cornerSubPix (default: 1e-3).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        extr_pattern_size = parse_pattern_value(args.extr_pattern)
        extr_square_size = parse_square_value(args.extr_square)
        print(
            f"INFO: extr_pattern=({extr_pattern_size[0]},{extr_pattern_size[1]}), "
            f"extr_square={extr_square_size:.6f} m"
        )
        if args.subpix_iter <= 0:
            raise CalibrationError("--subpix-iter must be a positive integer.")
        if args.subpix_eps <= 0:
            raise CalibrationError("--subpix-eps must be a positive value.")
        pnp_flag = {
            "iterative": cv2.SOLVEPNP_ITERATIVE,
            "ippe": cv2.SOLVEPNP_IPPE,
            "ippe_square": cv2.SOLVEPNP_IPPE_SQUARE,
        }[args.pnp]
        refine_mode = args.refine
        subpix_criteria = (
            SUBPIX_CRITERIA[0],
            args.subpix_iter,
            args.subpix_eps,
        )
        intrinsics_entries = load_intrinsics(args.intrinsics)
        specs = [parse_camera_arg(entry) for entry in args.camera]
        obj_template = make_object_points(extr_pattern_size, extr_square_size)
        results: list[ExtrinsicsResult] = []
        for spec in specs:
            intr_entry = resolve_intrinsics_section(spec, intrinsics_entries)
            print(
                f"INFO: using intrinsics section '{intr_entry.name}' for dir '{spec.dirname}'"
            )
            result = process_camera(
                spec,
                intr_entry,
                extr_pattern_size,
                obj_template,
                subpix_criteria,
                pnp_flag,
                refine_mode,
            )
            results.append(result)
            print(
                f"{result.name}: images_used={result.images_used}, rms={result.rms:.6f} px, "
                f"pnp={args.pnp}, refine={args.refine}"
            )
            verdict = (
                "PASS"
                if result.rms < 1.0
                else "WARN"
                if result.rms < 2.0
                else "FAIL"
            )
            print(
                f"total_images={result.total_images}, detections={result.num_points}, verdict={verdict}"
            )
        write_csv(results, "extrinsics_summary.csv")
        write_toml(results, "extrinsics_pose2sim.toml")
        return 0
    except CalibrationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # unexpected issues
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
