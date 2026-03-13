"""Camera calibration calculation engine.

Wraps cv2.calibrateCamera() and provides per-image
reprojection error calculation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy

logger = logging.getLogger(__name__)


@dataclass
class CalibrationResult:
    """Calibration calculation result."""
    rms_error: float                     # RMS reprojection error (pixels)
    camera_matrix: numpy.ndarray         # shape=(3,3), float64
    dist_coeffs: numpy.ndarray           # shape=(1,5), float64
    rvecs: list[numpy.ndarray]           # per-image rotation vectors
    tvecs: list[numpy.ndarray]           # per-image translation vectors
    per_image_errors: list[float]        # per-image RMS reprojection error (pixels)


class CalibrationEngine:
    """Camera calibration calculation engine.

    Wraps cv2.calibrateCamera() and provides per-image
    reprojection error calculation.
    """

    MIN_CAPTURES: int = 4

    def calibrate(
        self,
        object_points_list: list[numpy.ndarray],
        image_points_list: list[numpy.ndarray],
        image_size: tuple[int, int],
    ) -> CalibrationResult:
        """Run camera calibration.

        Args:
            object_points_list: Per-capture object points.
                Each element: shape=(N,1,3), float32.
            image_points_list: Per-capture image points.
                Each element: shape=(N,1,2), float32.
            image_size: Image size (width, height).

        Returns:
            CalibrationResult with all calibration parameters.

        Raises:
            ValueError: If len(object_points_list) < MIN_CAPTURES.
            cv2.error: If cv2.calibrateCamera() fails.
        """
        if len(object_points_list) < self.MIN_CAPTURES:
            raise ValueError(
                f"At least {self.MIN_CAPTURES} captures required, "
                f"got {len(object_points_list)}"
            )

        rms, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
            object_points_list,
            image_points_list,
            image_size,
            None,
            None,
        )

        per_image_errors = self._compute_per_image_errors(
            object_points_list,
            image_points_list,
            camera_matrix,
            dist_coeffs,
            rvecs,
            tvecs,
        )

        logger.info(
            "Calibration done: RMS=%.4f px, %d images",
            rms, len(object_points_list),
        )

        return CalibrationResult(
            rms_error=rms,
            camera_matrix=camera_matrix,
            dist_coeffs=dist_coeffs,
            rvecs=list(rvecs),
            tvecs=list(tvecs),
            per_image_errors=per_image_errors,
        )

    def _compute_per_image_errors(
        self,
        object_points_list: list[numpy.ndarray],
        image_points_list: list[numpy.ndarray],
        camera_matrix: numpy.ndarray,
        dist_coeffs: numpy.ndarray,
        rvecs: list[numpy.ndarray],
        tvecs: list[numpy.ndarray],
    ) -> list[float]:
        """Compute per-image RMS reprojection error.

        For each capture, project object_points back to image plane
        using the calibration result and compute RMS distance to
        detected image_points.
        """
        errors = []
        for i in range(len(object_points_list)):
            projected, _ = cv2.projectPoints(
                object_points_list[i],
                rvecs[i],
                tvecs[i],
                camera_matrix,
                dist_coeffs,
            )
            diff = image_points_list[i].reshape(-1, 2) - projected.reshape(-1, 2)
            # diff shape=(N,2): x差分とy差分。diff**2 を全要素平均 → sqrt は
            # 各点のユークリッド距離 sqrt(dx^2+dy^2) のRMSと数学的に等価。
            rms = float(numpy.sqrt(numpy.mean(diff ** 2)))
            errors.append(rms)
        return errors
