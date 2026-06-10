"""Tests for BoardDetector (bug-009: collinear corner rejection).

共線配置のChArUcoコーナーは cv2.calibrateCamera() の内部初期推定
(initIntrinsicParams2D) をクラッシュさせるため、検出失敗として
扱われることを検証する。
"""

import cv2
import numpy
import pytest

from board_detector import BoardDetector


SQUARE_M = 0.034  # 34mm grid pitch (board coordinate unit)


def _obj_points(coords_2d: list[tuple[float, float]]) -> numpy.ndarray:
    """Build object_points array shape=(N,1,3) from 2D board coords."""
    pts = numpy.array(
        [[x * SQUARE_M, y * SQUARE_M, 0.0] for x, y in coords_2d],
        dtype=numpy.float32,
    )
    return pts.reshape(-1, 1, 3)


class TestIsCollinear:
    """_is_collinear() の直接単体テスト。"""

    def test_vertical_column_6_points_is_collinear(self):
        # 4x6格子の縦1列（x固定6点）— 実発生事例 capture_041 と同型
        pts = _obj_points([(4, y) for y in range(1, 7)])
        assert BoardDetector._is_collinear(pts) is True

    def test_horizontal_row_4_points_is_collinear(self):
        # 横1行（y固定4点）。検出経由では n<6 で先に弾かれるが判定単体で検証
        pts = _obj_points([(x, 3) for x in range(1, 5)])
        assert BoardDetector._is_collinear(pts) is True

    def test_diagonal_4_points_is_collinear(self):
        # 格子対角の斜め直線
        pts = _obj_points([(i, i) for i in range(1, 5)])
        assert BoardDetector._is_collinear(pts) is True

    def test_two_columns_6_points_is_not_collinear(self):
        # 非共線の最小ケース: 2列に分散した6点
        pts = _obj_points([(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3)])
        assert BoardDetector._is_collinear(pts) is False

    def test_full_grid_24_points_is_not_collinear(self):
        # 5x7ボードの内部コーナーグリッド全体 (4x6=24点)
        pts = _obj_points([(x, y) for x in range(1, 5) for y in range(1, 7)])
        assert BoardDetector._is_collinear(pts) is False

    def test_identical_points_is_collinear(self):
        # 全点同一座標（sv[0]=0 のゼロ除算ガード）。実際の検出では
        # ChArUco IDが一意のため発生しないが、防御として検証する
        pts = _obj_points([(2, 2)] * 6)
        assert BoardDetector._is_collinear(pts) is True


class TestDetectCharuco:
    """合成画像を使った detect() の統合テスト。"""

    @pytest.fixture
    def detector(self) -> BoardDetector:
        return BoardDetector(
            board_type="charuco",
            cols=5,
            rows=7,
            square_mm=34.0,
            marker_mm=22.0,
        )

    @pytest.fixture
    def board_image(self, detector: BoardDetector) -> numpy.ndarray:
        """フルボードの合成画像 (BGR)。"""
        gray = detector._board.generateImage((1000, 1400), marginSize=50)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    def test_full_board_detection_succeeds(self, detector, board_image):
        result = detector.detect(board_image)
        assert result.success is True
        assert result.num_corners == 24
        assert result.failure_reason == ""
        assert result.object_points is not None

    def test_single_column_detection_fails_as_collinear(
        self, detector, board_image
    ):
        # フルボード画像の左1列分だけを残し、他を白でマスクする。
        # 5x7ボード(1000x1400, margin=50)の1列はマージン込みで
        # x < 50 + 2*180 = 410 程度に収まる（square=180px）。
        # 内部コーナーの縦1列(6点)だけが検出される状態を作る。
        masked = board_image.copy()
        masked[:, 410:] = 255

        result = detector.detect(masked)

        assert result.success is False
        assert "collinear" in result.failure_reason
        assert result.num_corners == 6
        assert result.object_points is None
        # コーナー数不足ケースと同様、検出点とIDは保持される
        assert result.image_points is not None
        assert result.charuco_ids is not None

    def test_collinear_detection_does_not_crash_calibration_pipeline(
        self, detector, board_image
    ):
        """検出失敗扱いにより、共線ビューがキャリブレーション入力に
        混入しないこと（bug-009 のクラッシュ経路が塞がれること）。"""
        masked = board_image.copy()
        masked[:, 410:] = 255

        results = [detector.detect(board_image), detector.detect(masked)]
        valid = [r for r in results if r.success]

        assert len(valid) == 1  # 共線ビューは混入しない
