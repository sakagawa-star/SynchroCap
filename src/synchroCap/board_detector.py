"""Board detection engine for camera calibration.

Supports ChArUco and checkerboard detection with overlay drawing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import cv2
import numpy

logger = logging.getLogger(__name__)


@dataclass
class DetectionResult:
    success: bool
    image_points: numpy.ndarray | None  # shape=(N,1,2), float32
    object_points: numpy.ndarray | None  # shape=(N,1,3), float32
    charuco_ids: numpy.ndarray | None  # shape=(N,1), int32 (ChArUco only)
    num_corners: int
    failure_reason: str  # empty string on success


class BoardDetector:
    """ChArUco / checkerboard detection engine."""

    def __init__(
        self,
        board_type: str = "charuco",
        cols: int = 5,
        rows: int = 7,
        square_mm: float = 30.0,
        marker_mm: float = 22.0,
    ) -> None:
        self._board_type = board_type
        self._cols = cols
        self._rows = rows
        self._square_mm = square_mm
        self._marker_mm = marker_mm

        # Internal detector objects (created in _init_detector)
        self._charuco_detector: cv2.aruco.CharucoDetector | None = None
        self._board: cv2.aruco.CharucoBoard | None = None

        self._init_detector()

    def _init_detector(self) -> None:
        """Initialize the internal detector based on current settings."""
        self._charuco_detector = None
        self._board = None

        if self._board_type == "charuco":
            square_size_m = self._square_mm / 1000.0
            marker_size_m = self._marker_mm / 1000.0
            dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
            self._board = cv2.aruco.CharucoBoard(
                (self._cols, self._rows), square_size_m, marker_size_m, dictionary
            )
            detector_params = cv2.aruco.CharucoParameters()
            self._charuco_detector = cv2.aruco.CharucoDetector(
                self._board, detector_params
            )

        logger.info(
            "Board config: %s %dx%d square=%.1fmm marker=%.1fmm",
            self._board_type,
            self._cols,
            self._rows,
            self._square_mm,
            self._marker_mm,
        )

    def detect(self, frame_bgr: numpy.ndarray) -> DetectionResult:
        """Detect board in a BGR frame."""
        if frame_bgr.size == 0:
            return DetectionResult(
                success=False,
                image_points=None,
                object_points=None,
                charuco_ids=None,
                num_corners=0,
                failure_reason="Empty frame",
            )

        t0 = time.monotonic()
        try:
            if self._board_type == "charuco":
                result = self._detect_charuco(frame_bgr)
            else:
                result = self._detect_checkerboard(frame_bgr)
        except cv2.error as e:
            reason = f"{self._board_type} detection error"
            logger.warning("%s: %s", reason, e)
            return DetectionResult(
                success=False,
                image_points=None,
                object_points=None,
                charuco_ids=None,
                num_corners=0,
                failure_reason=reason,
            )

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.debug(
            "Detection: %d corners in %.1fms", result.num_corners, elapsed_ms
        )
        return result

    def _detect_charuco(self, frame_bgr: numpy.ndarray) -> DetectionResult:
        """ChArUco board detection using CharucoDetector API."""
        try:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        except cv2.error as e:
            logger.warning("Gray conversion failed: %s", e)
            return DetectionResult(
                success=False,
                image_points=None,
                object_points=None,
                charuco_ids=None,
                num_corners=0,
                failure_reason="Gray conversion failed",
            )

        charuco_corners, charuco_ids, marker_corners, marker_ids = (
            self._charuco_detector.detectBoard(gray)
        )

        if charuco_corners is None or len(charuco_corners) == 0:
            return DetectionResult(
                success=False,
                image_points=None,
                object_points=None,
                charuco_ids=None,
                num_corners=0,
                failure_reason="No board detected",
            )

        n = len(charuco_corners)
        if n < 6:
            return DetectionResult(
                success=False,
                image_points=charuco_corners,
                object_points=None,
                charuco_ids=charuco_ids,
                num_corners=n,
                failure_reason=f"Detected only {n} corners (minimum: 6)",
            )

        # Extract object points for detected corners
        all_obj_points = self._board.getChessboardCorners()  # shape=(total, 3)
        obj_points = all_obj_points[charuco_ids.flatten()]  # shape=(N, 3)
        obj_points = obj_points.reshape(-1, 1, 3)

        return DetectionResult(
            success=True,
            image_points=charuco_corners,
            object_points=obj_points,
            charuco_ids=charuco_ids,
            num_corners=n,
            failure_reason="",
        )

    def _detect_checkerboard(self, frame_bgr: numpy.ndarray) -> DetectionResult:
        """Checkerboard detection using findChessboardCorners."""
        try:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        except cv2.error as e:
            logger.warning("Gray conversion failed: %s", e)
            return DetectionResult(
                success=False,
                image_points=None,
                object_points=None,
                charuco_ids=None,
                num_corners=0,
                failure_reason="Gray conversion failed",
            )

        pattern_size = (self._cols - 1, self._rows - 1)
        flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
        ret, corners = cv2.findChessboardCorners(gray, pattern_size, flags=flags)

        if not ret or corners is None:
            return DetectionResult(
                success=False,
                image_points=None,
                object_points=None,
                charuco_ids=None,
                num_corners=0,
                failure_reason="Checkerboard not detected",
            )

        # Sub-pixel refinement
        criteria = (
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER,
            30,
            0.001,
        )
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)

        # Generate object points
        n_inner = (self._cols - 1) * (self._rows - 1)
        square_size_m = self._square_mm / 1000.0
        objp = numpy.zeros((n_inner, 1, 3), numpy.float32)
        objp[:, 0, :2] = (
            numpy.mgrid[0 : self._cols - 1, 0 : self._rows - 1]
            .T.reshape(-1, 2)
            * square_size_m
        )

        return DetectionResult(
            success=True,
            image_points=corners,
            object_points=objp,
            charuco_ids=None,
            num_corners=len(corners),
            failure_reason="",
        )

    def draw_overlay(
        self, frame_bgr: numpy.ndarray, result: DetectionResult
    ) -> numpy.ndarray:
        """Draw detection result on a copy of the frame. Original is not modified."""
        output = frame_bgr.copy()
        if not result.success:
            return output

        if self._board_type == "charuco":
            cv2.aruco.drawDetectedCornersCharuco(
                output, result.image_points, result.charuco_ids, (0, 255, 0)
            )
        else:
            cv2.drawChessboardCorners(
                output,
                (self._cols - 1, self._rows - 1),
                result.image_points,
                True,
            )
        return output

    def reconfigure(
        self,
        board_type: str,
        cols: int,
        rows: int,
        square_mm: float,
        marker_mm: float,
    ) -> None:
        """Reconfigure board settings and reinitialize the detector."""
        self._board_type = board_type
        self._cols = cols
        self._rows = rows
        self._square_mm = square_mm
        self._marker_mm = marker_mm
        self._init_detector()

    @property
    def max_corners(self) -> int:
        """Maximum number of corners for the current board configuration."""
        return (self._cols - 1) * (self._rows - 1)
