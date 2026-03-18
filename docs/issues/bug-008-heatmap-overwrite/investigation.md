# 不具合調査・修正計画: bug-008

## イテレーション1 (2026-03-18)

### 1.1 不具合の特定

- **対応する要求ID**: feat-010 FR-001（ヒートマップ生成）
- **対応する設計セクション**: feat-010 機能設計書 4.1（ヒートマップ生成）
- **現在の動作**: キャプチャ追加後にヒートマップ全体が再正規化され、既存の高密度（赤色）領域が相対的に薄い色に変化する。例えば、左半分で5回キャプチャ→左が赤色。右半分で1回キャプチャ→左の赤が薄くなる
- **再現手順**:
  1. Calibrationタブでカメラを選択しライブビューを開始
  2. 画像の左半分でキャプチャを数回取得 → 左半分が赤色になる
  3. 画像の右半分でキャプチャを1回取得 → 左半分の赤色が薄い色に変わる
- **期待する動作**: feat-010 要求仕様書 FR-001 受け入れ基準「コーナーが多い領域ほど暖色（赤）、少ない領域ほど寒色（青）で表示される」。キャプチャ追加後も高密度領域は赤のまま維持されるべき

### 1.2 原因分析

- **原因箇所**: `src/synchroCap/coverage_heatmap.py` L57-59 `generate()` メソッドの正規化処理
- **原因の説明**: 正規化で `blurred.max()` を分母として `0-255` にスケーリングしている。キャプチャが追加されるたびに全ポイントを再集計し `max_val` が変化する。特定領域にキャプチャが集中すると `max_val` が大きくなり、他の領域のピクセル値が相対的に小さくなる。結果として、以前は赤色（255近い）だった領域が薄い色（低い値）に変わる
- **根本原因**: `max_val` による相対正規化が原因。キャプチャが追加されるたびに全体のスケールが変動する
- **該当コード**:
  ```python
  max_val = blurred.max()
  if max_val > 0:
      normalized = (blurred / max_val * 255).astype(numpy.uint8)
  ```

### 1.3 修正内容

- **変更対象ファイル**: `src/synchroCap/coverage_heatmap.py`
  - `generate()` メソッドの正規化を、相対正規化（`max_val` 除算）から固定スケール正規化に変更する
  - 固定スケール: ガウシアンカーネル1回分のピーク値を基準とする。1つのコーナー点にガウシアンブラーを適用した場合のピーク値を計算し、その値の N 倍を「飽和閾値」として使用する。N はキャプチャ回数の目安で、閾値を超えた値は 255 にクリップする
  - 具体的な計算: 2Dガウシアンのピーク値は `1.0 / (2 * pi * sigma^2)` だが、`cv2.GaussianBlur` は入力の 1.0 をカーネル全体に分散するため、ピーク値はカーネルの中央値。実測が確実なため、初期化時に1点のガウシアンブラーを実行してピーク値を取得する
  - 飽和キャプチャ数 `SAT_CAPTURES` を定数として定義する。同一ピクセルに対してガウシアンカーネルのピーク値が `SAT_CAPTURES` 回分加算された場合に正規化値が255に到達する。値: 3。選定根拠: ChArUcoボードの一般的なキャプチャ枚数は20〜50枚。画像全域を均一にカバーする場合、1領域あたり3〜5回のカバーが目安。3回で飽和とすることで、十分にカバーされた領域を早期に赤色で表示し、未カバー領域（黒）との対比を明確にする。4回以上重なった領域も255にクリップされるため区別できなくなるが、ヒートマップの目的は「次にボードをどこに置くべきか」の可視化であり、既に十分カバーされた領域の精密な密度比較は不要

変更後のコード:
```python
class CoverageHeatmap:
    SIGMA_RATIO: float = 0.05
    SAT_CAPTURES: int = 3  # Saturate to red after this many overlapping captures

    def __init__(self, image_size: tuple[int, int]) -> None:
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
        if len(points) == 0:
            return numpy.zeros((self._height, self._width, 3), dtype=numpy.uint8)

        point_map = numpy.zeros((self._height, self._width), dtype=numpy.float32)
        xs = numpy.clip(points[:, 0].astype(int), 0, self._width - 1)
        ys = numpy.clip(points[:, 1].astype(int), 0, self._height - 1)
        numpy.add.at(point_map, (ys, xs), 1.0)

        blurred = cv2.GaussianBlur(point_map, (0, 0), self._sigma)

        # Fixed-scale normalization: saturate at SAT_CAPTURES overlaps
        normalized = numpy.clip(blurred / self._saturation * 255, 0, 255).astype(numpy.uint8)

        colored = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)
        colored[normalized == 0] = [0, 0, 0]

        return colored
```

