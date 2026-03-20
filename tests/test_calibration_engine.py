"""Tests for calibration_engine.py."""

import sys
from pathlib import Path

import cv2
import numpy
import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "synchroCap"))

from calibration_engine import CalibrationEngine, CalibrationResult


def _generate_synthetic_data(
    num_images: int = 10,
    board_cols: int = 5,
    board_rows: int = 7,
    square_size: float = 0.03,
) -> tuple[
    list[numpy.ndarray],
    list[numpy.ndarray],
    tuple[int, int],
    numpy.ndarray,
]:
    """Generate synthetic calibration data with known camera parameters.

    Returns:
        (object_points_list, image_points_list, image_size, known_camera_matrix)
    """
    image_size = (640, 480)

    known_camera_matrix = numpy.array([
        [800.0,   0.0, 320.0],
        [  0.0, 800.0, 240.0],
        [  0.0,   0.0,   1.0],
    ], dtype=numpy.float64)

    known_dist_coeffs = numpy.zeros((1, 5), dtype=numpy.float64)

    # Generate object points for a checkerboard pattern
    inner_cols = board_cols - 1
    inner_rows = board_rows - 1
    objp = numpy.zeros((inner_cols * inner_rows, 1, 3), numpy.float32)
    objp[:, 0, :2] = (
        numpy.mgrid[0:inner_cols, 0:inner_rows]
        .T.reshape(-1, 2)
        * square_size
    )

    object_points_list = []
    image_points_list = []

    rng = numpy.random.RandomState(42)

    for _ in range(num_images):
        # Random rotation (small angles)
        rvec = rng.uniform(-0.5, 0.5, (3, 1)).astype(numpy.float64)
        # Translation: board in front of camera
        tvec = numpy.array([
            [rng.uniform(-0.05, 0.05)],
            [rng.uniform(-0.05, 0.05)],
            [rng.uniform(0.3, 0.6)],
        ], dtype=numpy.float64)

        projected, _ = cv2.projectPoints(
            objp, rvec, tvec, known_camera_matrix, known_dist_coeffs,
        )

        # Check all points are within image bounds
        pts = projected.reshape(-1, 2)
        if (pts[:, 0].min() < 0 or pts[:, 0].max() >= image_size[0]
                or pts[:, 1].min() < 0 or pts[:, 1].max() >= image_size[1]):
            continue

        object_points_list.append(objp.copy())
        image_points_list.append(projected.astype(numpy.float32))

    return object_points_list, image_points_list, image_size, known_camera_matrix


class TestCalibrationEngine:
    """Tests for CalibrationEngine."""

    def setup_method(self):
        self.engine = CalibrationEngine()

    def test_calibrate_returns_result(self):
        """Calibration with synthetic data returns a CalibrationResult."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        result = self.engine.calibrate(obj_pts, img_pts, img_size)
        assert isinstance(result, CalibrationResult)

    def test_rms_error_reasonable(self):
        """RMS error should be small for perfect synthetic data."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        result = self.engine.calibrate(obj_pts, img_pts, img_size)
        assert result.rms_error < 1.0

    def test_camera_matrix_shape(self):
        """Camera matrix should be 3x3."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        result = self.engine.calibrate(obj_pts, img_pts, img_size)
        assert result.camera_matrix.shape == (3, 3)

    def test_dist_coeffs_shape(self):
        """Distortion coefficients should be (1, 8) with rational model."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        result = self.engine.calibrate(obj_pts, img_pts, img_size)
        assert result.dist_coeffs.shape == (1, 8)

    def test_per_image_errors_length(self):
        """per_image_errors list length should match capture count."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        result = self.engine.calibrate(obj_pts, img_pts, img_size)
        assert len(result.per_image_errors) == len(obj_pts)

    def test_per_image_errors_non_negative(self):
        """All per-image errors should be non-negative."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        result = self.engine.calibrate(obj_pts, img_pts, img_size)
        for err in result.per_image_errors:
            assert err >= 0.0
            assert isinstance(err, float)

    def test_camera_matrix_close_to_known(self):
        """Estimated camera matrix should be close to the known values."""
        obj_pts, img_pts, img_size, known_matrix = _generate_synthetic_data(
            num_images=20,
        )
        result = self.engine.calibrate(obj_pts, img_pts, img_size)
        # fx, fy should be within 5% of known values
        assert abs(result.camera_matrix[0, 0] - known_matrix[0, 0]) < known_matrix[0, 0] * 0.05
        assert abs(result.camera_matrix[1, 1] - known_matrix[1, 1]) < known_matrix[1, 1] * 0.05
        # cx, cy should be within 10 pixels
        assert abs(result.camera_matrix[0, 2] - known_matrix[0, 2]) < 10.0
        assert abs(result.camera_matrix[1, 2] - known_matrix[1, 2]) < 10.0

    def test_rvecs_tvecs_length(self):
        """rvecs and tvecs should match capture count."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        result = self.engine.calibrate(obj_pts, img_pts, img_size)
        assert len(result.rvecs) == len(obj_pts)
        assert len(result.tvecs) == len(obj_pts)

    def test_min_captures_raises_valueerror(self):
        """Should raise ValueError when captures < MIN_CAPTURES."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        with pytest.raises(ValueError, match="At least 4 captures required"):
            self.engine.calibrate(obj_pts[:3], img_pts[:3], img_size)

    def test_empty_list_raises_valueerror(self):
        """Should raise ValueError for empty capture list."""
        with pytest.raises(ValueError, match="At least 4 captures required"):
            self.engine.calibrate([], [], (640, 480))

    def test_min_captures_exactly_four(self):
        """Should succeed with exactly MIN_CAPTURES (4) images."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        result = self.engine.calibrate(obj_pts[:4], img_pts[:4], img_size)
        assert isinstance(result, CalibrationResult)
        assert len(result.per_image_errors) == 4

    def test_min_captures_constant(self):
        """MIN_CAPTURES should be 4."""
        assert CalibrationEngine.MIN_CAPTURES == 4


_REAL_IMAGE_DIR = Path(__file__).resolve().parent.parent / "src" / "synchroCap" / "captures" / "20260318-141544" / "intrinsics" / "cam05520125"


@pytest.mark.skipif(
    not _REAL_IMAGE_DIR.is_dir(),
    reason="Test images not available",
)
class TestWideAngleCalibration:
    """Integration test with real wide-angle lens images (LM3NC1M 3.5mm)."""

    def setup_method(self):
        from board_detector import BoardDetector
        self.engine = CalibrationEngine()
        self.detector = BoardDetector()

    def test_wide_angle_calibration(self):
        """Calibrate with 37 real wide-angle images, RMS < 1.0px."""
        images = sorted(_REAL_IMAGE_DIR.glob("*.png"))
        assert len(images) > 0

        obj_list = []
        img_list = []
        image_size = None

        for img_path in images:
            bgr = cv2.imread(str(img_path))
            if bgr is None:
                continue
            if image_size is None:
                h, w = bgr.shape[:2]
                image_size = (w, h)

            result = self.detector.detect(bgr)
            if result.success:
                obj_list.append(result.object_points)
                img_list.append(result.image_points)

        assert len(obj_list) >= CalibrationEngine.MIN_CAPTURES, (
            f"Only {len(obj_list)} detections from {len(images)} images"
        )

        cal = self.engine.calibrate(obj_list, img_list, image_size)

        assert cal.rms_error < 1.0, f"RMS too high: {cal.rms_error:.4f}"
        assert cal.dist_coeffs.shape == (1, 8)
        assert cal.camera_matrix.shape == (3, 3)
