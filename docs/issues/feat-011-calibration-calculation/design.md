# 機能設計書: Camera Calibration - Calibration Calculation + Result Display

対象: feat-011
作成日: 2026-03-13
基準文書: `docs/DESIGN_STANDARD.md`
要求仕様書: `docs/issues/feat-011-calibration-calculation/requirements.md`

---

## 1. 対応要求マッピング

| 要求ID | 要求名 | 設計セクション |
|--------|--------|---------------|
| FR-001 | キャリブレーション計算 | 4.1 |
| FR-002 | 結果表示 | 4.2 |
| FR-003 | キャプチャごとの再投影誤差表示 | 4.3 |
| FR-004 | Calibrateボタンと結果のライフサイクル管理 | 4.4 |

---

## 2. システム構成

### 2.1 モジュール構成図

```
+-----------------------------------------------------------------+
|                        MainWindow (既存)                         |
|  +-----------------------------------------------------------+  |
|  |                      QTabWidget                            |  |
|  |  +--------+--------+--------+--------+-----------------+  |  |
|  |  | Tab1   | Tab2   | Tab3   | Tab4   | Tab5            |  |  |
|  |  |Channel | Camera | Multi  |Settings| Calibration     |  |  |
|  |  |Manager |Settings| View   | Viewer | Widget (変更)   |  |  |
|  |  +--------+--------+--------+--------+-----------------+  |  |
|  +-----------------------------------------------------------+  |
+-----------------------------------------------------------------+
```

### 2.2 関連ファイル

| ファイル | 役割 | 変更種別 |
|---------|------|---------|
| `src/synchroCap/calibration_engine.py` | キャリブレーション計算エンジン（新規） | **新規作成** |
| `src/synchroCap/ui_calibration.py` | Tab5 CalibrationWidget（Calibrateボタン、Results表示追加） | **変更** |
| `src/synchroCap/board_detector.py` | ボード検出エンジン（変更なし） | 変更なし |
| `src/synchroCap/stability_trigger.py` | 安定検出トリガー（変更なし） | 変更なし |
| `src/synchroCap/coverage_heatmap.py` | カバレッジヒートマップ（変更なし） | 変更なし |
| `src/synchroCap/mainwindow.py` | タブ管理（変更なし） | 変更なし |

### 2.3 モジュール間の依存関係

```
mainwindow.py (既存・変更なし)
  +-- ui_calibration.py (変更)
        +-- calibration_engine.py (新規)
        +-- coverage_heatmap.py (既存・変更なし)
        +-- stability_trigger.py (既存・変更なし)
        +-- board_detector.py (既存・変更なし)
        +-- imagingcontrol4 (ic4)
        +-- cv2
        +-- numpy
        +-- channel_registry.py
        +-- device_resolver.py
```

循環依存は存在しない。`calibration_engine.py` は `numpy` と `cv2` のみに依存する。

### 2.4 ディレクトリ構成

```
src/synchroCap/
+-- calibration_engine.py              # 新規
+-- ui_calibration.py                  # 変更
+-- coverage_heatmap.py                # 変更なし
+-- stability_trigger.py               # 変更なし
+-- board_detector.py                  # 変更なし
+-- mainwindow.py                      # 変更なし
+-- (その他既存ファイル)                # 変更なし
```

---

## 3. 技術スタック

| 項目 | バージョン |
|------|-----------|
| Python | 3.10 |

| ライブラリ | バージョン | 用途 | 選定理由 |
|-----------|-----------|------|---------|
| numpy | ==2.2.6 | 配列操作 | 既存（バージョンは TECH_STACK.md に従う） |
| opencv-contrib-python | >=4.9.0 | calibrateCamera, projectPoints | 既存 |
| PySide6 | ==6.8.3 | GUI | 既存 |

新規ライブラリの追加なし。

---

## 4. 各機能の詳細設計

### 4.1 キャリブレーション計算（FR-001）

#### データフロー

- 入力:
  - `object_points_list: list[numpy.ndarray]` — 各キャプチャの object_points。各要素は shape=(N,1,3), float32
  - `image_points_list: list[numpy.ndarray]` — 各キャプチャの image_points。各要素は shape=(N,1,2), float32
  - `image_size: tuple[int, int]` — (width, height)。`cv2.calibrateCamera()` は `imageSize=(width, height)` を期待し、`_capture_image_size` はこの形式で保持されている（`_execute_capture()` の `(w, h)` で設定）
