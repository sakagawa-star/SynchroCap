from __future__ import annotations

import csv
from pathlib import Path
from typing import Sequence

from .geometry import CameraPairStats, CameraPose


def write_cameras_csv(cameras: Sequence[CameraPose], csv_path: Path) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(["name", "Cx", "Cy", "Cz", "ax", "ay", "az"])
        for cam in cameras:
            writer.writerow(
                [
                    cam.name,
                    *(_fmt(value) for value in (*cam.center, *cam.axis)),
                ]
            )


def write_pairs_csv(pairs: Sequence[CameraPairStats], csv_path: Path) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(["cam_i", "cam_j", "baseline_m", "axis_angle_deg"])
        for pair in pairs:
            writer.writerow(
                [
                    pair.cam_a,
                    pair.cam_b,
                    _fmt(pair.baseline),
                    _fmt(pair.axis_angle_deg),
                ]
            )


def _fmt(value: float) -> str:
    return f"{value:.9f}"
