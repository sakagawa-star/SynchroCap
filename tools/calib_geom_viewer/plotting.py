from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np

from .geometry import CameraPose


def render_matplotlib_plot(cameras: Sequence[CameraPose], axis_length: float, output_path: Path) -> None:
    """Render a 3D scatter plot of camera centers and optical axes."""

    if not cameras:
        raise ValueError("No cameras available for plotting.")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # pylint: disable=import-error
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Matplotlib is required for --matplotlib on.") from exc

    centers = np.array([cam.center for cam in cameras])
    fig = plt.figure(figsize=(8, 6))
    ax = fig.add_subplot(111, projection="3d")
    ax.scatter(centers[:, 0], centers[:, 1], centers[:, 2], color="C0", label="Camera centers")

    for cam in cameras:
        ax.text(cam.center[0], cam.center[1], cam.center[2], cam.name, fontsize=8, color="black")
        ax.quiver(
            cam.center[0],
            cam.center[1],
            cam.center[2],
            cam.axis[0],
            cam.axis[1],
            cam.axis[2],
            length=axis_length,
            normalize=True,
            color="C1",
        )

    _set_isotropic_axes(ax, centers)
    ax.set_xlabel("X [m]")
    ax.set_ylabel("Y [m]")
    ax.set_zlabel("Z [m]")
    ax.legend()
    ax.set_title("Calibrated camera geometry")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def _set_isotropic_axes(ax, centers: np.ndarray) -> None:
    mins = centers.min(axis=0)
    maxs = centers.max(axis=0)
    centers_range = max(maxs - mins)
    if centers_range < 1e-6:
        centers_range = 1.0
    mid = (maxs + mins) / 2.0
    half = centers_range / 2.0
    ax.set_xlim(mid[0] - half, mid[0] + half)
    ax.set_ylim(mid[1] - half, mid[1] + half)
    ax.set_zlim(mid[2] - half, mid[2] + half)
    try:
        ax.set_box_aspect((1, 1, 1))
    except AttributeError:  # pragma: no cover - matplotlib <3.3
        pass
