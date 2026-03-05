# 機能設計書: Calibration Board Settings 誤操作防止

対象: bug-007
作成日: 2026-03-05
基準文書: `docs/DESIGN_STANDARD.md`
要求仕様書: `docs/issues/bug-007-calibration-spinbox-wheel-scroll/requirements.md`

---

## 1. 対応要求マッピング

| 要求ID | 要求名 | 設計セクション |
|--------|--------|---------------|
| FR-001 | Board Settings の値表示を読み取り専用にする | 4.1 |
| FR-002 | クリックでダイアログを開き設定変更する | 4.2 |

---

## 2. システム構成

### 2.1 関連ファイル

| ファイル | 役割 | 変更種別 |
|---------|------|---------|
| `src/synchroCap/ui_calibration.py` | Board Settings UI の変更 | **変更** |
| `src/synchroCap/ui_camera_settings.py` | ダイアログ方式の参考（変更なし） | 参考のみ |

### 2.2 モジュール間の依存関係

変更は `ui_calibration.py` 内で完結する。他モジュールへの影響なし。

---

## 3. 技術スタック

既存技術スタックの範囲内。追加ライブラリなし。
import に `QDialog`, `QDialogButtonBox`, `QPushButton` を追加する。

---

## 4. 詳細設計

### 4.1 Board Settings の値表示を読み取り専用にする（FR-001）

#### 変更概要

Board Settings パネル内の編集可能ウィジェット（QComboBox, QSpinBox, QDoubleSpinBox）を、読み取り専用の QPushButton に置き換える。QPushButton にした理由は、クリック可能であることが視覚的に明確で、クリックイベントのハンドリングが容易なため。QLabelではクリック可能であることがユーザーに伝わらない。

#### UI構成の変更

| 項目 | 変更前 | 変更後 | 変数名 |
|------|--------|--------|--------|
| Type | `QComboBox` | `QPushButton` | `self._type_button` |
| Columns | `QSpinBox` | `QPushButton` | `self._cols_button` |
| Rows | `QSpinBox` | `QPushButton` | `self._rows_button` |
| Square size | `QDoubleSpinBox` | `QPushButton` | `self._square_button` |
| Marker size | `QDoubleSpinBox` | `QPushButton` | `self._marker_button` |

#### 値の内部管理

SpinBox を削除するため、設定値はインスタンス変数で保持する。`__init__` 内で初期化する。

```python
self._board_type: str = "charuco"
self._cols: int = 5
self._rows: int = 7
self._square_mm: float = 30.0
self._marker_mm: float = 22.0
```

#### ボタンのテキスト表示フォーマット

| 項目 | フォーマット | 例 |
|------|------------|-----|
| Type | `"{type}"` | `"ChArUco"` |
| Columns | `"{value}"` | `"5"` |
| Rows | `"{value}"` | `"7"` |
| Square size | `"{value:.1f} mm"` | `"30.0 mm"` |
| Marker size | `"{value:.1f} mm"` | `"22.0 mm"` |

#### Marker size のグレーアウト

board_type が `"checkerboard"` の場合、`self._marker_button.setEnabled(False)` とする。`"charuco"` の場合は `setEnabled(True)` とする。この切り替えは Type 変更時に行う。

#### _create_ui の変更後の構成

```python
# Board settings panel
board_group = QGroupBox("Board Settings")
board_form = QFormLayout(board_group)

self._type_button = QPushButton("ChArUco")
self._type_button.clicked.connect(self._on_type_button_clicked)
board_form.addRow("Type:", self._type_button)

self._cols_button = QPushButton("5")
self._cols_button.clicked.connect(self._on_cols_button_clicked)
board_form.addRow("Columns:", self._cols_button)

self._rows_button = QPushButton("7")
self._rows_button.clicked.connect(self._on_rows_button_clicked)
board_form.addRow("Rows:", self._rows_button)

self._square_button = QPushButton("30.0 mm")
self._square_button.clicked.connect(self._on_square_button_clicked)
board_form.addRow("Square size:", self._square_button)

self._marker_button = QPushButton("22.0 mm")
self._marker_button.clicked.connect(self._on_marker_button_clicked)
board_form.addRow("Marker size:", self._marker_button)
```

### 4.2 ダイアログによる設定変更（FR-002）

