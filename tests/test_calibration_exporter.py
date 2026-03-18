"""Tests for calibration_exporter.py."""

import json
import sys
from pathlib import Path

import numpy
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "synchroCap"))

from calibration_engine import CalibrationResult
from calibration_exporter import CalibrationExporter


@pytest.fixture
def sample_result() -> CalibrationResult:
    """Create a synthetic CalibrationResult for testing."""
    return CalibrationResult(
        rms_error=0.3220,
        camera_matrix=numpy.array([
            [800.1234, 0.0, 320.5678],
            [0.0, 800.9876, 240.4321],
            [0.0, 0.0, 1.0],
        ], dtype=numpy.float64),
        dist_coeffs=numpy.array(
            [[-0.0812, 0.1243, -0.0003, 0.0001, 0.0056]],
            dtype=numpy.float64,
        ),
        rvecs=[numpy.zeros((3, 1))],
        tvecs=[numpy.zeros((3, 1))],
        per_image_errors=[0.32],
    )


@pytest.fixture
def exporter() -> CalibrationExporter:
    return CalibrationExporter()


SERIAL = "49710379"
IMAGE_SIZE = (1920, 1080)
NUM_IMAGES = 10


# ── TOML generation tests ──


class TestBuildToml:
    """Tests for _build_toml()."""

    def test_contains_camera_section(self, exporter, sample_result):
        toml_str = exporter._build_toml(sample_result, SERIAL, IMAGE_SIZE)
        assert f"[cam_{SERIAL}]" in toml_str

    def test_name_matches_section(self, exporter, sample_result):
        toml_str = exporter._build_toml(sample_result, SERIAL, IMAGE_SIZE)
        assert f'name = "cam_{SERIAL}"' in toml_str

    def test_size_format(self, exporter, sample_result):
        toml_str = exporter._build_toml(sample_result, SERIAL, IMAGE_SIZE)
        assert "size = [1920.0, 1080.0]" in toml_str

    def test_matrix_3x3(self, exporter, sample_result):
        toml_str = exporter._build_toml(sample_result, SERIAL, IMAGE_SIZE)
        assert "matrix = [[800.1234, 0.0000, 320.5678]," in toml_str
        assert "[0.0000, 800.9876, 240.4321]," in toml_str
        assert "[0.0000, 0.0000, 1.0000]]" in toml_str

    def test_distortions_4_elements(self, exporter, sample_result):
        toml_str = exporter._build_toml(sample_result, SERIAL, IMAGE_SIZE)
        assert "distortions = [-0.0812, 0.1243, -0.0003, 0.0001]" in toml_str
        # k3 (0.0056) should NOT be present in distortions
        assert "0.0056" not in toml_str

    def test_rotation_zero(self, exporter, sample_result):
        toml_str = exporter._build_toml(sample_result, SERIAL, IMAGE_SIZE)
        assert "rotation = [0.0, 0.0, 0.0]" in toml_str

    def test_translation_zero(self, exporter, sample_result):
        toml_str = exporter._build_toml(sample_result, SERIAL, IMAGE_SIZE)
        assert "translation = [0.0, 0.0, 0.0]" in toml_str

    def test_fisheye_false(self, exporter, sample_result):
        toml_str = exporter._build_toml(sample_result, SERIAL, IMAGE_SIZE)
        assert "fisheye = false" in toml_str

    def test_metadata_section(self, exporter, sample_result):
        toml_str = exporter._build_toml(sample_result, SERIAL, IMAGE_SIZE)
        assert "[metadata]" in toml_str
        assert "adjusted = false" in toml_str
        assert "error = 0.3220" in toml_str


# ── JSON generation tests ──


class TestBuildJsonDict:
    """Tests for _build_json_dict()."""

    def test_json_parseable(self, exporter, sample_result):
        d = exporter._build_json_dict(sample_result, SERIAL, IMAGE_SIZE, NUM_IMAGES)
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed is not None

    def test_serial(self, exporter, sample_result):
        d = exporter._build_json_dict(sample_result, SERIAL, IMAGE_SIZE, NUM_IMAGES)
        assert d["serial"] == SERIAL

    def test_image_size(self, exporter, sample_result):
        d = exporter._build_json_dict(sample_result, SERIAL, IMAGE_SIZE, NUM_IMAGES)
        assert d["image_size"] == [1920, 1080]

    def test_camera_matrix_3x3(self, exporter, sample_result):
        d = exporter._build_json_dict(sample_result, SERIAL, IMAGE_SIZE, NUM_IMAGES)
        matrix = d["camera_matrix"]
        assert len(matrix) == 3
        assert all(len(row) == 3 for row in matrix)
        assert matrix[0][0] == pytest.approx(800.1234)
        assert matrix[1][1] == pytest.approx(800.9876)

    def test_dist_coeffs_5_elements(self, exporter, sample_result):
        d = exporter._build_json_dict(sample_result, SERIAL, IMAGE_SIZE, NUM_IMAGES)
        assert len(d["dist_coeffs"]) == 5
        assert d["dist_coeffs"][4] == pytest.approx(0.0056)

    def test_rms_error(self, exporter, sample_result):
        d = exporter._build_json_dict(sample_result, SERIAL, IMAGE_SIZE, NUM_IMAGES)
        assert d["rms_error"] == pytest.approx(0.3220)

    def test_num_images(self, exporter, sample_result):
        d = exporter._build_json_dict(sample_result, SERIAL, IMAGE_SIZE, NUM_IMAGES)
        assert d["num_images"] == NUM_IMAGES


# ── File export tests ──


class TestExport:
    """Tests for export()."""

    def test_creates_two_files(self, exporter, sample_result, tmp_path):
        paths = exporter.export(
            sample_result, SERIAL, IMAGE_SIZE, NUM_IMAGES, tmp_path,
        )
        assert len(paths) == 2
        assert all(p.exists() for p in paths)

    def test_file_names(self, exporter, sample_result, tmp_path):
        paths = exporter.export(
            sample_result, SERIAL, IMAGE_SIZE, NUM_IMAGES, tmp_path,
        )
        assert paths[0].name == f"{SERIAL}_intrinsics.toml"
        assert paths[1].name == f"{SERIAL}_intrinsics.json"

    def test_toml_file_content(self, exporter, sample_result, tmp_path):
        paths = exporter.export(
            sample_result, SERIAL, IMAGE_SIZE, NUM_IMAGES, tmp_path,
        )
        content = paths[0].read_text(encoding="utf-8")
        assert f"[cam_{SERIAL}]" in content
        assert "[metadata]" in content

    def test_json_file_parseable(self, exporter, sample_result, tmp_path):
        paths = exporter.export(
            sample_result, SERIAL, IMAGE_SIZE, NUM_IMAGES, tmp_path,
        )
        with open(paths[1], encoding="utf-8") as f:
            data = json.load(f)
        assert data["serial"] == SERIAL
        assert data["num_images"] == NUM_IMAGES

    def test_nonexistent_directory_raises(self, exporter, sample_result, tmp_path):
        bad_dir = tmp_path / "nonexistent"
        with pytest.raises(OSError):
            exporter.export(
                sample_result, SERIAL, IMAGE_SIZE, NUM_IMAGES, bad_dir,
            )

    def test_overwrite_existing(self, exporter, sample_result, tmp_path):
        """Existing files are silently overwritten."""
        exporter.export(sample_result, SERIAL, IMAGE_SIZE, NUM_IMAGES, tmp_path)
        # Export again — should not raise
        paths = exporter.export(
            sample_result, SERIAL, IMAGE_SIZE, NUM_IMAGES, tmp_path,
        )
        assert all(p.exists() for p in paths)
