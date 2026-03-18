# 機能設計書: Camera Calibration - Export (Pose2Sim TOML + JSON)

対象: feat-012
作成日: 2026-03-18
基準文書: `docs/DESIGN_STANDARD.md`
要求仕様書: `docs/issues/feat-012-export-pose2sim/requirements.md`

---

## 1. 対応要求マッピング

| 要求ID | 要求名 | 設計セクション |
|--------|--------|---------------|
| FR-001 | Exportボタン | 4.1 |
| FR-002 | Pose2Sim TOML エクスポート | 4.2 |
| FR-003 | JSON エクスポート | 4.3 |
| FR-004 | Exportボタンのライフサイクル管理 | 4.4 |

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
| `src/synchroCap/calibration_exporter.py` | エクスポートエンジン（TOML/JSON生成） | **新規作成** |
| `src/synchroCap/ui_calibration.py` | Tab5 CalibrationWidget（Exportボタン追加） | **変更** |
| `src/synchroCap/calibration_engine.py` | キャリブレーション計算エンジン（変更なし） | 変更なし |

### 2.3 モジュール間の依存関係

```
ui_calibration.py (変更)
  +-- calibration_exporter.py (新規)
  |     +-- calibration_engine.py (CalibrationResult 参照のみ)
  |     +-- json (Python標準)
  |     +-- pathlib
  +-- calibration_engine.py (既存・変更なし)
  +-- (その他既存モジュール)
```

循環依存は存在しない。`calibration_exporter.py` は `CalibrationResult` を型参照のみで使用する。

### 2.4 ディレクトリ構成

```
src/synchroCap/
+-- calibration_exporter.py              # 新規
+-- calibration_engine.py                # 変更なし
+-- ui_calibration.py                    # 変更
+-- (その他既存ファイル)                  # 変更なし
```

---

## 3. 技術スタック

| 項目 | バージョン |
|------|-----------|
| Python | 3.10 |

| ライブラリ | バージョン | 用途 | 選定理由 |
|-----------|-----------|------|---------|
| json | Python標準 | JSONエクスポート | 標準ライブラリのため追加不要 |
| pathlib | Python標準 | ファイルパス操作 | 標準ライブラリのため追加不要 |
| numpy | ==2.2.6 | ndarray→list変換 | 既存 |
| PySide6 | ==6.8.3 | GUI（QPushButton） | 既存 |

新規外部ライブラリの追加なし。

**設計判断**: TOML生成方式
- 採用: f-stringによる手動構築（Pose2Simの `toml_write()` と同一方式。外部ライブラリ不要。出力形式を完全に制御できる）
- 却下: `toml` ライブラリの `toml.dump()`（ネスト配列のフォーマットがPose2Simの期待する形式と異なる可能性がある。不要な依存を追加する）

---

## 4. 各機能の詳細設計

### 4.1 Exportボタン（FR-001）

#### UI構成

Calibration QGroupBox 内の Calibrate ボタンの下に Export ボタンを追加する。

```python
# _create_ui() 内、Calibration section に追加
self._export_button = QPushButton("Export")
self._export_button.setEnabled(False)
self._export_button.clicked.connect(self._on_export_clicked)
calib_layout.addWidget(self._export_button)
```

配置順序（Calibration QGroupBox 内）:
1. Calibrate ボタン（既存）
2. Export ボタン（**新規**）
3. Results QFormLayout（既存）

#### 処理ロジック

```python
def _on_export_clicked(self) -> None:
    """Export calibration result to TOML and JSON files."""
    if self._calibration_result is None or self._capture_image_size is None:
        return

    try:
        export_dir = self._ensure_save_dir()
    except OSError as e:
        self._status_label.setText(f"Export failed: {e}")
        logger.error("Export failed: %s", e)
        return

    try:
        exporter = CalibrationExporter()
        paths = exporter.export(
            result=self._calibration_result,
            serial=self._current_serial,
            image_size=self._capture_image_size,
            num_images=len(self._captures),
            output_dir=export_dir,
        )
    except OSError as e:
        self._status_label.setText(f"Export failed: {e}")
        logger.error("Export failed: %s", e)
        return

    self._status_label.setText(f"Exported to {export_dir}")
    logger.info("Exported: %s", [str(p) for p in paths])
```

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| ディレクトリ作成失敗 / ファイル書き込み失敗 | OSError catch | ステータスラベルに `Export failed: {e}` を表示。`OSError` のメッセージにファイルパスが含まれるため、失敗したファイルをユーザーが特定できる。成功済みファイルはそのまま残す | ERROR |

### 4.2 Pose2Sim TOML エクスポート（FR-002）

