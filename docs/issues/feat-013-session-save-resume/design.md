# 機能設計書: Camera Calibration - Session Save/Resume (Board Settings)

対象: feat-013
作成日: 2026-03-18
基準文書: `docs/DESIGN_STANDARD.md`
要求仕様書: `docs/issues/feat-013-session-save-resume/requirements.md`

---

## 1. 対応要求マッピング

| 要求ID | 要求名 | 設計セクション |
|--------|--------|---------------|
| FR-001 | Board Settings の自動保存 | 4.1 |
| FR-002 | Board Settings の自動復元 | 4.2 |

---

## 2. システム構成

### 2.1 関連ファイル

| ファイル | 役割 | 変更種別 |
|---------|------|---------|
| `src/synchroCap/board_settings_store.py` | Board Settings の永続化ストア | **新規作成** |
| `src/synchroCap/ui_calibration.py` | Tab5 CalibrationWidget（保存/復元の呼び出し追加） | **変更** |

### 2.2 モジュール間の依存関係

```
ui_calibration.py (変更)
  +-- board_settings_store.py (新規)
  |     +-- json (Python標準)
  |     +-- pathlib
  +-- (その他既存モジュール)
```

循環依存は存在しない。`board_settings_store.py` は `json` と `pathlib` のみに依存する。

### 2.3 ディレクトリ構成

```
src/synchroCap/
+-- board_settings_store.py              # 新規
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
| json | Python標準 | JSON読み書き | 標準ライブラリのため追加不要 |
| pathlib | Python標準 | ファイルパス操作 | 標準ライブラリのため追加不要 |
| PySide6 | ==6.8.3 | QStandardPaths（保存先ディレクトリ取得） | 既存 |

新規外部ライブラリの追加なし。

**設計判断**: ストアクラスの設計パターン
- 採用: `BoardSettingsStore` として独立クラスを新規作成する。`CameraSettingsStore`（`ui_camera_settings.py` L38-96）と同じ設計パターン（ファイルパスを受け取り、load/save メソッドを持つ）を踏襲する
- 却下: `CameraSettingsStore` を汎用化して共用する（Camera Settings はデバイスシリアルをキーとする複雑な構造であり、Board Settings の単純なグローバル設定とは構造が異なる。共用化は不要な複雑さを導入する）
- 却下: `ui_calibration.py` 内に保存ロジックを直接記述する（テスタビリティが低下する）

---

## 4. 各機能の詳細設計

### 4.1 Board Settings の自動保存（FR-001）

#### データフロー

- 入力: Board Settings の5項目（`board_type`, `cols`, `rows`, `square_mm`, `marker_mm`）
- 出力: `{AppDataLocation}/board_settings.json` ファイル

#### JSONファイル形式

```json
{
  "board_type": "charuco",
  "cols": 5,
  "rows": 7,
  "square_mm": 30.0,
  "marker_mm": 22.0
}
```

#### 処理ロジック

Board Settings の各ダイアログ（`_on_type_button_clicked`, `_on_cols_button_clicked`, `_on_rows_button_clicked`, `_on_square_button_clicked`, `_on_marker_button_clicked`）の OK 押下後、`_apply_board_config()` が呼ばれた後に `_save_board_settings()` を呼び出す。

```python
def _save_board_settings(self) -> None:
    """Save current board settings to persistent storage."""
    self._board_settings_store.save({
        "board_type": self._board_type,
        "cols": self._cols,
        "rows": self._rows,
        "square_mm": self._square_mm,
        "marker_mm": self._marker_mm,
    })
```

5つの既存ダイアログメソッドの末尾（`_apply_board_config()` の直後）に `self._save_board_settings()` を追加する:

| メソッド | 追加位置 |
|---------|---------|
| `_on_type_button_clicked()` | L804 `_apply_board_config()` の直後 |
| `_on_cols_button_clicked()` | L828 `_apply_board_config()` の直後 |
| `_on_rows_button_clicked()` | L852 `_apply_board_config()` の直後 |
| `_on_square_button_clicked()` | L878 `_apply_board_config()` の直後 |
| `_on_marker_button_clicked()` | L904 `_apply_board_config()` の直後 |

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| ファイル書き込み失敗 | `BoardSettingsStore.save()` 内で Exception catch | ログ出力のみ。設定変更自体は成功している | WARNING |

### 4.2 Board Settings の自動復元（FR-002）

#### データフロー

- 入力: `{AppDataLocation}/board_settings.json` ファイル
- 出力: 内部変数（`_board_type`, `_cols`, `_rows`, `_square_mm`, `_marker_mm`）とUIボタンテキストの更新

#### 処理ロジック

`CalibrationWidget.__init__()` で、Board Settings のデフォルト値設定直後に復元処理を実行する。

```python
def _load_board_settings(self) -> None:
    """Load board settings from persistent storage."""
    data = self._board_settings_store.load()
    if data is None:
        return  # No saved settings, keep defaults

    # Validate and restore each value (invalid → keep default)
    bt = data.get("board_type")
    if bt in ("charuco", "checkerboard"):
        self._board_type = bt

    cols = data.get("cols")
    if isinstance(cols, int) and 3 <= cols <= 20:
        self._cols = cols

    rows = data.get("rows")
    if isinstance(rows, int) and 3 <= rows <= 20:
        self._rows = rows

    sq = data.get("square_mm")
    if isinstance(sq, (int, float)) and 1.0 <= sq <= 200.0:
        self._square_mm = float(sq)

    mk = data.get("marker_mm")
    if isinstance(mk, (int, float)) and 1.0 <= mk <= 200.0:
        self._marker_mm = float(mk)
