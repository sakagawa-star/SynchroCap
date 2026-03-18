# 不具合調査・修正計画: feat-012

## イテレーション1 (2026-03-18)

### 1.1 不具合の特定

- **対応する要求ID**: FR-001（Exportボタン）
- **対応する設計セクション**: 機能設計書 4.1（Exportボタン処理ロジック）
- **現在の動作**: Exportボタンをクリックするとアプリケーションが操作不能になる（フリーズ）
- **再現手順**:
  1. Calibrationタブでカメラを選択しライブビューを開始
  2. キャプチャを4件以上取得
  3. Calibrateボタンでキャリブレーション実行
  4. Exportボタンをクリック → 操作不能になる
- **期待する動作**: 要求仕様書 FR-001「ボタン押下でディレクトリ選択ダイアログが開く」

### 1.2 原因分析

- **原因箇所**: `src/synchroCap/ui_calibration.py` L646 `QFileDialog.getExistingDirectory()`
- **原因の説明**: `QFileDialog.getExistingDirectory()` はLinux上でデフォルトでネイティブGTKダイアログを使用する。IC4カメラのストリーミング中（`_frame_timer` 動作中、IC4内部スレッドがフレーム配信中）にネイティブGTKダイアログが開くと、GTKイベントループとQtイベントループの競合が発生し、アプリケーションがフリーズする
- **根本原因（仮説）**: Linux上のネイティブGTKファイルダイアログとIC4フレームコールバック+QTimerの非互換性。`DontUseNativeDialog` オプション追加で解消することを手動テストで確認する
- **補足情報**: プロジェクト内の他の `QFileDialog` 使用例（`dev/tutorials/10_csv_continuity/mainwindow.py`）はIC4の `DisplayWidget` を使用しており、フレームコールバック+QTimerパターンとは異なるため直接比較できない

### 1.3 修正内容

- **変更対象ファイル**: `src/synchroCap/ui_calibration.py`
  - `_on_export_clicked()` の `QFileDialog.getExistingDirectory()` に `QFileDialog.Option.DontUseNativeDialog` オプションを追加する
  - これによりQtの組み込みファイルダイアログが使用され、GTKとの競合を回避する
- **変更しないファイル**:
  - `calibration_exporter.py`: エクスポートロジックに問題なし
  - `calibration_engine.py`: 変更なし
- **修正が設計書に沿っているか**: 設計書 4.1 の `QFileDialog.getExistingDirectory()` 呼び出しにオプション引数を追加するのみ。設計の意図（ディレクトリ選択ダイアログを表示する）は変わらない

### 1.4 影響範囲

- **他の機能への影響**: なし。Exportボタンのダイアログのみに影響。プロジェクト内で `QFileDialog` を使用しているのは本箇所のみ（`src/synchroCap/` 内を検索済み。`dev/tutorials/` のチュートリアルコードは本アプリケーションのコードパスに含まれない）
- **リグレッションリスク**: ダイアログの外観がOS標準と異なる（Qtの組み込みダイアログになる）。機能面でのリグレッションなし

### 1.5 確認方法

- **自動テスト**: ダイアログの表示はGUIテストのためpytestでは検証不可
- **手動テスト**:
  1. Calibrationタブでカメラを選択しライブビューを開始
  2. キャプチャを4件以上取得
  3. Calibrateボタンでキャリブレーション実行
  4. Exportボタンをクリック → ディレクトリ選択ダイアログが正常に表示されること
  5. ダイアログでディレクトリを選択 → TOMLとJSONの2ファイルが生成されること
  6. ダイアログでキャンセル → 何も起きないこと
  7. ダイアログ表示中にライブビューのフレーム更新が継続していることを目視で確認する。ダイアログを5秒以上表示した状態でアプリケーションが応答し続けることを確認する

### 設計書の変更案

機能設計書 4.1 処理ロジックの `QFileDialog.getExistingDirectory()` 呼び出しを以下に変更する。

変更前:
```python
directory = QFileDialog.getExistingDirectory(
    self, "Select Export Directory"
)
```

変更後:
```python
directory = QFileDialog.getExistingDirectory(
    self, "Select Export Directory",
    options=QFileDialog.Option.DontUseNativeDialog,
)
```

理由: Linux上でネイティブGTKダイアログがIC4フレームコールバック+QTimerと競合してフリーズを引き起こすため（仮説。手動テストで検証する）。

---

## イテレーション2 (2026-03-18)

### 問題の分類

要求仕様作成時のヒアリング漏れ。Export先ディレクトリの指定方法について、ユーザーの運用要件が仕様に反映されていなかった。

### 2.1 不具合の特定