- 中間データ:
  - `cv2.calibrateCamera()` の戻り値: (rms, camera_matrix, dist_coeffs, rvecs, tvecs)
- 出力:
  - `CalibrationResult` データクラス

#### CalibrationResult データクラス

```python
@dataclass
class CalibrationResult:
    """Calibration calculation result."""
    rms_error: float                     # RMS reprojection error (pixels)
    camera_matrix: numpy.ndarray         # shape=(3,3), float64
    dist_coeffs: numpy.ndarray           # shape=(1,5), float64
    rvecs: list[numpy.ndarray]           # per-image rotation vectors
    tvecs: list[numpy.ndarray]           # per-image translation vectors
    per_image_errors: list[float]        # per-image RMS reprojection error (pixels)
```

#### CalibrationEngine クラス設計

キャリブレーション計算ロジックを `calibration_engine.py` に分離する。UIに依存しない純粋な計算クラスとする（`stability_trigger.py`, `coverage_heatmap.py` と同じ設計パターン）。

```python
# calibration_engine.py

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy

logger = logging.getLogger(__name__)


@dataclass
class CalibrationResult:
    """Calibration calculation result."""
    rms_error: float
    camera_matrix: numpy.ndarray
    dist_coeffs: numpy.ndarray
    rvecs: list[numpy.ndarray]
    tvecs: list[numpy.ndarray]
    per_image_errors: list[float]


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
```

**設計判断**: calibration_engine.py の分離
- 採用: キャリブレーション計算ロジックを独立モジュールに分離（テスタビリティ、UI非依存の純粋ロジック。stability_trigger.py, coverage_heatmap.py と同じ設計パターン）
- 却下: `ui_calibration.py` に直接記述（UIコードと計算ロジックの混在を避ける）

**設計判断**: cv2.calibrateCamera() のフラグ
- 採用: デフォルトフラグ（None, None）で実行する。一般的なピンホール+放射歪みモデルで5パラメータ (k1, k2, p1, p2, k3) を推定する
- 却下: `cv2.CALIB_FIX_ASPECT_RATIO` などのフラグ指定（シンプルさ優先、通常用途では不要）
- 却下: fisheye モデル（スコープ外）

**設計判断**: 最小キャプチャ数
- 採用: 4件（5パラメータの歪み係数 + 4パラメータの内部行列を安定推定するため。2-3件では自由度が不足し、結果が不安定）
- 却下: 10件（品質推奨値であり、最小要件としては厳しすぎる。ユーザーがRMS値で品質を判断する）

**設計判断**: 再投影誤差の計算方式
- 採用: 各キャプチャごとに `cv2.projectPoints()` で再投影し、検出点との差のRMSを計算する（キャプチャごとの品質を個別に把握できる）
- 却下: 全体RMSのみ（個々のキャプチャの品質が分からず、悪いキャプチャの特定ができない）

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| キャプチャ数不足 | `len() < MIN_CAPTURES` | ValueError送出。呼び出し元でキャッチ不要（ボタンが無効化されているため到達しない） | — |
| cv2.calibrateCamera() 失敗 | cv2.error catch | 呼び出し元（ui_calibration.py）でキャッチし、ステータスに表示 | WARNING |

#### 境界条件

- キャプチャ4件（最小）: 計算は実行される。パラメータの精度は低い可能性がある（ユーザーがRMS値で判断）
- 全キャプチャのコーナー数が同一でない場合: `cv2.calibrateCamera()` は各画像で異なるコーナー数を許容する（ChArUcoの場合、部分検出が一般的）
- object_points の単位がメートル（board_detector.py で square_mm / 1000.0 で変換済み）: カメラ行列のfx, fyはピクセル単位、tvecはメートル単位で出力される

### 4.2 結果表示（FR-002）

#### UI構成

左パネルの Captures GroupBox の下に「Calibration」QGroupBox を追加する。このグループには「Calibrate」ボタンと結果表示ラベルを含む。

