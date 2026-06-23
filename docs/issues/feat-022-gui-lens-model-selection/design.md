# 機能設計書: feat-022 GUI Calibration - Lens Model Selection (Normal / Wide)

## 1.1 対応要求マッピング

| 要求ID | 設計セクション |
|---|---|
| FR-001 | 1.4.1 (選択UI + ダイアログ) |
| FR-002 | 1.4.2 (calibrate 呼び出し変更) |
| FR-003 | 1.4.3 (永続化) |
| FR-004 | 1.4.4 (結果表示のモデル対応) |

## 1.2 システム構成

```
src/synchroCap/ui_calibration.py       # 変更: Lens選択UI、calibrate呼び出し、永続化、結果表示
src/synchroCap/board_settings_store.py # 変更なし（ジェネリックdict保存。docstring追記のみ任意）
src/synchroCap/calibration_engine.py   # 変更なし（lens_model 引数は feat-019 で実装済み）
src/synchroCap/calibration_exporter.py # 変更なし（係数長に非依存。配列長は自動追従）
tests/test_ui_calibration_lens.py      # 追加: 永続化ラウンドトリップ等のロジックテスト
```

依存方向は既存と同じ（`ui_calibration.py` → `calibration_engine.py` / `board_settings_store.py`）。循環依存なし。

## 1.3 技術スタック

- Python 3.10 / PySide6（既存）
- OpenCV（`CalibrationEngine` 経由、既存）
- 新規ライブラリなし（`TECH_STACK.md` 更新不要）

## 1.4 各機能の詳細設計

### 1.4.1 選択UI + ダイアログ（FR-001）

#### 状態変数

`__init__` の Board Settings 初期化部（`self._board_type`〜`self._marker_mm`、現状110-114行）に追加:

```python
self._lens_model: str = "normal"   # "normal" | "wide"（GUI初期値=normal）
```

直後の `_load_board_settings()`（122行）で永続値があれば上書きされる（1.4.3）。

**初期化順序（重要）**: `__init__` は `_create_ui()`（148行）→ `_update_board_settings_ui()`（151行）の順で呼ぶ。`_lens_button` は `_create_ui()` 内の Board Settings 構築部（後述、224-245行付近）で生成されるため、151行の `_update_board_settings_ui()` で `_lens_button.setText()` を呼ぶ時点では既に生成済みであり問題ない（既存の `_type_button` 等と同じ）。実装時はこの順序を崩さないこと。

#### UI構築

Board Settings GroupBox（現状224-245行）の Marker size 行の後に Lens 行を追加:

```python
self._lens_button = QPushButton("Normal")
self._lens_button.clicked.connect(self._on_lens_button_clicked)
board_form.addRow("Lens:", self._lens_button)
```

#### ダイアログ（既存 `_on_type_button_clicked` と同一パターン）

```python
def _on_lens_button_clicked(self) -> None:
    dlg = QDialog(self)
    dlg.setWindowTitle("Lens Type")
    layout = QVBoxLayout(dlg)

    combo = QComboBox()
    combo.addItems(["Normal", "Wide-Angle"])
    combo.setCurrentIndex(0 if self._lens_model == "normal" else 1)
    layout.addWidget(combo)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return

    self._lens_model = "normal" if combo.currentIndex() == 0 else "wide"
    self._lens_button.setText(self._lens_label())
    self._save_board_settings()
```

ヘルパ（表示文字列の一元化）:

```python
def _lens_label(self) -> str:
    return "Normal" if self._lens_model == "normal" else "Wide-Angle"
```

`_update_board_settings_ui()`（現状825-831行）に1行追加:

```python
self._lens_button.setText(self._lens_label())
```

設計判断: Lens選択は `_apply_board_config()`（detector へのボード設定反映）を呼ばない。`lens_model` は検出ではなくキャリブレーション計算時にのみ使う値であり、ボード検出パラメータと無関係なため。Type選択と異なり `_apply_board_config()` は不要。

