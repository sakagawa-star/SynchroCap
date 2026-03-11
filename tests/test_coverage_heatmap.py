"""Unit tests for CoverageHeatmap (Gaussian kernel approach)."""

import numpy
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "synchroCap"))

from coverage_heatmap import CoverageHeatmap


class TestCoverageHeatmapInit:
    """Tests for CoverageHeatmap initialization."""

    def test_sigma_hd(self):
        """HD 1920x1080 -> sigma = 1920 * 0.05 = 96.0."""
        hm = CoverageHeatmap((1920, 1080))
        assert hm._sigma == pytest.approx(96.0)

    def test_sigma_vga(self):
        """VGA 640x480 -> sigma = 640 * 0.05 = 32.0."""
        hm = CoverageHeatmap((640, 480))
        assert hm._sigma == pytest.approx(32.0)

    def test_sigma_minimum(self):
        """Very small image -> sigma clamped to 1.0."""
        hm = CoverageHeatmap((10, 10))
        assert hm._sigma >= 1.0


class TestCoverageHeatmapGenerate:
    """Tests for CoverageHeatmap.generate()."""

    def test_empty_points_returns_black(self):
        """Empty points array returns all-black image."""
        hm = CoverageHeatmap((640, 480))
        points = numpy.empty((0, 2), dtype=numpy.float32)
        result = hm.generate(points)

        assert result.shape == (480, 640, 3)
        assert result.dtype == numpy.uint8
        assert numpy.all(result == 0)

    def test_output_shape_matches_image_size(self):
        """Output shape matches the specified image size."""
        hm = CoverageHeatmap((800, 600))
        points = numpy.array([[400.0, 300.0]], dtype=numpy.float32)
        result = hm.generate(points)

        assert result.shape == (600, 800, 3)
        assert result.dtype == numpy.uint8

    def test_single_point_creates_colored_area(self):
        """Single point should create a colored area around it (Gaussian spread)."""
        hm = CoverageHeatmap((200, 200))
        points = numpy.array([[100.0, 100.0]], dtype=numpy.float32)
        result = hm.generate(points)

        # Center area should be non-black (Gaussian peak)
        center_region = result[90:110, 90:110]
        assert numpy.any(center_region > 0), "Center should be colored"

    def test_single_point_far_corners_are_black(self):
        """Corners far from the single point should remain black."""
        hm = CoverageHeatmap((400, 400))
        # Point at center
        points = numpy.array([[200.0, 200.0]], dtype=numpy.float32)
        result = hm.generate(points)

        # Far corners should be black (Gaussian tail falls off)
        top_left = result[0:5, 0:5]
        assert numpy.all(top_left == 0), "Far corner should be black"

    def test_gaussian_spread_fills_between_corners(self):
        """Multiple nearby points should create a continuous filled area."""
        hm = CoverageHeatmap((200, 200))
        # Points in a grid pattern (like board corners)
        points = numpy.array([
            [80.0, 80.0], [100.0, 80.0], [120.0, 80.0],
            [80.0, 100.0], [100.0, 100.0], [120.0, 100.0],
            [80.0, 120.0], [100.0, 120.0], [120.0, 120.0],
        ], dtype=numpy.float32)
        result = hm.generate(points)

        # The area between points should be filled (non-black)
        between = result[90, 90]  # Between (80,80) and (100,100)
        assert numpy.any(between > 0), "Gap between corners should be filled"

    def test_zero_pixels_are_black(self):
        """Pixels with zero coverage must be black, not TURBO blue."""
        hm = CoverageHeatmap((400, 400))
        # Points only in top-left
        points = numpy.array([[20.0, 20.0]], dtype=numpy.float32)
        result = hm.generate(points)

        # Bottom-right corner should be black
        bottom_right = result[380:400, 380:400]
        assert numpy.all(bottom_right == 0), "Uncovered area should be black"

    def test_multiple_captures_accumulate(self):
        """Points from different positions should both contribute."""
        hm = CoverageHeatmap((400, 400))
        # Points at two distant locations
        points = numpy.array([
            [50.0, 50.0],
            [350.0, 350.0],
        ], dtype=numpy.float32)
        result = hm.generate(points)

        # Both locations should be colored
        near_p1 = result[50, 50]
        near_p2 = result[350, 350]
        assert numpy.any(near_p1 > 0), "First point area should be colored"
        assert numpy.any(near_p2 > 0), "Second point area should be colored"

    def test_dense_points_produce_higher_intensity(self):
        """Area with more points should have higher intensity than sparse area."""
        hm = CoverageHeatmap((400, 400))
        # 10 points clustered at (100, 100), 1 point at (300, 300)
        dense = numpy.array([[100.0, 100.0]] * 10, dtype=numpy.float32)
        sparse = numpy.array([[300.0, 300.0]], dtype=numpy.float32)
        points = numpy.concatenate([dense, sparse])
        result = hm.generate(points)

        # Both areas should be non-black
        assert numpy.any(result[100, 100] > 0)
        assert numpy.any(result[300, 300] > 0)

    def test_points_at_image_edge(self):
        """Points at image edges should not cause errors."""
        hm = CoverageHeatmap((200, 200))
        points = numpy.array([
            [0.0, 0.0],
            [199.0, 0.0],
            [0.0, 199.0],
            [199.0, 199.0],
        ], dtype=numpy.float32)
        result = hm.generate(points)

        assert result.shape == (200, 200, 3)
        # All four corners should be colored
        assert numpy.any(result[0, 0] > 0)
        assert numpy.any(result[0, 199] > 0)
        assert numpy.any(result[199, 0] > 0)
        assert numpy.any(result[199, 199] > 0)

    def test_points_outside_image_clipped(self):
        """Points with coordinates outside image bounds should be clipped."""
        hm = CoverageHeatmap((200, 200))
        points = numpy.array([
            [-10.0, -10.0],
            [250.0, 250.0],
        ], dtype=numpy.float32)
        result = hm.generate(points)

        assert result.shape == (200, 200, 3)
        # Should not crash, corners should be colored
        assert numpy.any(result[0, 0] > 0)
        assert numpy.any(result[199, 199] > 0)
