from __future__ import annotations

import itertools
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

import numpy as np

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for <3.11
    import tomli as tomllib  # type: ignore[no-redef]


NumericVector = Sequence[float]


@dataclass(frozen=True)
class CameraPose:
    """Holds camera pose information expressed in world coordinates."""

    name: str
    center: np.ndarray  # shape (3,)
    axis: np.ndarray  # unit vector, shape (3,)
    rotation_c2w: np.ndarray  # shape (3, 3)
    translation: np.ndarray  # original translation vector (world->camera)


@dataclass(frozen=True)
class CameraPairStats:
    """Baseline distance and axis angle between two cameras."""

    cam_a: str
    cam_b: str
    baseline: float
    axis_angle_deg: float


class CameraSpecError(Exception):
    """Raised when a camera definition is invalid."""


def load_camera_poses(toml_path: Path, logger: logging.Logger) -> List[CameraPose]:
    """Parse the TOML file and build camera poses."""

    if not toml_path.exists():
        raise FileNotFoundError(f"TOML file not found: {toml_path}")

    with toml_path.open("rb") as f:
        data = tomllib.load(f)

    cameras: List[CameraPose] = []
    for section_name, section in data.items():
        if not isinstance(section, dict):
            continue
        try:
            pose = _build_camera_from_section(section)
        except CameraSpecError as exc:
            logger.error("Skipping section %s: %s", section_name, exc)
            continue
        except Exception as exc:  # pragma: no cover - unexpected parsing failure
            logger.exception("Skipping section %s due to unexpected error: %s", section_name, exc)
            continue
        cameras.append(pose)

    return cameras


def _build_camera_from_section(section: dict) -> CameraPose:
    name = section.get("name")
    if not isinstance(name, str) or not name:
        raise CameraSpecError("Key 'name' must be a non-empty string.")

    rotation = _vector(section, "rotation", 3, name)
    translation = _vector(section, "translation", 3, name)

    matrix = section.get("matrix")
    if matrix is None:
        raise CameraSpecError("Key 'matrix' is required (even if unused).")
    _ = _matrix3x3(matrix, name)

    R_world_to_cam = rodrigues_to_matrix(rotation)
    R_cam_to_world = R_world_to_cam.T
    center = -R_cam_to_world @ translation
    axis = normalize_vector(R_cam_to_world @ np.array([0.0, 0.0, 1.0]))

    return CameraPose(
        name=name,
        center=center,
        axis=axis,
        rotation_c2w=R_cam_to_world,
        translation=translation,
    )


def rodrigues_to_matrix(rvec: NumericVector) -> np.ndarray:
    """Convert a Rodrigues vector into a rotation matrix."""

    vec = np.asarray(rvec, dtype=float).reshape(3)
    theta = np.linalg.norm(vec)
    if not np.isfinite(theta):
        raise CameraSpecError("Rotation vector contains non-finite values.")

    if theta < 1e-12:
        return np.eye(3)

    k = vec / theta
    K = np.array(
        [
            [0.0, -k[2], k[1]],
            [k[2], 0.0, -k[0]],
            [-k[1], k[0], 0.0],
        ]
    )
    R = np.eye(3) + math.sin(theta) * K + (1.0 - math.cos(theta)) * (K @ K)
    return R


def normalize_vector(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    if norm < 1e-12:
        raise CameraSpecError("Vector norm is too small to normalize.")
    return vec / norm


def _vector(section: dict, key: str, expected_len: int, name: str) -> np.ndarray:
    raw = section.get(key)
    if raw is None:
        raise CameraSpecError(f"Missing '{key}' for camera '{name}'.")
    try:
        arr = np.asarray(raw, dtype=float).reshape(expected_len)
    except Exception as exc:
        raise CameraSpecError(f"Key '{key}' for camera '{name}' must be a list of {expected_len} numbers.") from exc
    if not np.all(np.isfinite(arr)):
        raise CameraSpecError(f"Key '{key}' for camera '{name}' contains non-finite values.")
    return arr


def _matrix3x3(value: Iterable[Iterable[float]], name: str) -> np.ndarray:
    try:
        mat = np.asarray(value, dtype=float)
    except Exception as exc:
        raise CameraSpecError(f"Key 'matrix' for camera '{name}' must be a 3x3 numeric array.") from exc
    if mat.shape != (3, 3):
        raise CameraSpecError(f"Key 'matrix' for camera '{name}' must be 3x3, got {mat.shape}.")
    if not np.all(np.isfinite(mat)):
        raise CameraSpecError(f"Key 'matrix' for camera '{name}' contains non-finite values.")
    return mat


def compute_pair_stats(cameras: Sequence[CameraPose]) -> List[CameraPairStats]:
    """Compute pairwise baselines and axis angles."""

    stats: List[CameraPairStats] = []
    for cam_a, cam_b in itertools.combinations(cameras, 2):
        baseline = float(np.linalg.norm(cam_a.center - cam_b.center))
        dot = float(np.clip(np.dot(cam_a.axis, cam_b.axis), -1.0, 1.0))
        axis_angle = math.degrees(math.acos(dot))
        stats.append(
            CameraPairStats(
                cam_a=cam_a.name,
                cam_b=cam_b.name,
                baseline=baseline,
                axis_angle_deg=axis_angle,
            )
        )
    return stats
