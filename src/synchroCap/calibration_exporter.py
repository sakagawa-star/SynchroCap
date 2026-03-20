"""Export calibration results to Pose2Sim TOML and generic JSON."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from calibration_engine import CalibrationResult

logger = logging.getLogger(__name__)


class CalibrationExporter:
    """Export calibration results to Pose2Sim TOML and generic JSON."""

    def export(
        self,
        result: CalibrationResult,
        serial: str,
        image_size: tuple[int, int],
        num_images: int,
        output_dir: Path,
    ) -> list[Path]:
        """Export calibration result to TOML and JSON files.

        Args:
            result: Calibration result from CalibrationEngine.
            serial: Camera serial number.
            image_size: Image size (width, height).
            num_images: Number of captures used for calibration.
            output_dir: Directory to save files.

        Returns:
            List of created file paths [toml_path, json_path].

        Raises:
            OSError: If file write fails.

        Processing flow:
            1. Build TOML string via _build_toml()
            2. Write TOML file (OSError raises immediately)
            3. Build JSON dict via _build_json_dict()
            4. Write JSON file (OSError raises immediately)
            If step 2 fails, step 3-4 are skipped.
            If step 4 fails, the TOML file from step 2 remains on disk.
        """
        toml_path = output_dir / f"cam{serial}_intrinsics.toml"
        json_path = output_dir / f"cam{serial}_intrinsics.json"

        toml_str = self._build_toml(result, serial, image_size)
        toml_path.write_text(toml_str, encoding="utf-8")
        logger.info("TOML written: %s", toml_path)

        json_dict = self._build_json_dict(result, serial, image_size, num_images)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_dict, f, indent=2)
        logger.info("JSON written: %s", json_path)

        return [toml_path, json_path]

    def _build_toml(
        self,
        result: CalibrationResult,
        serial: str,
        image_size: tuple[int, int],
    ) -> str:
        """Build Pose2Sim-compatible TOML string."""
        cam_name = f"cam{serial}"
        K = result.camera_matrix
        d = result.dist_coeffs.flatten()

        lines = []
        lines.append(f"[{cam_name}]")
        lines.append(f'name = "{cam_name}"')
        lines.append(f"size = [{image_size[0]:.1f}, {image_size[1]:.1f}]")
        lines.append(
            f"matrix = ["
            f"[{K[0,0]:.4f}, {K[0,1]:.4f}, {K[0,2]:.4f}], "
            f"[{K[1,0]:.4f}, {K[1,1]:.4f}, {K[1,2]:.4f}], "
            f"[{K[2,0]:.4f}, {K[2,1]:.4f}, {K[2,2]:.4f}]]"
        )
        lines.append(
            f"distortions = [{d[0]:.4f}, {d[1]:.4f}, {d[2]:.4f}, {d[3]:.4f}]"
        )
        lines.append("rotation = [0.0, 0.0, 0.0]")
        lines.append("translation = [0.0, 0.0, 0.0]")
        lines.append("fisheye = false")
        lines.append("")
        lines.append("[metadata]")
        lines.append("adjusted = false")
        lines.append(f"error = {result.rms_error:.4f}")
        lines.append("")

        return "\n".join(lines)

    def _build_json_dict(
        self,
        result: CalibrationResult,
        serial: str,
        image_size: tuple[int, int],
        num_images: int,
    ) -> dict:
        """Build JSON-serializable dict."""
        return {
            "serial": serial,
            "image_size": list(image_size),
            "camera_matrix": result.camera_matrix.tolist(),
            "dist_coeffs": result.dist_coeffs.flatten().tolist(),
            "rms_error": float(result.rms_error),
            "num_images": num_images,
        }
