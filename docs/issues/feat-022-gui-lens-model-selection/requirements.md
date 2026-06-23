# 要求仕様書: feat-022 GUI Calibration - Lens Model Selection (Normal / Wide)

## 1.1 プロジェクト概要

- **何を作るのか**: GUI版キャリブレーション（Tab5: Calibration）で、レンズ種別（通常 / 広角）を選択し、選択に応じて推定する歪み係数モデルを切り替える機能。選択値はセッションに永続化する。
- **なぜ作るのか**: 現状 Tab5 は `CalibrationEngine.calibrate()` を `lens_model` 未指定で呼び、デフォルトの `"wide"`（Rational 8係数）固定で推定する。通常レンズでは8係数は過剰パラメータであり、過学習による歪み補正の外挿不安定を招くリスクがある。オフライン版（feat-019 `--lens`）と同等の選択を GUI からも可能にする。
- **誰が使うのか**: SynchroCap でカメラキャリブレーションを行う運用者。
- **どこで使うのか**: Linux PC 上の SynchroCap GUI（Tab5 Calibration）。カメラ接続あり（ライブビューでキャプチャ後に計算）。

## 1.2 用語定義

| 用語 | 定義 |
|---|---|
| 通常レンズ (normal) | 歪みが小さい標準的なレンズ。標準5係数モデルで補正する |
| 広角レンズ (wide) | 歪みが大きいレンズ（例: LM3NC1M 3.5mm）。Rational 8係数モデルで補正する |
| 標準5係数モデル | OpenCV の `(k1, k2, p1, p2, k3)`。`cv2.calibrateCamera()` flags=0 で推定される |
| Rational 8係数モデル | OpenCV の `(k1, k2, p1, p2, k3, k4, k5, k6)`。`cv2.CALIB_RATIONAL_MODEL` フラグで推定される |
| Board Settings | Tab5 の GroupBox。Type/Columns/Rows/Square size/Marker size を読み取り専用ボタン+ダイアログで設定する |
| board_settings.json | Board Settings の永続化先 JSON（`BoardSettingsStore` が読み書き） |

本用語は機能設計書・コード内でも同一の語を使用する。`lens_model` の値は `"normal"` / `"wide"`（`CalibrationEngine` と一致）。

## 1.3 機能要求一覧

### FR-001: レンズ種別の選択UI

- **概要**: Tab5 の Board Settings GroupBox に「Lens」行を追加し、通常 / 広角を選択できるようにする。
- **入力**: ユーザーがLens行のボタンをクリック → QDialog（QComboBox: Normal / Wide-Angle、OK/Cancel）で選択。
- **出力**: 選択値が `self._lens_model`（`"normal"` / `"wide"`）に反映され、ボタン表示テキストが更新される。
- **受け入れ基準**:
  - Lens行のボタンに現在の選択（"Normal" または "Wide-Angle"）が表示される。
  - ダイアログで Cancel した場合、選択値は変更されない。
  - 既存の設計思想（読み取り専用表示 + クリックでダイアログ OK/Cancel）に準拠し、メインUI上で直接編集できる SpinBox/ComboBox を置かないこと。

### FR-002: 選択モデルでのキャリブレーション計算

- **概要**: キャリブレーション計算時、選択された `lens_model` を `CalibrationEngine.calibrate()` に渡す。
- **入力**: `self._lens_model`（`"normal"` / `"wide"`）。
- **出力**: 選択が `normal` の場合5係数、`wide` の場合8係数で推定される（`CalibrationResult.dist_coeffs` の長さに反映）。
- **受け入れ基準**: `normal` 選択時に計算結果の歪み係数が5要素、`wide` 選択時に8要素となること。エクスポート（TOML/JSON）出力の歪み配列長も選択に追従すること（exporter は係数長非依存のため自動追従）。

### FR-003: 選択値の永続化

- **概要**: 選択した `lens_model` を `board_settings.json` に保存し、アプリ再起動時に復元する。
- **入力**: `self._lens_model`。
- **出力**: `board_settings.json` に `"lens_model"` キーが追加される。次回起動時に読み込まれUIに反映される。
- **受け入れ基準**:
  - Lens選択後、`board_settings.json` に `"lens_model"` が記録されること。
  - アプリ再起動後、前回選択した Lens がUIと計算の両方に反映されること。
  - `lens_model` キーが存在しない既存の `board_settings.json` を読み込んだ場合、デフォルト `"normal"` として扱い、エラーにしないこと（初期値=Normal）。

### FR-004: 結果表示のモデル対応

- **概要**: キャリブレーション結果の歪み係数表示（`_dist_label`）が、選択モデルの係数数（5 または 8）に追従して表示する。
- **入力**: `CalibrationResult.dist_coeffs`（5要素または8要素）。
- **出力**: `normal` 時は5係数、`wide` 時は8係数の値が表示される。
- **受け入れ基準**: 表示される係数の個数が `dist_coeffs` の長さと一致すること（既存の表示ロジックが配列長に依存しないなら変更不要、その場合は確認のみ）。

## 1.4 非機能要求

- **パフォーマンス**: 既存処理と同等（モデル切り替えによる追加処理時間は `cv2.calibrateCamera()` 内部のみ）。
- **対応環境**: Linux、SynchroCap GUI（PySide6 / Python 3.10、micromamba 環境 `SynchroCap`）。
- **信頼性**: `board_settings.json` の `lens_model` が不正値（`normal`/`wide` 以外）または欠落の場合、デフォルト `"normal"` にフォールバックし、起動を妨げないこと。
- **互換性**: 既存の `board_settings.json`（`lens_model` キーなし）を読み込んでもエラーにならないこと（デフォルト `"normal"` 扱い）。オフライン版 `offline_calibration.py` の挙動は変更しない。
- **初期値**: GUI（Tab5）のレンズ初期値は `"normal"`（Normal）とする。これはオフライン版 `CalibrationEngine.calibrate()` のデフォルト `"wide"` とは独立した GUI 側の既定値であり、ユーザー決定事項。

## 1.5 制約条件

- **カメラ設定変更禁止ルール**: 本機能は Resolution/PixelFormat/FrameRate 等のカメラ設定を変更しない。`lens_model` はキャリブレーション計算のパラメータでありカメラ設定ではないため、本ルールの対象外。
- 使用ライブラリ: 既存（PySide6, OpenCV）。新規ライブラリ導入なし（`TECH_STACK.md` 更新不要）。
- `CalibrationEngine.calibrate()` の `lens_model` 引数は feat-019 で実装済み。本案件でエンジンのロジックは変更しない。
- 選択UIの配置は Board Settings GroupBox とする（ユーザー決定）。`lens_model` は厳密にはボード設定ではないが、永続化先を `board_settings.json` に統一する都合上、同 GroupBox に配置する。

## 1.6 優先順位

| 要求ID | MoSCoW |
|---|---|
| FR-001 | Must |
| FR-002 | Must |
| FR-003 | Must |
| FR-004 | Should |

MVP = FR-001 + FR-002 + FR-003。