#### データフロー

- 入力:
  - `CalibrationResult` — カメラ行列 (3x3, float64), 歪み係数 (1x5, float64), RMS誤差
  - `serial: str` — カメラシリアル番号
  - `image_size: tuple[int, int]` — (width, height)
- 出力:
  - `{serial}_intrinsics.toml` ファイル

#### 出力ファイル形式

Pose2Simの `toml_write()` 関数が出力する形式に準拠する。数値フォーマット: カメラ行列・歪み係数・RMS誤差は小数点以下4桁（`:.4f`）、`size` は小数点以下1桁（`:.1f`）で出力する。科学記法は使用しない。

```toml
[cam_49710379]
name = "cam_49710379"
size = [1920.0, 1080.0]
matrix = [[1120.5432, 0.0, 960.3210], [0.0, 1118.7654, 540.1098], [0.0, 0.0, 1.0]]
distortions = [-0.0812, 0.1243, -0.0003, 0.0001]
rotation = [0.0, 0.0, 0.0]
translation = [0.0, 0.0, 0.0]
fisheye = false

[metadata]
adjusted = false
error = 0.3220
```

#### 処理ロジック

1. `CalibrationResult.camera_matrix` (3x3 ndarray) を行ごとにリスト化する
2. `CalibrationResult.dist_coeffs` (1x5 ndarray) から先頭4要素 (k1, k2, p1, p2) を取得する。OpenCVの順序は `[k1, k2, p1, p2, k3]` であり、インデックス `[0:4]` を使用する
3. f-stringでTOML文字列を構築する
4. ファイルに `open(path, "w", encoding="utf-8")` で書き込む

前提条件: `CalibrationResult.dist_coeffs` は `CalibrationEngine.calibrate()` が `shape=(1, 5)` を保証するため、要素数チェックは行わない

```python
def _build_toml(
    self,
    result: CalibrationResult,
    serial: str,
    image_size: tuple[int, int],
) -> str:
    cam_name = f"cam_{serial}"
    K = result.camera_matrix
    d = result.dist_coeffs.flatten()

    lines = []
    lines.append(f"[{cam_name}]")
    lines.append(f'name = "{cam_name}"')
    lines.append(f"size = [{image_size[0]:.1f}, {image_size[1]:.1f}]")
    lines.append(
        f"matrix = ["
        f"[{K[0,0]:.4f}, {K[0,1]:.4f}, {K[0,2]:.4f}], "
        f"[{K[1,0]:.4f}, {K[1,1]:.4f}, {K[1,2]:.4f}], "
        f"[{K[2,0]:.4f}, {K[2,1]:.4f}, {K[2,2]:.4f}]]"
    )
    lines.append(
        f"distortions = [{d[0]:.4f}, {d[1]:.4f}, {d[2]:.4f}, {d[3]:.4f}]"
    )
    lines.append("rotation = [0.0, 0.0, 0.0]")
    lines.append("translation = [0.0, 0.0, 0.0]")
    lines.append("fisheye = false")
    lines.append("")
    lines.append("[metadata]")
    lines.append("adjusted = false")
    lines.append(f"error = {result.rms_error:.4f}")
    lines.append("")

    return "\n".join(lines)
```

#### Pose2Sim互換性の詳細

| フィールド | 値の由来 | 備考 |
|-----------|---------|------|
| `name` | `"cam_{serial}"` | セクションヘッダと一致させる |
| `size` | `image_size` を `:.1f` で float 出力 | Pose2Sim は float 配列として読む |
| `matrix` | `CalibrationResult.camera_matrix` | 3x3 ネスト配列 |
| `distortions` | `CalibrationResult.dist_coeffs[0:4]` | k1, k2, p1, p2 の4要素。k3 は除外 |
| `rotation` | `[0.0, 0.0, 0.0]` | Rodriguesベクトル。内部パラメータのみのためゼロ |
| `translation` | `[0.0, 0.0, 0.0]` | 内部パラメータのみのためゼロ |
| `fisheye` | `false` | 常に false |
| `metadata.adjusted` | `false` | Pose2Simが外部パラメータ調整済みかを示すフラグ。intrinsicsのみのため `false` 固定 |
| `metadata.error` | `CalibrationResult.rms_error` | RMS再投影誤差 |

**設計判断**: 歪み係数の要素数
- 採用: TOML は4要素 (k1, k2, p1, p2)。Pose2Simの既存コードが4要素を前提としている
- 却下: 5要素 (k1, k2, p1, p2, k3)（Pose2Simの既存フォーマットとの互換性が保証されない）