```python
# Calibration section
calib_group = QGroupBox("Calibration")
calib_layout = QVBoxLayout(calib_group)

self._calibrate_button = QPushButton("Calibrate")
self._calibrate_button.setEnabled(False)
self._calibrate_button.clicked.connect(self._on_calibrate_clicked)
calib_layout.addWidget(self._calibrate_button)

results_form = QFormLayout()

self._rms_label = QLabel("---")
results_form.addRow("RMS Error:", self._rms_label)

self._fx_label = QLabel("---")
results_form.addRow("fx:", self._fx_label)

self._fy_label = QLabel("---")
results_form.addRow("fy:", self._fy_label)

self._cx_label = QLabel("---")
results_form.addRow("cx:", self._cx_label)

self._cy_label = QLabel("---")
results_form.addRow("cy:", self._cy_label)

self._dist_label = QLabel("---")
self._dist_label.setWordWrap(True)
results_form.addRow("Dist:", self._dist_label)

calib_layout.addLayout(results_form)

left_layout.addWidget(calib_group)
```

#### 結果更新処理

```python
def _display_calibration_result(self, result: CalibrationResult) -> None:
    """Update result labels with calibration values."""
    self._rms_label.setText(f"{result.rms_error:.4f} px")
    self._fx_label.setText(f"{result.camera_matrix[0, 0]:.1f}")
    self._fy_label.setText(f"{result.camera_matrix[1, 1]:.1f}")
    self._cx_label.setText(f"{result.camera_matrix[0, 2]:.1f}")
    self._cy_label.setText(f"{result.camera_matrix[1, 2]:.1f}")

    d = result.dist_coeffs.flatten()
    self._dist_label.setText(
        f"k1={d[0]:.4f}, k2={d[1]:.4f}\n"
        f"p1={d[2]:.4f}, p2={d[3]:.4f}\n"
        f"k3={d[4]:.4f}"
    )
```

#### 結果クリア処理

```python
def _clear_calibration_result(self) -> None:
    """Clear result labels and internal result state."""
    self._calibration_result = None
    self._rms_label.setText("---")
    self._fx_label.setText("---")
    self._fy_label.setText("---")
    self._cx_label.setText("---")
    self._cy_label.setText("---")
    self._dist_label.setText("---")
```

**設計判断**: 結果表示の場所
- 採用: 左パネルに「Calibration」QGroupBox として配置（ワークフローの流れに沿って上から順に Camera → Board Settings → Captures → Calibration。左パネルは QScrollArea で包まれているためスクロール可能）
- 却下: ダイアログ表示（結果を常に見ながらキャプチャの追加/削除を行う反復ワークフローに適さない）
- 却下: 右パネル下部（ライブビュー表示領域を圧迫する）

**設計判断**: 歪み係数の表示形式
- 採用: `k1=..., k2=...\np1=..., p2=...\nk3=...` の3行表示（左パネル幅200pxに収まるよう改行。各パラメータ名を付与して意味が分かるようにする。QLabel の `setWordWrap(True)` を設定）
- 却下: 1行のカンマ区切り（左パネル幅に収まらずはみ出す）
- 却下: 5行の個別ラベル（FormLayout の行数が多くなりすぎる）

### 4.3 キャプチャごとの再投影誤差表示（FR-003）

#### 処理ロジック

キャプチャリストの表示更新メソッド `_update_capture_list_ui()` を変更する。`_calibration_result` が存在する場合は再投影誤差を付加する。

```python
def _update_capture_list_ui(self) -> None:
    """Rebuild the captures QListWidget."""
    self._captures_list.clear()
    for i, cap in enumerate(self._captures):
        text = f"#{i+1:02d}: {cap.num_corners} corners"
        if (self._calibration_result is not None
                and i < len(self._calibration_result.per_image_errors)):
            err = self._calibration_result.per_image_errors[i]
            text += f" | err: {err:.2f} px"
        self._captures_list.addItem(text)
```

#### 境界条件

- キャリブレーション結果がない場合: `#01: 24 corners`（既存と同一の表示）
- キャプチャ追加後（結果クリア済み）: `#01: 24 corners`（結果が `None` のため誤差非表示）

### 4.4 Calibrateボタンと結果のライフサイクル管理（FR-004）

#### Calibrateボタンの実行処理