- **変更しないファイル**:
  - `ui_calibration.py`: ヒートマップの呼び出し方は変更なし
  - `calibration_exporter.py`: 無関係
- **修正が設計書に沿っているか**: 設計書の「累積マップの最大値で正規化」を「固定スケールで正規化」に変更する。設計書の変更が必要

### 設計書の変更案

feat-010 機能設計書 4.1 の正規化処理を以下のように変更:
- 「累積マップの最大値で正規化し、0〜255の範囲にスケーリングする」を「固定スケール（ガウシアンカーネル1回分のピーク値 × `SAT_CAPTURES`）で正規化し、0〜255の範囲にクリップする。`SAT_CAPTURES` 回以上重なった領域は赤色（255）に飽和する」に変更

feat-010 要求仕様書 FR-001 処理ステップ4を以下に変更:
- 「累積マップの最大値で正規化し、0〜255の範囲にスケーリングする（最大値が0の場合は全ピクセル0とする）」を「ガウシアンカーネル1回分のピーク値を初期化時に計算する。累積マップをピーク値×SAT_CAPTURES（=3）で除算し、0〜255にクリップする。SAT_CAPTURES回以上コーナーが重なった領域は赤色に飽和する」に変更

### 1.4 影響範囲

- **他の機能への影響**: なし。`CoverageHeatmap` の公開インターフェース（`__init__` の引数、`generate` の引数・返り値の型）は変更なし。内部実装（正規化ロジック、初期化時の前計算）のみ変更
- **リグレッションリスク**: ヒートマップの色分布が変わる。以前は相対的な色分布だったが、修正後は絶対的な色分布になる。低密度領域が以前より暗く表示される（意図通り）。画像端のコーナーはガウシアンカーネルの打ち切りによりピーク値が中央より低くなる。端の領域ではSAT_CAPTURES回で飽和に到達しない場合がある。これは既存の相対正規化方式でも同じ特性であり、新たなリグレッションではない
- **既存テストへの影響**: `tests/test_coverage_heatmap.py` 全13テストを確認した結果:
  - **影響なし（11テスト）**: `TestCoverageHeatmapInit` 3テスト（sigma計算のみ）、`TestCoverageHeatmapGenerate` のうち `test_empty_points_returns_black`, `test_output_shape_matches_image_size`, `test_single_point_creates_colored_area`, `test_single_point_far_corners_are_black`, `test_gaussian_spread_fills_between_corners`, `test_zero_pixels_are_black`, `test_multiple_captures_accumulate`, `test_points_at_image_edge`, `test_points_outside_image_clipped` — これらは色の有無や形状の検証であり、正規化方式に依存しない
  - **影響あり（1テスト）**: `test_dense_points_produce_higher_intensity`（L117-128）— 10点集中 vs 1点の比較。固定スケールでは10点が `SAT_CAPTURES=3` で飽和し255に到達する。1点のピーク値は `255/3 ≈ 85` 程度。両方とも非黒であることの検証（L127-128）は通るが、テストの意図（密度の違いが強度に反映される）を維持するため、密集側のピクセル値 > 疎側のピクセル値 の検証を追加する
  - **影響なし（1テスト）**: `test_dense_points_produce_higher_intensity` の既存アサーション（非黒の確認）自体は通る。ただし修正後の仕様をより正確に検証するためアサーションを強化する

### 1.5 確認方法

- **自動テスト**:
  - 既存13テストを実行し全て合格することを確認する
  - `test_dense_points_produce_higher_intensity` に密集側 > 疎側のピクセル値比較アサーションを追加する
  - 新規テストを追加する:
    - `test_fixed_scale_saturation`: SAT_CAPTURES 回同一位置にコーナーが重なった場合、そのピクセルの正規化値が255（飽和）に到達すること
    - `test_fixed_scale_clip`: SAT_CAPTURES 回を超えた場合でも255にクリップされること（255を超えない）
    - `test_no_intensity_drop_on_new_capture`: 1回目のキャプチャ後のヒートマップと、2回目のキャプチャ（別領域）追加後のヒートマップで、1回目の領域のピクセル値が下がらないこと（本不具合の直接的な回帰テスト）
- **手動テスト**:
  1. 画像の左半分でキャプチャを3回取得 → 左半分が赤色になること
  2. 画像の右半分でキャプチャを1回取得 → 左半分の赤色が維持されること。右半分は青〜緑で表示されること
  3. 右半分でさらに2回キャプチャ → 右半分も赤色に近づくこと
  4. カバレッジがない領域は黒のままであること