**設計判断**: カメラ名のフォーマット
- 採用: `cam_{serial}`（例: `cam_49710379`）。Pose2Simの予約セクション名（metadata, capture_volume, charuco, checkerboard）と衝突しない
- 却下: シリアル番号のみ（数字のみのセクション名はTOMLの慣習に反する）

### 4.3 JSON エクスポート（FR-003）

#### データフロー

- 入力:
  - `CalibrationResult` — カメラ行列, 歪み係数, RMS誤差
  - `serial: str` — カメラシリアル番号
  - `image_size: tuple[int, int]` — (width, height)
  - `num_images: int` — キャリブレーションに使用したキャプチャ数
- 出力:
  - `{serial}_intrinsics.json` ファイル

#### 出力ファイル形式

```json
{
  "serial": "49710379",
  "image_size": [1920, 1080],
  "camera_matrix": [
    [1120.5432, 0.0, 960.321],
    [0.0, 1118.7654, 540.1098],
    [0.0, 0.0, 1.0]
  ],
  "dist_coeffs": [-0.0812, 0.1243, -0.0003, 0.0001, 0.0056],
  "rms_error": 0.322,
  "num_images": 53
}
```

#### 処理ロジック

1. `CalibrationResult.camera_matrix` (3x3 ndarray) を `tolist()` でネストリストに変換する
2. `CalibrationResult.dist_coeffs` (1x5 ndarray) を `flatten().tolist()` で5要素リストに変換する
3. `json.dump()` で `indent=2` 付き、`open(path, "w", encoding="utf-8")` で書き込む。数値は `json.dump()` のデフォルト浮動小数点表現をそのまま使用する（桁数の制御は行わない。`numpy.float64` は `float()` でPython floatに変換済み）

```python
def _build_json_dict(
    self,
    result: CalibrationResult,
    serial: str,
    image_size: tuple[int, int],
    num_images: int,
) -> dict:
    return {
        "serial": serial,
        "image_size": list(image_size),
        "camera_matrix": result.camera_matrix.tolist(),
        "dist_coeffs": result.dist_coeffs.flatten().tolist(),
        "rms_error": float(result.rms_error),
        "num_images": num_images,
    }
```

**設計判断**: JSON の歪み係数
- 採用: 5要素 (k1, k2, p1, p2, k3)。OpenCV完全互換。他ツールでの読み込み時に情報が欠落しない
- 却下: 4要素（k3 を失う。汎用フォーマットとしての価値が低下する）

### 4.4 Exportボタンのライフサイクル管理（FR-004）

#### 処理ロジック

既存の `_update_button_states()` にExportボタンの有効/無効ロジックを追加する。

```python
def _update_button_states(self, _row: int = -1) -> None:
    """Update Delete/Clear All/Calibrate/Export button enabled states."""
    has_captures = len(self._captures) > 0
    has_selection = self._captures_list.currentRow() >= 0

    self._delete_button.setEnabled(has_captures and has_selection)
    self._clear_all_button.setEnabled(has_captures)
    self._save_button.setEnabled(has_captures)
    self._calibrate_button.setEnabled(
        len(self._captures) >= CalibrationEngine.MIN_CAPTURES
    )
    self._export_button.setEnabled(self._calibration_result is not None)
```

#### 状態変化のトリガー

`_update_button_states()` は以下の箇所で既に呼び出されているため、追加呼び出しは不要:

| 呼び出し元 | タイミング | Exportボタン状態 |
|-----------|----------|-----------------|
| `_execute_capture()` | キャプチャ追加後（結果クリア済み） | 無効 |
| `_on_delete_clicked()` | キャプチャ削除後（結果クリア済み） | 無効 |
| `_on_clear_all_clicked()` | 全クリア後（結果クリア済み） | 無効 |
| `stop_live_view()` | カメラ切替・タブ離脱（結果クリア済み） | 無効 |
| `_on_calibrate_clicked()` | 計算成功後 | **有効** |

注意: `_on_calibrate_clicked()` は現在 `_update_button_states()` を呼んでいない。`_update_capture_list_ui()` の呼び出しのみ。Exportボタンの状態を反映するために、`_on_calibrate_clicked()` 内の `_update_capture_list_ui()` の直後、`_status_label.setText()` の直前に `_update_button_states()` の呼び出しを挿入する。

```python
def _on_calibrate_clicked(self) -> None:
    # ... 既存処理 ...
    self._calibration_result = result
    self._display_calibration_result(result)
    self._update_capture_list_ui()
    self._update_button_states()    # 追加: Exportボタンを有効化
    self._status_label.setText(
        f"Calibration done: RMS={result.rms_error:.4f} px"
    )
```

