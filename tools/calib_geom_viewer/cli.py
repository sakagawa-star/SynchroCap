from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable, Optional

from . import blender_export
from .geometry import CameraSpecError, CameraPose, compute_pair_stats, load_camera_poses
from .outputs import write_cameras_csv, write_pairs_csv
from .plotting import render_matplotlib_plot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Visualize Calib_board.toml camera poses using Matplotlib and Blender.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--toml", required=True, type=Path, help="Path to Calib_board.toml")
    parser.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="Output directory (must not already exist)",
    )
    parser.add_argument(
        "--matplotlib",
        choices=["on", "off"],
        default="on",
        help="Generate Matplotlib 3D plot",
    )
    parser.add_argument(
        "--blender",
        choices=["on", "off"],
        default="off",
        help="Generate Blender .blend scene",
    )
    parser.add_argument(
        "--blender-exec",
        default="blender",
        help="Blender executable path (used only when --blender on)",
    )
    parser.add_argument(
        "--axis-length",
        type=float,
        default=0.3,
        help="Length of the optical axis arrows (in meters)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (e.g., DEBUG, INFO, WARNING)",
    )
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logger = _configure_logging(args.log_level)

    try:
        _run(args, logger)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except CameraSpecError as exc:
        logger.error("Invalid camera specification: %s", exc)
        return 2
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 3
    except Exception:  # pragma: no cover - unexpected critical failure
        logger.exception("Unexpected error")
        return 99
    return 0


def _run(args, logger: logging.Logger) -> None:
    axis_length = args.axis_length
    if axis_length <= 0:
        raise ValueError("--axis-length must be positive.")

    toml_path = args.toml.expanduser().resolve()
    out_dir = args.out_dir.expanduser().resolve()
    if out_dir.exists():
        if not out_dir.is_dir():
            raise FileExistsError(f"Output path exists and is not a directory: {out_dir}")
        logger.warning("Writing into existing directory: %s", out_dir)
    else:
        out_dir.mkdir(parents=True, exist_ok=False)

    cameras = load_camera_poses(toml_path, logger)
    if not cameras:
        raise CameraSpecError("No valid cameras found in the TOML file.")

    logger.info("Loaded %d cameras from %s", len(cameras), toml_path)

    cameras_csv = out_dir / "cameras.csv"
    write_cameras_csv(cameras, cameras_csv)
    logger.info("Wrote camera centers and axes to %s", cameras_csv)

    plots_requested = args.matplotlib == "on"
    blender_requested = args.blender == "on"

    if len(cameras) >= 2:
        pairs = compute_pair_stats(cameras)
        pairs_csv = out_dir / "pairs.csv"
        write_pairs_csv(pairs, pairs_csv)
        logger.info("Wrote %d camera pair entries to %s", len(pairs), pairs_csv)
    else:
        logger.warning("Only %d camera available; skipping pairs.csv", len(cameras))

    if plots_requested:
        plot_path = out_dir / "plot3d.png"
        render_matplotlib_plot(cameras, axis_length, plot_path)
        logger.info("Saved Matplotlib visualization to %s", plot_path)

    if blender_requested:
        blend_path = out_dir / "calib_view.blend"
        blender_export.build_blender_scene(
            cameras=cameras,
            axis_length=axis_length,
            blend_path=blend_path,
            blender_exec=args.blender_exec,
            logger=logger,
        )
        logger.info("Generated Blender scene at %s", blend_path)

    logger.info("Done. Outputs stored under %s", out_dir)


def _configure_logging(level_name: str) -> logging.Logger:
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        raise ValueError(f"Invalid log level: {level_name}")
    logging.basicConfig(format="%(levelname)s | %(message)s", level=level)
    return logging.getLogger("calib_geom_viewer")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