- **対応する要求ID**: FR-001（Exportボタン）
- **対応する設計セクション**: 機能設計書 4.1（Exportボタン処理ロジック）
- **現在の動作**: Exportボタン押下時に `QFileDialog` でディレクトリを毎回選択する必要がある
- **期待する動作**: Save（キャプチャ画像保存）と同じディレクトリにExportファイルが自動保存される。ディレクトリ選択ダイアログは不要

### 2.2 原因分析

- **原因**: 要求仕様書 FR-001 でExport先を `QFileDialog` によるユーザー選択と定義していた。ユーザーの実運用では、キャプチャ画像とキャリブレーション結果が同一ディレクトリに存在することが望ましい
- **根本原因**: ヒアリング不足。Export先ディレクトリの運用要件を確認せずに `QFileDialog` 方式を採用した

### 2.3 修正内容

#### 概要

Save と Export で保存先ディレクトリを共有する。インスタンス変数 `_save_dir: Path | None` を導入し、初回の Save または Export で生成したディレクトリパスを記憶する。

#### 保存先パス

```
captures/{timestamp}/intrinsics/cam{serial}/
├── capture_001.png            ← Save
├── capture_002.png            ← Save
├── {serial}_intrinsics.toml   ← Export
└── {serial}_intrinsics.json   ← Export
```

- タイムスタンプは `datetime.now().strftime("%Y%m%d-%H%M%S")` （既存の Save と同一形式）
- パス構造: `captures/{timestamp}/intrinsics/cam{serial}/`（既存の Save と同一。`cam{serial}` はアンダースコアなし、例: `cam49710379`）
- `_save_dir` 構築時に `self._current_serial` を参照する。`stop_live_view()` で `_save_dir` と `_current_serial` が同時にクリアされるため、異なるカメラのシリアル番号が混在することはない

#### 変更対象ファイル

**`src/synchroCap/ui_calibration.py`:**

1. `__init__()` に `self._save_dir: Path | None = None` を追加する
2. `_ensure_save_dir()` メソッドを新規追加する:
   ```python
   def _ensure_save_dir(self) -> Path:
       """Return save directory, creating it on first call.

       mkdir is called on every invocation because Save and Export
       can be called in any order, and the directory may not yet
       exist when _save_dir is already set.

       Raises:
           OSError: If mkdir fails (e.g. permission denied, disk full).
       """
       if self._save_dir is None:
           timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
           self._save_dir = Path("captures") / timestamp / "intrinsics" / f"cam{self._current_serial}"
       self._save_dir.mkdir(parents=True, exist_ok=True)
       return self._save_dir
   ```
3. `_on_save_clicked()` を変更: L724 `timestamp = datetime.now().strftime(...)` と L725 `cam_dir = Path("captures") / ...` の2行を `cam_dir = self._ensure_save_dir()` に置き換える。L726-L730 の `mkdir` + `OSError` ハンドリングは `_ensure_save_dir()` に移動済みのため削除する。`OSError` は `_ensure_save_dir()` からそのまま raise されるため、`_on_save_clicked()` 側で catch する:
   ```python
   def _on_save_clicked(self) -> None:
       """Save all captured raw frames as PNG files."""
       if not self._captures:
           return

       try:
           cam_dir = self._ensure_save_dir()
       except OSError as e:
           logger.error("Failed to create save dir %s: %s", self._save_dir, e)
           self._status_label.setText(f"Save failed: {e}")
           return

       saved = 0
       for i, cap in enumerate(self._captures):
           filename = f"capture_{i+1:03d}.png"
           filepath = cam_dir / filename
           try:
               cv2.imwrite(str(filepath), cap.raw_bgr)
               saved += 1
           except Exception as e:
               logger.error("Failed to save %s: %s", filepath, e)

       self._status_label.setText(f"Saved {saved} images to {cam_dir}")
       logger.info("Saved %d images to %s", saved, cam_dir)
   ```
   注: 個別画像の保存失敗時のステータス表示は既存動作を維持する（スコープ外）。
4. `_on_export_clicked()` を変更: `QFileDialog` を削除し、`_ensure_save_dir()` で取得したディレクトリに保存する。イテレーション1で追加した `DontUseNativeDialog` オプションは、`QFileDialog` 自体の削除により不要となる。`ui_calibration.py` 内で `QFileDialog` を参照しているのは L20 のインポートと `_on_export_clicked()` 内の L646 の使用の2箇所のみであることを確認済み。インポートごと削除しても他の機能に影響なし。変更後の全体コード:
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
5. `stop_live_view()` の `self._capture_image_size = None`（L167）の直後に `self._save_dir = None` を追加する（カメラ切替時にリセット）
6. `_on_clear_all_clicked()` の `self._capture_image_size = None` の直後に `self._save_dir = None` を追加する（全キャプチャクリア = セッションリセットのため、新しいタイムスタンプで保存ディレクトリを生成する）
7. `_on_delete_clicked()` の `self._capture_image_size = None`（キャプチャ0件時のみ実行される分岐内）の直後に `self._save_dir = None` を追加する（同上）