### 1.4.2 calibrate 呼び出し変更（FR-002）

現状（641-645行）:

```python
result = self._calibration_engine.calibrate(
    object_points_list,
    image_points_list,
    self._capture_image_size,
)
```

変更後:

```python
result = self._calibration_engine.calibrate(
    object_points_list,
    image_points_list,
    self._capture_image_size,
    lens_model=self._lens_model,
)
```

エンジンは feat-019 で `lens_model` をサポート済み。`normal` → 5係数、`wide` → 8係数を返す。エクスポート（`calibration_exporter.py`）は `dist_coeffs.flatten()` で全要素を列挙するため配列長に自動追従し、変更不要。

### 1.4.3 永続化（FR-003）

#### 保存

`_save_board_settings()`（現状789-797行）の dict に `lens_model` を追加:

```python
self._board_settings_store.save({
    "board_type": self._board_type,
    "cols": self._cols,
    "rows": self._rows,
    "square_mm": self._square_mm,
    "marker_mm": self._marker_mm,
    "lens_model": self._lens_model,
})
```

#### 読み込み

バリデーションは**静的ヘルパに切り出して**テスト可能にする（bug-009 の `_is_collinear` 静的ヘルパと同じ前例）。`_load_board_settings()` がインスタンスメソッドかつ Qt ウィジェットに密結合しており、純関数なしでは tests/1.9 のテスト2/3 が QWidget インスタンス化を要し実質テスト不能になるため。

```python
@staticmethod
def _validate_lens_model(value) -> str:
    """Return value if it is a valid lens_model, else default "normal"."""
    return value if value in ("normal", "wide") else "normal"
```

`_load_board_settings()`（現状799-823行）に他キーと同じ位置で読み込みを追加:

```python
self._lens_model = self._validate_lens_model(data.get("lens_model"))
# None / 不正値はヘルパ内で "normal" にフォールバック（GUI初期値=normal、後方互換）
```

`BoardSettingsStore.save()` の docstring 引数説明（現状52行、キーを明示列挙している）に `lens_model` を追記する（**必須**: 追記しないと既存 docstring が不正確になる）。`board_settings_store.py` 本体のロジック変更はなし。

### 1.4.4 結果表示のモデル対応（FR-004）

**重要**: 現状の `_display_calibration_result()`（703-709行）は `d[0]`〜`d[7]` を固定インデックスで参照しており、`normal`（5係数）では `d[5]` で `IndexError` が発生する。配列長に追従する表示へ変更する。

変更後（係数数に応じてラベルを動的生成）:

```python
d = result.dist_coeffs.flatten()
labels = ["k1", "k2", "p1", "p2", "k3", "k4", "k5", "k6"]
parts = [f"{labels[i]}={d[i]:.4f}" for i in range(len(d))]
# 2項目ずつ改行して表示（既存の2列レイアウトを踏襲）
lines = [", ".join(parts[i:i + 2]) for i in range(0, len(parts), 2)]
self._dist_label.setText("\n".join(lines))
```

- `len(d)` は normal=5、wide=8。`labels` は最大8個を用意し、`range(len(d))` で打ち切る。
- 5係数時は `k1,k2 / p1,p2 / k3` の3行、8係数時は従来同様4行表示となる。

### 1.4.5 ダイアログ Cancel 時の挙動（FR-001 受け入れ基準）

`dlg.exec() != Accepted` で早期 return するため、Cancel 時は `self._lens_model` もボタン表示も変更されない（既存 Type ダイアログと同一）。

## 1.5 状態遷移

なし（選択値は単純な永続フィールド。計算ボタン押下時に参照されるのみ）。

## 1.6 ファイル・ディレクトリ設計

- 永続化先: `board_settings.json`（既存、`appdata/board_settings.json`）。`lens_model` キーを追加。
- エクスポート出力（TOML/JSON）のパス・キー名は変更なし。`distortions`/`dist_coeffs` の配列長のみ選択に追従。

## 1.7 インターフェース定義