#### 境界条件

- 結果が `None` の場合: Exportボタン無効（ボタンが押せないため `_on_export_clicked()` は呼ばれない）
- キャリブレーション成功直後: Exportボタン有効
- キャプチャ追加/削除で結果クリア: `_clear_calibration_result()` → `_update_button_states()` でExportボタン無効

---

## 5. 状態遷移

CalibrationWidget の状態遷移は feat-011 と同一。新たな状態は追加しない。

### 5.1 各状態でのUI要素の状態（Exportボタン追加）

| 状態 | Calibrate | Export | Results |
|------|-----------|--------|---------|
| Idle | 無効 | 無効 | `---` |
| Connecting | 無効 | 無効 | `---` |
| LiveView（キャプチャ0〜3件） | 無効 | 無効 | `---` |
| LiveView（4件以上、未計算） | 有効 | 無効 | `---` |
| LiveView（4件以上、計算済み） | 有効 | **有効** | 数値表示 |

---

## 6. ファイル・ディレクトリ設計

### 6.1 出力ファイル

| ファイル | 命名規則 | 形式 | エンコーディング |
|---------|---------|------|----------------|
| TOML | `{serial}_intrinsics.toml` | Pose2Sim互換TOML | UTF-8 |
| JSON | `{serial}_intrinsics.json` | JSON | UTF-8 |

### 6.2 出力先

`_ensure_save_dir()` が返す `captures/{timestamp}/intrinsics/cam{serial}/` に保存する。Save と Export で同一ディレクトリを共有する。

### 6.3 ファイル上書き

同名ファイルが存在する場合は確認なしで上書きする。

---

## 7. インターフェース定義

### 7.1 calibration_exporter.py（新規）

```python
from __future__ import annotations

import json
import logging
from pathlib import Path

from calibration_engine import CalibrationResult

logger = logging.getLogger(__name__)


class CalibrationExporter:
    """Export calibration results to Pose2Sim TOML and generic JSON."""

    def export(
        self,
        result: CalibrationResult,
        serial: str,
        image_size: tuple[int, int],
        num_images: int,
        output_dir: Path,
    ) -> list[Path]:
        """Export calibration result to TOML and JSON files.

        Args:
            result: Calibration result from CalibrationEngine.
            serial: Camera serial number.
            image_size: Image size (width, height).
            num_images: Number of captures used for calibration.
            output_dir: Directory to save files.

        Returns:
            List of created file paths [toml_path, json_path].

        Raises:
            OSError: If file write fails.

        Processing flow:
            1. Build TOML string via _build_toml()
            2. Write TOML file (OSError raises immediately)
            3. Build JSON dict via _build_json_dict()
            4. Write JSON file (OSError raises immediately)
            If step 2 fails, step 3-4 are skipped.
            If step 4 fails, the TOML file from step 2 remains on disk.
        """
        toml_path = output_dir / f"{serial}_intrinsics.toml"
        json_path = output_dir / f"{serial}_intrinsics.json"

        toml_str = self._build_toml(result, serial, image_size)
        toml_path.write_text(toml_str, encoding="utf-8")
        logger.info("TOML written: %s", toml_path)

        json_dict = self._build_json_dict(result, serial, image_size, num_images)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_dict, f, indent=2)
        logger.info("JSON written: %s", json_path)

        return [toml_path, json_path]

    def _build_toml(
        self,
        result: CalibrationResult,
        serial: str,
        image_size: tuple[int, int],
    ) -> str:
        """Build Pose2Sim-compatible TOML string."""
        ...

    def _build_json_dict(
        self,
        result: CalibrationResult,
        serial: str,
        image_size: tuple[int, int],
        num_images: int,
    ) -> dict:
        """Build JSON-serializable dict."""
        ...
```

### 7.2 ui_calibration.py（変更分のみ）

import に `CalibrationExporter` と `QFileDialog` を追加:

```python
from calibration_exporter import CalibrationExporter
```

```python
class CalibrationWidget(QWidget):
    # -- 追加UIウィジェット --
    # self._export_button: QPushButton

    # -- 追加メソッド --

    def _on_export_clicked(self) -> None:
        """Exportボタン押下時。ファイルダイアログ→エクスポート実行"""

    # -- 変更メソッド --
    # _create_ui(): Export ボタンの追加
    # _update_button_states(): Export ボタンの有効/無効を追加
    # _on_calibrate_clicked(): _update_button_states() 呼び出しを追加
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
|[Export]  ← 新規             |
|RMS: 0.1234 px              |
|fx: 1234.5                  |
|fy: 1234.5                  |
|cx: 960.0                   |
|cy: 540.0                   |
|Dist: k1=... k2=...         |
|  p1=... p2=...             |
|  k3=...                    |
+----------+------------------+
```