```python
def _on_calibrate_clicked(self) -> None:
    """Execute calibration calculation."""
    if len(self._captures) < CalibrationEngine.MIN_CAPTURES:
        return
    # _capture_image_size は初回キャプチャ時に設定されるため、
    # キャプチャが MIN_CAPTURES 件以上であれば必ず非 None

    object_points_list = [cap.object_points for cap in self._captures]
    image_points_list = [cap.image_points for cap in self._captures]

    # ValueError は到達しない（上の len チェックで MIN_CAPTURES 未満を排除済み）。
    # catch するのは cv2.error のみ。
    try:
        result = self._calibration_engine.calibrate(
            object_points_list,
            image_points_list,
            self._capture_image_size,
        )
    except cv2.error as e:
        self._status_label.setText(f"Calibration failed: {e}")
        logger.warning("Calibration failed: %s", e)
        return

    self._calibration_result = result
    self._display_calibration_result(result)
    self._update_capture_list_ui()
    self._status_label.setText(
        f"Calibration done: RMS={result.rms_error:.4f} px"
    )
```

#### ボタン状態管理

`_update_button_states()` に Calibrate ボタンの有効/無効ロジックを追加する。

```python
def _update_button_states(self, _row: int = -1) -> None:
    """Update Delete/Clear All/Calibrate button enabled states."""
    has_captures = len(self._captures) > 0
    has_selection = self._captures_list.currentRow() >= 0

    self._delete_button.setEnabled(has_captures and has_selection)
    self._clear_all_button.setEnabled(has_captures)
    self._save_button.setEnabled(has_captures)
    self._calibrate_button.setEnabled(
        len(self._captures) >= CalibrationEngine.MIN_CAPTURES
    )
```

#### 結果クリアのタイミング

キャプチャの追加・削除時に結果をクリアする。以下の箇所で `_clear_calibration_result()` を呼び出す:

| 呼び出し元 | タイミング | 説明 |
|-----------|----------|------|
| `_execute_capture()` | キャプチャ追加後 | `self._captures.append(capture)` の後、`_update_heatmap_cache()` の前に呼び出す |
| `_on_delete_clicked()` | キャプチャ削除後 | `self._captures.pop(row)` の後、`_update_heatmap_cache()` の前に呼び出す |
| `_on_clear_all_clicked()` | 全キャプチャクリア後 | `self._captures.clear()` の後、`_update_heatmap_cache()` の前に呼び出す |
| `stop_live_view()` | カメラ切替・タブ離脱時 | キャプチャクリアと同時に呼び出す |

#### _execute_capture() への追加

```python
def _execute_capture(self, result: DetectionResult, raw_bgr: numpy.ndarray) -> None:
    # ... 既存のキャプチャ追加処理 ...
    self._captures.append(capture)
    n = len(self._captures)

    self._clear_calibration_result()   # 追加
    self._update_heatmap_cache()
    self._update_capture_list_ui()
    self._update_button_states()
    self._flash_live_view()
    # ...
```

#### _on_delete_clicked() への追加

```python
def _on_delete_clicked(self) -> None:
    # ... 既存の削除処理 ...
    self._captures.pop(row)
    if not self._captures:
        self._capture_image_size = None
    self._clear_calibration_result()   # 追加
    self._update_heatmap_cache()
    self._update_capture_list_ui()
    self._update_button_states()
    # ...
```

#### _on_clear_all_clicked() への追加

```python
def _on_clear_all_clicked(self) -> None:
    self._captures.clear()
    self._capture_image_size = None
    self._clear_calibration_result()   # 追加
    self._update_heatmap_cache()
    self._update_capture_list_ui()
    self._update_button_states()
    # ...
```

#### stop_live_view() への追加

```python
def stop_live_view(self) -> None:
    # ... 既存のクリア処理 ...
    self._captures.clear()
    self._capture_image_size = None
    self._stability_trigger.reset()
    self._heatmap_cache = None
    self._heatmap_generator = None
    self._clear_calibration_result()    # 追加
    self._update_capture_list_ui()
    self._update_button_states()
```

#### 境界条件

- キャプチャ3件から4件目追加時: Calibrate ボタンが無効→有効に切り替わる
- キャプチャ4件から3件に削除時: Calibrate ボタンが有効→無効に切り替わる。結果もクリアされる
- Calibrate実行直後にキャプチャ追加: 結果がクリアされ、再度Calibrateボタンの押下が必要
- 同じキャプチャセットで再Calibrate: 結果が再計算され上書きされる（冪等な操作）

---

## 5. 状態遷移

CalibrationWidget の状態遷移は feat-009/010 と同一（Idle, Connecting, LiveView）。本案件で新たな状態は追加しない。

キャリブレーション結果は LiveView 状態の内部属性として保持される。`_calibration_result: CalibrationResult | None` が `None` でなければ結果表示中。

