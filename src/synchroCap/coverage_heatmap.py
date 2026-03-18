"""Coverage heatmap generator for camera calibration.

Uses Gaussian kernels around each detected corner to visualize
which image regions have calibration coverage as a continuous surface.
"""

from __future__ import annotations

import cv2
import numpy


class CoverageHeatmap:
    """Coverage heatmap generator.

    Generates a heatmap image from captured corner coordinates,
    showing which image regions have good calibration coverage.
    Each corner point is spread with a Gaussian kernel so that
    the board's covered area appears as a filled surface.

    Uses fixed-scale normalization: the heatmap saturates to red
    after SAT_CAPTURES overlapping captures at the same pixel.
    """

    SIGMA_RATIO: float = 0.05  # sigma = image_width * SIGMA_RATIO
    SAT_CAPTURES: int = 3  # Saturate to red after this many overlapping captures

    def __init__(self, image_size: tuple[int, int]) -> None:
        """Initialize.

        Args:
            image_size: Image size (width, height).
        """
        self._width, self._height = image_size
        self._sigma = max(1.0, self._width * self.SIGMA_RATIO)
        self._peak = self._compute_single_peak()
        self._saturation = self._peak * self.SAT_CAPTURES

    def _compute_single_peak(self) -> float:
        """Compute the peak value of a single-point Gaussian blur."""
        single = numpy.zeros((self._height, self._width), dtype=numpy.float32)
        cx, cy = self._width // 2, self._height // 2
        single[cy, cx] = 1.0
        blurred = cv2.GaussianBlur(single, (0, 0), self._sigma)
        return float(blurred.max())

    def generate(self, points: numpy.ndarray) -> numpy.ndarray:
        """Generate a heatmap image.

        Args:
            points: All corner coordinates. shape=(M,2), float32.
                    M=0 returns a black image.

        Returns:
            Heatmap image. shape=(height, width, 3), uint8, BGR.
        """
        if len(points) == 0:
            return numpy.zeros((self._height, self._width, 3), dtype=numpy.uint8)

        # Point map: place 1.0 at each corner position
        point_map = numpy.zeros((self._height, self._width), dtype=numpy.float32)
        xs = numpy.clip(points[:, 0].astype(int), 0, self._width - 1)
        ys = numpy.clip(points[:, 1].astype(int), 0, self._height - 1)
        numpy.add.at(point_map, (ys, xs), 1.0)

        # Gaussian blur to spread influence of each corner
        # ksize=0 lets OpenCV auto-compute kernel size from sigma
        blurred = cv2.GaussianBlur(point_map, (0, 0), self._sigma)

        # Fixed-scale normalization: saturate at SAT_CAPTURES overlaps
        normalized = numpy.clip(blurred / self._saturation * 255, 0, 255).astype(numpy.uint8)

        # Apply colormap
        colored = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)

        # Zero-value pixels -> black (no coverage = black)
        colored[normalized == 0] = [0, 0, 0]

        return colored