```

`__init__()` での挿入位置: L111（`self._marker_mm = 22.0`）の直後、L114（`self._detector = BoardDetector()`）の直前。パス構築は `CalibrationWidget.__init__()` 内で `QStandardPaths` を呼ぶ（シグネチャ変更不要）:

```python
# Board settings (internal state) — defaults
self._board_type: str = "charuco"
self._cols: int = 5
self._rows: int = 7
self._square_mm: float = 30.0
self._marker_mm: float = 22.0

# Persistent storage — insert after L111, before L114
appdata = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
board_settings_path = os.path.join(appdata, "board_settings.json")
self._board_settings_store = BoardSettingsStore(board_settings_path)
self._load_board_settings()  # Override defaults with saved values

# Board detector (existing L114)
self._detector = BoardDetector()
```

`_create_ui()` 内のボタンテキストはハードコードされたデフォルト値（`"ChArUco"`, `"5"`, `"7"`, `"30.0 mm"`, `"22.0 mm"`）で初期化されるため、`_load_board_settings()` で内部変数を復元しただけではUIに反映されない。`_create_ui()` の後にボタンテキストを明示的に更新する `_update_board_settings_ui()` メソッドを追加する:

```python
def _update_board_settings_ui(self) -> None:
    """Update board settings button texts from internal state."""
    self._type_button.setText("ChArUco" if self._board_type == "charuco" else "Checkerboard")
    self._cols_button.setText(str(self._cols))
    self._rows_button.setText(str(self._rows))
    self._square_button.setText(f"{self._square_mm:.1f} mm")
    self._marker_button.setText(f"{self._marker_mm:.1f} mm")
```

`_apply_board_config()` は `self._detector`（L114で初期化済み）と `self._marker_button`（`_create_ui()` 内で作成）を参照するため、`_create_ui()` の後に呼ぶ必要がある。`self._create_ui()`（L137）の直後に `_update_board_settings_ui()` と `_apply_board_config()` を追加する。初回起動（デフォルト値）の場合でも呼ぶことで、ボタンテキストと `_marker_button` の有効/無効状態を `board_type` に応じて正しく設定する:

```python
self._create_ui()  # existing L137