---

## 8. ログ・デバッグ設計

### 8.1 ログレベル使い分け

| レベル | 使い分け | 例 |
|--------|---------|-----|
| INFO | エクスポート完了 | `Exported: ['path/to/toml', 'path/to/json']` |
| ERROR | エクスポート失敗 | `Export failed: [Errno 13] Permission denied` |

### 8.2 ログ出力ポイント

| モジュール | INFO | WARNING | ERROR |
|-----------|------|---------|-------|
| calibration_exporter | TOML書き込み完了、JSON書き込み完了 | — | — |
| ui_calibration | エクスポート完了（ファイルパス） | — | エクスポート失敗 |

### 8.3 ログフォーマット

既存モジュールと同一。`logging.getLogger(__name__)` を使用し、フォーマットはアプリケーション共通設定（`[%(asctime)s] %(levelname)s %(name)s: %(message)s`、datefmt: `%H:%M:%S`）に依存する。

---

## 9. テスト方針

### 9.1 単体テスト対象

`calibration_exporter.py` の `CalibrationExporter` クラス:

- **TOML生成**:
  - 合成 `CalibrationResult` から生成されたTOML文字列がPose2Simのフォーマットに準拠すること
  - カメラセクション名が `cam_{serial}` であること
  - `name` フィールドがセクションヘッダと一致すること
  - `size` が `[width, height]` の float 配列であること
  - `matrix` が 3x3 ネスト配列であること
  - `distortions` が4要素 (k1, k2, p1, p2) であること
  - `rotation` と `translation` がゼロベクトルであること
  - `fisheye` が `false` であること
  - `metadata.error` が RMS 誤差と一致すること

- **JSON生成**:
  - 合成 `CalibrationResult` から生成されたJSONが `json.loads()` で正しくパースできること
  - `dist_coeffs` が5要素であること
  - `camera_matrix` が 3x3 ネスト配列であること
  - `image_size` が `[width, height]` の整数配列であること
  - `num_images` が指定した値と一致すること

- **ファイル出力**:
  - `export()` がTOMLとJSONの2ファイルを生成すること
  - ファイル名が `{serial}_intrinsics.toml` / `{serial}_intrinsics.json` であること
  - 存在しないディレクトリを指定した場合に OSError が発生すること

### 9.2 テストデータの生成方法

feat-011のテスト (`test_calibration_engine.py`) と同様に合成 `CalibrationResult` を作成する。

```python
# テストデータ生成の概要（意図の伝達目的、そのままコピーして使わないこと）
result = CalibrationResult(
    rms_error=0.3220,
    camera_matrix=numpy.array([
        [800.0, 0.0, 320.0],
        [0.0, 800.0, 240.0],
        [0.0, 0.0, 1.0],
    ], dtype=numpy.float64),
    dist_coeffs=numpy.array(
        [[-0.08, 0.12, -0.0003, 0.0001, 0.005]],
        dtype=numpy.float64,
    ),
    rvecs=[numpy.zeros((3, 1))],
    tvecs=[numpy.zeros((3, 1))],
    per_image_errors=[0.32],
)
```

### 9.3 TOML互換性テスト

生成されたTOML文字列をパースし、各フィールドが期待した値であることを検証する。SynchroCap環境には `toml` パッケージがインストールされていないため、TOML互換性テストでは文字列検索（`assert "[cam_" in toml_str` 等）とキー=値のパターンマッチで検証する。TOMLパーサによる厳密な検証は手動テスト時にPose2Simの `retrieve_calib_params()` で実施する。

### 9.4 統合テスト

GUIを含む統合テストは手動で実施する。テスト項目:
- キャリブレーション実行前はExportボタンが無効化されていること
- キャリブレーション実行後にExportボタンが有効化されること
- Exportボタン押下で `captures/{timestamp}/intrinsics/cam{serial}/` にTOMLとJSONが自動保存されること
- Save と Export が同じディレクトリに保存されること
- ステータスラベルにエクスポート先が表示されること
- キャプチャ追加/削除でExportボタンが無効化されること
- 生成されたTOMLファイルの内容が正しいこと
- 生成されたJSONファイルの内容が正しいこと

---

## 10. 実装時の追加更新対象

- `docs/TECH_STACK.md`: numpy の「使用箇所」列に `calibration_exporter` を追記する（`calibration_exporter.py` は opencv を直接 import しない）
- `CLAUDE.md`: ディレクトリ構成に `calibration_exporter.py` を追記する