| シンボル | シグネチャ / 変更内容 |
|---|---|
| `CalibrationView._lens_model` | `str` フィールド追加（`"normal"`/`"wide"`、初期値 `"normal"`） |
| `CalibrationView._on_lens_button_clicked` | 新規メソッド `(self) -> None` |
| `CalibrationView._lens_label` | 新規ヘルパ `(self) -> str` |
| `CalibrationView._validate_lens_model` | 新規静的ヘルパ `@staticmethod (value) -> str`（不正/欠落は `"normal"`） |
| `CalibrationView._save_board_settings` | 保存 dict に `lens_model` 追加 |
| `CalibrationView._load_board_settings` | `lens_model` のバリデーション付き読み込み追加 |
| `CalibrationView._update_board_settings_ui` | `_lens_button` テキスト更新を追加 |
| `CalibrationView._display_calibration_result` | 配列長に追従する歪み表示へ変更 |
| `CalibrationEngine.calibrate` | 変更なし（呼び出し側で `lens_model` を渡す） |

注: クラス名は実装ファイルの実際の名称に合わせること（`ui_calibration.py` の Tab5 ビュークラス）。行番号はすべて執筆時点の目安であり、実装時はシンボル名で対象を特定すること。

## 1.8 ログ・デバッグ設計

- Lens選択変更時のログは**出さない**（既存の Type/Cols/Rows 変更がログを出していないため、それに統一する）。
- 計算時のモデル名は `CalibrationEngine` 側の既存 INFO ログ（`model=%s`）で確認できる。

## 1.9 テスト設計

GUIウィジェットの完全な起動は実機/Qt環境依存のため、自動テストは**ロジック単位**に絞る。

`tests/test_ui_calibration_lens.py`（新規）または既存テストに追加:

1. `test_board_settings_store_roundtrip_lens_model` — `BoardSettingsStore.save({..., "lens_model": "normal"})` → `load()` で `lens_model == "normal"` が復元される（store はジェネリックなので実質既存挙動の確認）。
2. `test_validate_lens_model_missing_defaults_normal` — `_validate_lens_model(None)` → `"normal"`（欠落時=初期値normal）。静的ヘルパ（1.4.3）を直接テストするため QWidget 不要。
3. `test_validate_lens_model_invalid_defaults_normal` — `_validate_lens_model("fisheye")` → `"normal"`。
4. `test_validate_lens_model_valid_passthrough` — `_validate_lens_model("normal")` → `"normal"`、`_validate_lens_model("wide")` → `"wide"`。

`CalibrationEngine` 側の normal/wide 係数長は feat-019 のテストで担保済みのため再掲しない。`_display_calibration_result` の動的表示は、可能なら `dist_coeffs` 5要素/8要素のダミー `CalibrationResult` を渡して `IndexError` が出ないことを確認する（QLabel が必要なため、Qt環境が前提。困難なら手動テストで確認）。

テスト実行: `micromamba run -n SynchroCap pytest -v`（Subagent で実行）。結果は `tests/results/feat-022_test_result.txt` に保存する。

## 1.10 手動テスト項目（実機）

1. Tab5 起動（lens_model 未保存時）→ Board Settings に「Lens: Normal」が表示される（初期値=Normal）。
2. Lens行クリック → ダイアログで Wide-Angle 選択 → OK → ボタンが「Wide-Angle」に変わる。Normal に戻すと「Normal」に戻る。
3. Normal でキャプチャ4枚以上 → Calibrate → 歪み表示が5係数（k1,k2,p1,p2,k3）になる。
4. Wide-Angle にして Calibrate → 8係数表示になる。
5. アプリ再起動 → 前回の Lens 選択が保持されている。
6. Cancel 動作: ダイアログで変更して Cancel → 選択が変わらない。
7. エクスポート追従（FR-002）: Normal でエクスポート → TOML の `distortions` / JSON の `dist_coeffs` が5要素。Wide-Angle でエクスポート → 8要素。