#### 共通パターン

各ダイアログは以下の共通構造を持つ:

1. `QDialog` を生成（parent=self）
2. タイトルを設定
3. 入力ウィジェットを配置（現在値を初期値として設定）
4. `QDialogButtonBox`（OK / Cancel）を配置
5. `dlg.exec()` でモーダル表示
6. OK の場合: 値をインスタンス変数に保存 → ボタンテキストを更新 → `_apply_board_config()` を呼び出す
7. Cancel の場合: 何もしない

#### _apply_board_config メソッド（新規）

既存の `_on_board_config_changed` を置き換える。marker_mm の制約チェックと BoardDetector 再初期化を行う。

```python
def _apply_board_config(self) -> None:
    """Apply current board config to detector. Enforce marker_mm < square_mm."""
    # Enforce marker_mm < square_mm
    if self._marker_mm >= self._square_mm:
        self._marker_mm = max(1.0, self._square_mm - 1.0)
        if self._square_mm < 2.0:
            self._marker_mm = 1.0
        self._marker_button.setText(f"{self._marker_mm:.1f} mm")
        logger.info("marker_mm adjusted to %.1f", self._marker_mm)

    # Enable/disable marker button based on board type
    self._marker_button.setEnabled(self._board_type == "charuco")

    self._detector.reconfigure(
        self._board_type, self._cols, self._rows,
        self._square_mm, self._marker_mm,
    )
```

#### 各ダイアログの詳細

##### Type ダイアログ

```python
def _on_type_button_clicked(self) -> None:
    dlg = QDialog(self)
    dlg.setWindowTitle("Board Type")
    layout = QVBoxLayout(dlg)

    combo = QComboBox()
    combo.addItems(["ChArUco", "Checkerboard"])
    combo.setCurrentIndex(0 if self._board_type == "charuco" else 1)
    layout.addWidget(combo)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return

    self._board_type = "charuco" if combo.currentIndex() == 0 else "checkerboard"
    self._type_button.setText("ChArUco" if self._board_type == "charuco" else "Checkerboard")
    self._apply_board_config()
```

##### Columns ダイアログ

```python
def _on_cols_button_clicked(self) -> None:
    dlg = QDialog(self)
    dlg.setWindowTitle("Columns")
    layout = QVBoxLayout(dlg)

    spin = QSpinBox()
    spin.setRange(3, 20)
    spin.setValue(self._cols)
    layout.addWidget(spin)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return

    self._cols = spin.value()
    self._cols_button.setText(str(self._cols))
    self._apply_board_config()
```

##### Rows ダイアログ

Columns ダイアログと同一構造。変数名を `self._rows` / `self._rows_button` に置き換え、タイトルを `"Rows"` にする。

##### Square size ダイアログ

```python
def _on_square_button_clicked(self) -> None:
    dlg = QDialog(self)
    dlg.setWindowTitle("Square Size")
    layout = QVBoxLayout(dlg)

    spin = QDoubleSpinBox()
    spin.setRange(1.0, 200.0)
    spin.setSingleStep(0.5)
    spin.setSuffix(" mm")
    spin.setValue(self._square_mm)
    layout.addWidget(spin)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return

    self._square_mm = spin.value()
    self._square_button.setText(f"{self._square_mm:.1f} mm")
    self._apply_board_config()
```

##### Marker size ダイアログ

Square size ダイアログと同一構造。変数名を `self._marker_mm` / `self._marker_button` に置き換え、タイトルを `"Marker Size"` にする。

#### 削除するメソッド

- `_on_board_config_changed` — `_apply_board_config` に置き換わるため削除

#### 削除するimport

- `QSpinBox`, `QDoubleSpinBox`, `QComboBox` は**削除しない**（ダイアログ内で使用するため引き続き必要）

#### 追加するimport

`QDialog`, `QDialogButtonBox`, `QPushButton` を既存の import ブロックに追加する。

---

## 5. エラーハンドリング

なし。ダイアログのキャンセルは通常フローとして処理する。

---

## 6. ログ・デバッグ設計

既存のログ出力を維持する:
- `_apply_board_config` 内の `marker_mm adjusted` ログ（INFO）
- `BoardDetector.reconfigure` 内の `Board config` ログ（INFO）

追加ログなし。
