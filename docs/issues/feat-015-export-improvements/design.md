# 機能設計書: Export Improvements - Naming Convention & Completion Notification

対象: feat-015
作成日: 2026-03-20
基準文書: `docs/DESIGN_STANDARD.md`
要求仕様書: `docs/issues/feat-015-export-improvements/requirements.md`

---

## 1. 対応要求マッピング

| 要求ID | 要求名 | 設計セクション |
|--------|--------|---------------|
| FR-001 | ファイル名の `cam{serial}` 統一 | 4.1 |
| FR-002 | TOML内カメラ名の `cam{serial}` 統一 | 4.2 |
| FR-003 | エクスポート完了ポップアップ | 4.3 |

---

## 2. システム構成

### 2.1 関連ファイル

| ファイル | 役割 | 変更種別 |
|---------|------|---------|
| `src/synchroCap/calibration_exporter.py` | エクスポートエンジン | **変更** |
| `src/synchroCap/ui_calibration.py` | Tab5 CalibrationWidget（ポップアップ追加） | **変更** |
| `tests/test_calibration_exporter.py` | エクスポーターテスト | **変更** |

---

## 3. 技術スタック

既存と同一。新規ライブラリの追加なし。`QMessageBox` は PySide6.QtWidgets に含まれる。

---

## 4. 各機能の詳細設計

### 4.1 ファイル名の `cam{serial}` 統一（FR-001）

#### 変更箇所

`calibration_exporter.py` `export()` メソッド内のファイル名生成部分を変更する。

変更前:
```python
toml_path = output_dir / f"{serial}_intrinsics.toml"
json_path = output_dir / f"{serial}_intrinsics.json"
```

変更後:
```python
toml_path = output_dir / f"cam{serial}_intrinsics.toml"
json_path = output_dir / f"cam{serial}_intrinsics.json"
```

### 4.2 TOML内カメラ名の `cam{serial}` 統一（FR-002）

#### 変更箇所

`calibration_exporter.py` `_build_toml()` メソッド内の `cam_name` 生成を変更する。

変更前:
```python
cam_name = f"cam_{serial}"
```

変更後:
```python
cam_name = f"cam{serial}"
```

これにより、TOMLのセクション名 `[cam{serial}]` と `name` フィールド `"cam{serial}"` が自動的に変更される（`_build_toml()` 内のセクション名行と `name` フィールド行は `cam_name` 変数を参照しているため）。

### 4.3 エクスポート完了ポップアップ（FR-003）

#### 変更箇所

`ui_calibration.py` の `_on_export_clicked()` メソッドのエクスポート成功後に `QMessageBox.information()` を追加する。

変更前（`_on_export_clicked()` 末尾）:
```python
self._status_label.setText(f"Exported to {export_dir}")
logger.info("Exported: %s", [str(p) for p in paths])
```

変更後:
```python
resolved = export_dir.resolve()
self._status_label.setText(f"Exported to {resolved}")
logger.info("Exported: %s", [str(p) for p in paths])

QMessageBox.information(
    self,
    "Export Complete",
    f"Exported to:\n{resolved}",
)
```

ステータスラベルとポップアップの両方で `resolve()` による絶対パスを表示する（表示の一貫性のため）。

`export_dir.resolve()` でCWD基準の絶対パスに変換して表示する（`_ensure_save_dir()` は `Path("captures") / ...` の相対パスを返すため、`resolve()` でフルパスに変換する）。

#### エラーハンドリング

エクスポート失敗時（`OSError` 発生時）は既存の try-except ブロックで `return` されるため、`QMessageBox.information()` には到達しない。したがって、エクスポート失敗時にポップアップは表示されない。

#### import 追加

`ui_calibration.py` の既存 `from PySide6.QtWidgets import (...)` ブロックに `QMessageBox` を追加する。

---

## 5. 状態遷移

変更なし。

---

## 6. ファイル・ディレクトリ設計

### 6.1 変更後のファイル名

| 変更前 | 変更後 |
|--------|--------|
| `{serial}_intrinsics.toml` | `cam{serial}_intrinsics.toml` |
| `{serial}_intrinsics.json` | `cam{serial}_intrinsics.json` |

例: シリアル `49710379` の場合
- `cam49710379_intrinsics.toml`
- `cam49710379_intrinsics.json`

---

## 7. インターフェース定義

### 7.1 calibration_exporter.py（変更分のみ）

公開メソッド `export()` のシグネチャは変更なし。戻り値のファイルパスが変わるのみ。

### 7.2 ui_calibration.py（変更分のみ）

`_on_export_clicked()` に `QMessageBox.information()` を追加。

---

## 8. ログ・デバッグ設計

変更なし。

---

## 9. テスト方針

### 9.1 単体テスト: calibration_exporter.py

`tests/test_calibration_exporter.py` を更新する:

- `test_file_names`: 期待するファイル名を `{SERIAL}_intrinsics.toml` → `cam{SERIAL}_intrinsics.toml` に変更
- `test_contains_camera_section`: `[cam_{SERIAL}]` → `[cam{SERIAL}]` に変更
- `test_name_matches_section`: `'name = "cam_{SERIAL}"'` → `'name = "cam{SERIAL}"'` に変更
- `test_toml_file_content`: `[cam_{SERIAL}]` → `[cam{SERIAL}]` に変更
- `test_distortions_4_elements`: 影響なし（distortions の検証はカメラ名と無関係）

### 9.2 手動テスト

- Calibrate → Export → ポップアップが表示されること
- ポップアップに絶対パスが含まれること
- ファイル名が `cam{serial}_intrinsics.toml` / `cam{serial}_intrinsics.json` であること
- TOML内のセクション名が `[cam{serial}]`、`name` が `"cam{serial}"` であること
- Export失敗時はポップアップが表示されないこと