# Apply restored board settings to UI and detector
self._update_board_settings_ui()
self._apply_board_config()
```

#### 境界条件

| ケース | 振る舞い |
|--------|---------|
| 設定ファイルが存在しない | デフォルト値を使用（初回起動と同一） |
| JSONパースエラー | デフォルト値を使用。WARNING ログ出力 |
| 一部のキーが欠落 | 欠落キーはデフォルト値を使用。存在するキーは復元 |
| 値が範囲外（例: cols=100） | 当該キーのデフォルト値を使用。`_load_board_settings()` 内でバリデーション済み |
| 値の型が不正（例: cols="abc"） | 当該キーのデフォルト値を使用。`isinstance()` チェックで除外される |

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| ファイル読み込み失敗 | `BoardSettingsStore.load()` 内で Exception catch | None を返す → デフォルト値使用 | WARNING |
| JSONパースエラー | `json.load()` の JSONDecodeError catch | None を返す → デフォルト値使用 | WARNING |

---

## 5. 状態遷移

本案件で新たな状態は追加しない。`__init__()` での復元と、ダイアログOK時の保存のみ。

---

## 6. ファイル・ディレクトリ設計

### 6.1 保存ファイル

| 項目 | 値 |
|------|-----|
| ファイル名 | `board_settings.json` |
| ディレクトリ | `QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)`（`~/.local/share/synchroCap/`） |
| フォーマット | JSON、UTF-8、indent=2 |
| エンコーディング | UTF-8 |

### 6.2 JSONスキーマ

| キー | 型 | デフォルト値 | 値域 |
|------|-----|------------|------|
| `board_type` | str | `"charuco"` | `"charuco"`, `"checkerboard"` |
| `cols` | int | 5 | 3〜20 |
| `rows` | int | 7 | 3〜20 |
| `square_mm` | float | 30.0 | 1.0〜200.0 |
| `marker_mm` | float | 22.0 | 1.0〜200.0 |

---

## 7. インターフェース定義

### 7.1 board_settings_store.py（新規）

```python
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class BoardSettingsStore:
    """Persistent storage for board settings.

    Follows the same design pattern as CameraSettingsStore
    (ui_camera_settings.py L38-96).
    """

    def __init__(self, path: str) -> None:
        """Initialize.

        Args:
            path: Full path to the JSON settings file.
        """
        self._path = Path(path)

    def load(self) -> Optional[dict]:
        """Load board settings from JSON file.

        Returns:
            Dict with board settings keys, or None if file
            does not exist or cannot be parsed.
        """
        if not self._path.exists():
            return None
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            logger.warning("board_settings.json: root is not an object")
            return None
        except Exception as e:
            logger.warning("Failed to load board settings: %s", e)
            return None

    def save(self, settings: dict) -> bool:
        """Save board settings to JSON file.

        Args:
            settings: Dict with board_type, cols, rows, square_mm, marker_mm.

        Returns:
            True if saved successfully, False otherwise.
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=True, indent=2)
            logger.info("Board settings saved: %s", self._path)
            return True
        except Exception as e:
            logger.warning("Failed to save board settings: %s", e)
            return False
```

### 7.2 ui_calibration.py（変更分のみ）

import に `BoardSettingsStore` と `QStandardPaths` を追加:

```python
from PySide6.QtCore import Qt, QTimer, QStandardPaths
from board_settings_store import BoardSettingsStore
```

既存の `from PySide6.QtCore import Qt, QTimer` に `QStandardPaths` を追加する。`os` モジュールのインポートも追加する（`os.path.join` で使用）。

```python
class CalibrationWidget(QWidget):
    # -- 追加メンバー変数（__init__）--
    # self._board_settings_store: BoardSettingsStore

    # -- 追加メソッド --

    def _save_board_settings(self) -> None:
        """Save current board settings to persistent storage."""

    def _load_board_settings(self) -> None:
        """Load board settings from persistent storage."""

    def _update_board_settings_ui(self) -> None:
        """Update board settings button texts from internal state."""

    # -- 変更メソッド --
    # __init__(): BoardSettingsStore 初期化、_load_board_settings() 呼び出し、_update_board_settings_ui() + _apply_board_config() 呼び出し追加
    # _on_type_button_clicked(): _save_board_settings() 呼び出し追加
    # _on_cols_button_clicked(): _save_board_settings() 呼び出し追加
    # _on_rows_button_clicked(): _save_board_settings() 呼び出し追加
    # _on_square_button_clicked(): _save_board_settings() 呼び出し追加
    # _on_marker_button_clicked(): _save_board_settings() 呼び出し追加
```

---

## 8. ログ・デバッグ設計

### 8.1 ログレベル使い分け

| レベル | 使い分け | 例 |
|--------|---------|-----|
| INFO | 保存成功 | `Board settings saved: /home/user/.local/share/synchroCap/board_settings.json` |
| WARNING | 読み込み/保存失敗 | `Failed to load board settings: [Errno 2] No such file or directory` |

### 8.2 ログ出力ポイント

| モジュール | INFO | WARNING |
|-----------|------|---------|
| board_settings_store | 保存成功 | 読み込み失敗、保存失敗、JSONパースエラー |

### 8.3 ログフォーマット

既存モジュールと同一。`logging.getLogger(__name__)` を使用。

---

## 9. テスト方針

### 9.1 単体テスト対象

`board_settings_store.py` の `BoardSettingsStore` クラス:

- **save/load 正常系**:
  - 設定を保存し、再度読み込んだ値が一致すること
  - 全5キー（board_type, cols, rows, square_mm, marker_mm）が保存・復元されること

- **load 異常系**:
  - ファイルが存在しない場合は None を返すこと
  - JSONパースエラー（壊れたファイル）の場合は None を返すこと
  - ルートがオブジェクトでない場合は None を返すこと

- **save 異常系**:
  - 存在しないディレクトリの場合、親ディレクトリを自動作成して保存できること
  - 書き込み権限がない場合は False を返すこと

- **部分キー**:
  - 一部のキーのみ保存した場合、load で欠落キーが含まれないことを確認

### 9.2 統合テスト

手動で実施:
- アプリ起動 → Calibrationタブで Board Settings を変更 → アプリ終了 → 再起動 → 変更した値が復元されていること
- `board_settings.json` を手動削除 → アプリ起動 → デフォルト値が表示されること
- Board Type, Columns, Rows, Square Size, Marker Size のそれぞれを変更してアプリ再起動 → 各値が復元されること
- Camera Settings タブでカメラ設定を変更 → アプリ再起動 → Camera Settings の設定が従来通り正常に復元されていること（回帰確認）

---

## 10. 実装時の追加更新対象

- `CLAUDE.md`: ディレクトリ構成に `board_settings_store.py` を追記する
