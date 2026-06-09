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

    # --- feat-019: lens model selection ---

    def test_calibrate_wide_returns_8_coeffs(self):
        """lens_model='wide' should return (1, 8) dist_coeffs."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        result = self.engine.calibrate(obj_pts, img_pts, img_size, lens_model="wide")
        assert result.dist_coeffs.shape == (1, 8)

    def test_calibrate_normal_returns_5_coeffs(self):
        """lens_model='normal' should return (1, 5) dist_coeffs."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        result = self.engine.calibrate(obj_pts, img_pts, img_size, lens_model="normal")
        assert result.dist_coeffs.shape == (1, 5)

    def test_calibrate_default_is_wide(self):
        """Default lens_model should be 'wide' (8 coefficients)."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        result = self.engine.calibrate(obj_pts, img_pts, img_size)
        assert result.dist_coeffs.shape == (1, 8)

    def test_calibrate_invalid_lens_model_raises(self):
        """Invalid lens_model should raise ValueError."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        with pytest.raises(ValueError, match="Unknown lens_model"):
            self.engine.calibrate(obj_pts, img_pts, img_size, lens_model="fisheye")

    def test_calibrate_normal_accuracy(self):
        """lens_model='normal' should estimate camera matrix accurately."""
        obj_pts, img_pts, img_size, known_matrix = _generate_synthetic_data(
            num_images=20,
        )
        result = self.engine.calibrate(obj_pts, img_pts, img_size, lens_model="normal")
        assert result.rms_error < 1.0
        # fx, fy should be within 5% of known values
        assert abs(result.camera_matrix[0, 0] - known_matrix[0, 0]) < known_matrix[0, 0] * 0.05
        assert abs(result.camera_matrix[1, 1] - known_matrix[1, 1]) < known_matrix[1, 1] * 0.05
        # cx, cy should be within 10 pixels
        assert abs(result.camera_matrix[0, 2] - known_matrix[0, 2]) < 10.0
        assert abs(result.camera_matrix[1, 2] - known_matrix[1, 2]) < 10.0

    def test_export_normal_5_distortions(self, tmp_path):
        """Export of a 5-coefficient result should write 5-element arrays."""
        import json

        from calibration_exporter import CalibrationExporter

        result = CalibrationResult(
            rms_error=0.5,
            camera_matrix=numpy.eye(3, dtype=numpy.float64),
            dist_coeffs=numpy.zeros((1, 5), dtype=numpy.float64),
            rvecs=[],
            tvecs=[],
            per_image_errors=[],
        )
        exporter = CalibrationExporter()
        toml_path, json_path = exporter.export(
            result=result,
            serial="00000000",
            image_size=(640, 480),
            num_images=10,
            output_dir=tmp_path,
        )

        toml_text = toml_path.read_text(encoding="utf-8")
        dist_line = next(
            line for line in toml_text.splitlines()
            if line.startswith("distortions = ")
        )
        assert len(dist_line.split(",")) == 5

        with open(json_path, encoding="utf-8") as f:
            json_dict = json.load(f)
        assert len(json_dict["dist_coeffs"]) == 5

    # --- feat-020: spec-based intrinsic guess ---

    def test_calibrate_with_intrinsic_guess_returns_result(self):
        """Intrinsic guess with a near-known initial K returns a result."""
        obj_pts, img_pts, img_size, known = _generate_synthetic_data(num_images=20)
        result = self.engine.calibrate(
            obj_pts, img_pts, img_size,
            initial_camera_matrix=known.copy(),
        )
        assert isinstance(result, CalibrationResult)
        assert result.rms_error < 1.0

    def test_calibrate_intrinsic_guess_accuracy(self):
        """With an intrinsic guess, estimated K stays within 5% of known."""
        obj_pts, img_pts, img_size, known = _generate_synthetic_data(num_images=20)
        # Start 5% off so the optimizer must move toward the true values.
        initial = known.copy()
        initial[0, 0] *= 1.05
        initial[1, 1] *= 1.05
        result = self.engine.calibrate(
            obj_pts, img_pts, img_size,
            initial_camera_matrix=initial,
        )
        assert abs(result.camera_matrix[0, 0] - known[0, 0]) < known[0, 0] * 0.05
        assert abs(result.camera_matrix[1, 1] - known[1, 1]) < known[1, 1] * 0.05

    def test_calibrate_intrinsic_guess_not_fixed(self):
        """Initial K is a starting point only; the result must differ from it."""
        obj_pts, img_pts, img_size, known = _generate_synthetic_data(num_images=20)
        # Deliberately 5% off on every entry so the optimizer must move K.
        initial = known.copy()
        initial[0, 0] *= 1.05
        initial[1, 1] *= 1.05
        initial[0, 2] *= 1.05
        initial[1, 2] *= 1.05
        result = self.engine.calibrate(
            obj_pts, img_pts, img_size,
            initial_camera_matrix=initial,
        )
        assert not numpy.allclose(result.camera_matrix, initial)

    def test_calibrate_invalid_initial_matrix_shape_raises(self):
        """A non-(3,3) initial matrix should raise ValueError."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        bad = numpy.eye(2, dtype=numpy.float64)
        with pytest.raises(ValueError, match="initial_camera_matrix must be shape"):
            self.engine.calibrate(
                obj_pts, img_pts, img_size, initial_camera_matrix=bad,
            )

    def test_calibrate_default_no_guess(self):
        """Omitting initial_camera_matrix keeps the legacy behavior."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        result = self.engine.calibrate(obj_pts, img_pts, img_size)
        assert isinstance(result, CalibrationResult)

    def test_calibrate_guess_with_normal_lens(self):
        """Intrinsic guess composes with lens_model='normal' (5 coeffs)."""
        obj_pts, img_pts, img_size, known = _generate_synthetic_data(num_images=10)
        result = self.engine.calibrate(
            obj_pts, img_pts, img_size,
            lens_model="normal",
            initial_camera_matrix=known.copy(),
        )
        assert result.dist_coeffs.shape == (1, 5)

    def test_calibrate_guess_does_not_mutate_input(self):
        """The caller's initial matrix must be unchanged after calibration."""
        obj_pts, img_pts, img_size, known = _generate_synthetic_data(num_images=10)
        initial = known.copy()
        before = initial.copy()
        self.engine.calibrate(
            obj_pts, img_pts, img_size, initial_camera_matrix=initial,
        )
        assert numpy.array_equal(initial, before)

    def test_calibrate_fix_aspect_ratio_keeps_fx_eq_fy(self):
        """Fixing the aspect ratio (square init) keeps fx == fy."""
        obj_pts, img_pts, img_size, known = _generate_synthetic_data(num_images=20)
        # Square initial K (fx == fy), scaled 5% off the true value.
        initial = known.copy()
        initial[0, 0] = known[0, 0] * 1.05
        initial[1, 1] = known[0, 0] * 1.05  # keep fx == fy
        result = self.engine.calibrate(
            obj_pts, img_pts, img_size,
            initial_camera_matrix=initial,
            fix_aspect_ratio=True,
        )
        assert numpy.isclose(
            result.camera_matrix[0, 0], result.camera_matrix[1, 1]
        )
        assert result.rms_error < 1.0

    def test_calibrate_fix_aspect_ratio_requires_initial_matrix(self):
        """fix_aspect_ratio without an initial matrix should raise ValueError."""
        obj_pts, img_pts, img_size, _ = _generate_synthetic_data(num_images=10)
        with pytest.raises(ValueError, match="fix_aspect_ratio=True requires"):
            self.engine.calibrate(
                obj_pts, img_pts, img_size, fix_aspect_ratio=True,
            )

    def test_calibrate_fix_aspect_ratio_default_false(self):
        """Without the flag the ratio is free; with it the ratio is held.

        Judge by the fx/fy ratio, NOT RMS: a wrong fixed ratio can still
        produce RMS < 1.0 on synthetic data, so RMS cannot distinguish the
        two cases.
        """
        obj_pts, img_pts, img_size, known = _generate_synthetic_data(num_images=20)
        # Non-square initial K: fx = 1.1 * fy.
        initial = known.copy()
        initial[1, 1] = known[1, 1]          # fy = 800
        initial[0, 0] = known[1, 1] * 1.1    # fx = 880 -> ratio 1.1

        free = self.engine.calibrate(
            obj_pts, img_pts, img_size,
            initial_camera_matrix=initial.copy(),
            fix_aspect_ratio=False,
        )
        fixed = self.engine.calibrate(
            obj_pts, img_pts, img_size,
            initial_camera_matrix=initial.copy(),
            fix_aspect_ratio=True,
        )
        ratio_free = free.camera_matrix[0, 0] / free.camera_matrix[1, 1]
        ratio_fixed = fixed.camera_matrix[0, 0] / fixed.camera_matrix[1, 1]
        # Free: optimizer recovers the true square ratio (~1.0).
        assert abs(ratio_free - 1.0) < 0.02
        # Fixed: the initial ratio (1.1) is preserved.
        assert abs(ratio_fixed - 1.1) < 0.01


class TestBuildInitialCameraMatrix:
    """Tests for offline_calibration._build_initial_camera_matrix (feat-020)."""

    def test_build_initial_camera_matrix(self):
        """K is built from spec: fx=fy=focal/pitch, cx=W/2, cy=H/2."""
        sys.path.insert(
            0, str(Path(__file__).resolve().parent.parent / "tools")
        )
        from offline_calibration import _build_initial_camera_matrix

        K = _build_initial_camera_matrix(3.5, 0.003, (1920, 1080))
        assert K.shape == (3, 3)
        assert numpy.isclose(K[0, 0], 3.5 / 0.003)   # fx ~= 1166.67
        assert numpy.isclose(K[1, 1], 3.5 / 0.003)   # fy ~= 1166.67
        assert numpy.isclose(K[0, 0], K[1, 1])       # square -> ratio 1.0 (FR-004)
        assert numpy.isclose(K[0, 2], 960.0)         # cx = W/2
        assert numpy.isclose(K[1, 2], 540.0)         # cy = H/2


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