### 5.1 各状態でのUI要素の状態

| 状態 | カメラ一覧 | Delete | Clear All | Save | Calibrate | Results | ライブビュー |
|------|-----------|--------|-----------|------|-----------|---------|-------------|
| Idle | 有効 | 無効 | 無効 | 無効 | 無効 | `---` | メッセージ表示 |
| Connecting | 無効 | 無効 | 無効 | 無効 | 無効 | `---` | 空 |
| LiveView（キャプチャ0〜3件）| 有効 | 選択時有効 | キャプチャ1件以上で有効 | キャプチャ1件以上で有効 | 無効 | `---` | ライブ + ヒートマップ |
| LiveView（キャプチャ4件以上、未計算）| 有効 | 選択時有効 | 有効 | 有効 | **有効** | `---` | ライブ + ヒートマップ |
| LiveView（キャプチャ4件以上、計算済み）| 有効 | 選択時有効 | 有効 | 有効 | **有効** | **数値表示** | ライブ + ヒートマップ |

---

## 6. ファイル・ディレクトリ設計

本案件でファイル入出力はない。キャリブレーション結果はメモリ上にのみ保持される。

---

## 7. インターフェース定義

### 7.1 calibration_engine.py（新規）

```python
@dataclass
class CalibrationResult:
    rms_error: float                     # RMS reprojection error (pixels)
    camera_matrix: numpy.ndarray         # shape=(3,3), float64
    dist_coeffs: numpy.ndarray           # shape=(1,5), float64
    rvecs: list[numpy.ndarray]           # per-image rotation vectors
    tvecs: list[numpy.ndarray]           # per-image translation vectors
    per_image_errors: list[float]        # per-image RMS reprojection error (pixels)


class CalibrationEngine:
    MIN_CAPTURES: int = 4

    def calibrate(
        self,
        object_points_list: list[numpy.ndarray],
        image_points_list: list[numpy.ndarray],
        image_size: tuple[int, int],
    ) -> CalibrationResult:
        """Run camera calibration.

        Raises:
            ValueError: If len(object_points_list) < MIN_CAPTURES.
            cv2.error: If cv2.calibrateCamera() fails.
        """
        ...
```

### 7.2 ui_calibration.py（変更分のみ）

既存の `CalibrationWidget` クラスに以下を追加する。

import に `CalibrationEngine`, `CalibrationResult` を追加:

```python
from calibration_engine import CalibrationEngine, CalibrationResult
```

```python
class CalibrationWidget(QWidget):
    # -- 追加メンバー変数（__init__ の # Heatmap state セクションの後に追加）--
    # self._calibration_engine: CalibrationEngine = CalibrationEngine()
    # self._calibration_result: CalibrationResult | None = None

    # -- 追加UIウィジェット --
    # self._calibrate_button: QPushButton
    # self._rms_label: QLabel
    # self._fx_label: QLabel
    # self._fy_label: QLabel
    # self._cx_label: QLabel
    # self._cy_label: QLabel
    # self._dist_label: QLabel

    # -- 追加メソッド --

    def _on_calibrate_clicked(self) -> None:
        """Calibrateボタン押下時。キャリブレーション計算を実行"""

    def _display_calibration_result(self, result: CalibrationResult) -> None:
        """結果ラベルをキャリブレーション値で更新"""

    def _clear_calibration_result(self) -> None:
        """結果ラベルと内部結果状態をクリア"""

    # -- 変更メソッド --
    # _update_button_states(): Calibrate ボタンの有効/無効を追加
    # _update_capture_list_ui(): 再投影誤差の付加表示を追加
    # _execute_capture(): _clear_calibration_result() 呼び出しを追加
    # _on_delete_clicked(): _clear_calibration_result() 呼び出しを追加
    # _on_clear_all_clicked(): _clear_calibration_result() 呼び出しを追加
    # stop_live_view(): _clear_calibration_result() 呼び出しを追加
```

### 7.3 UIレイアウト（変更後）