**`docs/issues/feat-012-export-pose2sim/requirements.md`:**

FR-001 を以下のように変更:

処理（変更後の全文）:
  1. `_ensure_save_dir()` で保存先ディレクトリ `captures/{timestamp}/intrinsics/cam{serial}/` を取得する
  2. 取得したディレクトリに TOML ファイルと JSON ファイルを順次出力する（TOML→JSON の順。FR-002, FR-003）
  3. 書き込みに失敗した場合はエラーメッセージをステータスラベルに表示する。TOML書き込み成功後にJSON書き込みが失敗した場合、TOMLファイルはそのまま残す

受け入れ基準（変更後の全リスト）:
  - キャリブレーション結果が存在しない場合、Exportボタンは無効化されている
  - キャリブレーション結果が存在する場合、Exportボタンが有効化される
  - （削除）~~ボタン押下でディレクトリ選択ダイアログが開く~~
  - （削除）~~ダイアログでキャンセルした場合、ファイルは生成されない~~
  - エクスポート成功後、ステータスラベルに保存先パスを表示する
  - （追加）Save と Export が同じディレクトリに保存されること

**`docs/issues/feat-012-export-pose2sim/design.md`:**

- セクション3: PySide6 の用途欄を `GUI（QFileDialog, QPushButton）` から `GUI（QPushButton）` に変更
- セクション4.1: 「処理ロジック」のコードブロック全体を、本イテレーション項目4で提示した `_on_export_clicked()` コードで置き換える。既存コード内の `QFileDialog` 関連コメント（`directory` 変数、キャンセル分岐、`_current_serial` の非空保証コメント）は削除する。`_calibration_result` と `_capture_image_size` の非 None ガードは置き換え後のコードに含まれているため、追加コメントは不要
- セクション4.1: エラーハンドリングから「ユーザーキャンセル」行を削除
- セクション6.2: 「ユーザーが `QFileDialog.getExistingDirectory()` で選択するディレクトリに保存する」を「`_ensure_save_dir()` が返す `captures/{timestamp}/intrinsics/cam{serial}/` に保存する。Save と Export で同一ディレクトリを共有する」に変更
- セクション7.1: `export()` のインターフェースは変更なし（`output_dir` 引数はそのまま。呼び出し元で渡すディレクトリが変わるのみ）
- セクション7.2: `QFileDialog` のインポートを削除。イテレーション1で追加した `DontUseNativeDialog` は `QFileDialog` 自体の削除により不要となる
- セクション9.4: 統合テスト項目から「Exportボタン押下でディレクトリ選択ダイアログが開くこと」「ディレクトリ選択後にTOMLとJSONの2ファイルが生成されること」を削除し、「Exportボタン押下で `captures/{timestamp}/intrinsics/cam{serial}/` にTOMLとJSONが自動保存されること」「Save と Export が同じディレクトリに保存されること」に変更

**変更しないファイル:**
- `calibration_exporter.py`: `output_dir` を引数で受け取るインターフェースは変更不要

### 2.4 影響範囲

- **Save ボタン**: `_on_save_clicked()` のパス生成を `_ensure_save_dir()` に委譲する。保存先パスの構造は既存と同一のため、機能的な変更なし
- **Export ボタン**: `QFileDialog` が不要になる。`QFileDialog` のインポートも削除可能
- **stop_live_view()**: `_save_dir` のクリアを追加。カメラ切替時に新しいタイムスタンプで保存ディレクトリが生成される
- **リグレッションリスク**: Save の保存先パス構造は変更なし。Export の保存先が `QFileDialog` 選択からfixed pathに変わるため、リグレッションなし

### 2.5 確認方法

- **自動テスト**: `calibration_exporter.py` のテストは変更不要（`output_dir` 引数のインターフェースは同一）
- **手動テスト**:
  1. Calibrationタブでキャプチャ4件以上取得 → Calibrate → Export → `captures/{timestamp}/intrinsics/cam{serial}/` にTOML/JSONが生成されること
  2. 続けて Save → 同じディレクトリにPNGが保存されること
  3. Save → Export の順でも同じディレクトリに保存されること
  4. カメラ切替後に再度 Save/Export → 新しいタイムスタンプのディレクトリが生成されること
  5. Save のみ実行（Export なし）→ `captures/{timestamp}/intrinsics/cam{serial}/` にPNGが保存されること（既存動作の回帰テスト）
  6. Save 時にステータスラベルに `Saved N images to {path}` が表示されること
  7. Export 時にステータスラベルに `Exported to {path}` が表示されること
  8. Export ボタン押下時にアプリケーションがフリーズしないこと（イテレーション1の問題の解消確認）