```
+----------+------------------+
|Camera    |  Status (QLabel) |
|List      |------------------|
|(QList)   |   Live View      |
|----------|   (QFrame >      |
|Board     |    QLabel)       |
|Settings  |                  |
|----------|                  |
|Captures  |                  |
|(QList)   |                  |
|[Delete][Clear All]          |
|[Save]    |                  |
|----------|                  |
|Calibra-  |                  |
|tion      |                  |
|[Calibrate]                  |
|RMS: 0.1234 px              |
|fx: 1234.5                  |
|fy: 1234.5                  |
|cx: 960.0                   |
|cy: 540.0                   |
|Dist: k1=... k2=...         |
|  p1=... p2=...             |
|  k3=...                    |
+----------+------------------+
左パネル(left_panel): 固定幅200px（変更なし）
QScrollArea: 固定幅220px（変更なし）
```

左パネルの構成（上から順）:
1. Camera（QGroupBox）-- 既存
2. Board Settings（QGroupBox）-- 既存
3. Captures（QGroupBox）-- 既存
4. Calibration（QGroupBox）-- **新規**

---

## 8. ログ・デバッグ設計

### 8.1 ログレベル使い分け

| レベル | 使い分け | 例 |
|--------|---------|-----|
| INFO | キャリブレーション完了 | `Calibration done: RMS=0.1234 px, 15 images` |
| WARNING | キャリブレーション失敗 | `Calibration failed: {cv2.error message}` |

### 8.2 ログ出力ポイント

| モジュール | INFO | WARNING | ERROR |
|-----------|------|---------|-------|
| calibration_engine | キャリブレーション完了（RMS値、画像数） | — | — |
| ui_calibration | — | キャリブレーション失敗 | — |

`calibration_engine.py` は計算完了時に INFO ログを出力する。エラーは例外として呼び出し元に伝搬する。

### 8.3 ログフォーマット

既存の `ui_calibration.py` のロガー設定に従う。フォーマットは `[%(asctime)s] %(levelname)s %(name)s: %(message)s`（datefmt: `%H:%M:%S`）を使用。

---

## 9. テスト方針

### 9.1 単体テスト対象

`calibration_engine.py` の `CalibrationEngine` クラス:

- **正常系**:
  - 合成データ（既知のカメラ行列で生成した image_points）でキャリブレーションが実行でき、CalibrationResult が返される
  - RMS 再投影誤差が合理的な値（合成データでは 1.0px 以下）になる
  - camera_matrix の shape が (3,3)、dist_coeffs の shape が (1,5) である
  - per_image_errors のリスト長がキャプチャ数と一致する
  - per_image_errors の各値が 0 以上の float である

- **異常系**:
  - キャプチャ数が MIN_CAPTURES 未満で ValueError が送出される
  - 空のキャプチャリストで ValueError が送出される

- **境界条件**:
  - キャプチャ4件（最小）で計算が実行できる

### 9.2 テストデータの生成方法

合成データによるテスト: 既知のカメラ行列と歪み係数を設定し、`cv2.projectPoints()` で image_points を生成する。この image_points を使ってキャリブレーションを実行し、元のカメラ行列に近い値が得られることを検証する。

```python
# テストデータ生成の概要（意図の伝達目的、そのままコピーして使わないこと）
known_camera_matrix = numpy.array([
    [800.0,   0.0, 320.0],
    [  0.0, 800.0, 240.0],
    [  0.0,   0.0,   1.0],
], dtype=numpy.float64)

known_dist_coeffs = numpy.zeros((1, 5), dtype=numpy.float64)

# 複数のボード姿勢（rvec, tvec）を生成し、
# cv2.projectPoints() で各姿勢の image_points を生成する
# 生成した object_points と image_points で calibrate() を呼び出す
```

### 9.3 統合テスト

GUIを含む統合テストは手動で実施する。テスト項目:
- キャプチャ3件以下ではCalibrateボタンが無効化されること
- キャプチャ4件以上でCalibrateボタンが有効化されること
- Calibrateボタン押下でキャリブレーション結果が表示されること
- 結果のRMS Error, fx, fy, cx, cy, Distortionが表示されること
- キャプチャリストの各エントリに再投影誤差が表示されること
- キャプチャ追加後にキャリブレーション結果がクリアされること
- キャプチャ削除後にキャリブレーション結果がクリアされること
- Clear Allでキャリブレーション結果がクリアされること
- カメラ切替でキャリブレーション結果がクリアされること

---

## 10. 実装時の追加更新対象

- `docs/TECH_STACK.md`: numpy と opencv-contrib-python の「使用箇所」列に `calibration_engine` を追記する
- `CLAUDE.md`: ディレクトリ構成に `calibration_engine.py` を追記する
