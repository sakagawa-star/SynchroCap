# 要求仕様書: Camera Calibration - Export (Pose2Sim TOML + JSON)

対象: feat-012
作成日: 2026-03-18
基準文書: `docs/REQUIREMENTS_STANDARD.md`

---

## 1. プロジェクト概要

### 1.1 何を作るか

feat-011で算出されたキャリブレーション結果（カメラ行列、歪み係数、画像サイズ）をファイルにエクスポートする機能を追加する。Pose2Simが読み込めるTOML形式と、汎用的なJSON形式の2種類を出力する。

### 1.2 なぜ作るか

feat-011でキャリブレーション計算が実装されたが、結果がメモリ上にのみ保持されており永続化されない。Pose2Simワークフローとの連携にはTOML形式のエクスポートが必要であり、他ツールとの比較検証には汎用的なJSON形式が有用である。また、feat-011の手動テスト判定（他ツールとの結果比較）もエクスポート機能に依存している。

### 1.3 誰が使うか

SynchroCapを使用してモーションキャプチャ用の同期録画を行うオペレーター。

### 1.4 どこで使うか

SynchroCapと同一のPC環境（Ubuntu Linux、micromamba SynchroCap環境）。

---

## 2. 用語定義

| 用語 | 定義 |
|------|------|
| Pose2Sim TOML | Pose2Simが読み込むキャリブレーションファイル形式（`Calib.toml`）。カメラごとのセクションに内部パラメータ・外部パラメータを記載する |
| カメラ行列 | 3x3の内部パラメータ行列。焦点距離（fx, fy）と主点（cx, cy）を含む |
| 歪み係数 | レンズ歪みを表す係数ベクトル。OpenCVの5パラメータ: (k1, k2, p1, p2, k3)。Pose2Simは4パラメータ: (k1, k2, p1, p2) を使用する |
| RMS再投影誤差 | キャリブレーション品質指標。値が小さいほど品質が高い（ピクセル単位） |
| CalibrationResult | feat-011で定義されたキャリブレーション結果データクラス（`calibration_engine.py`） |

---

## 3. 機能要求一覧

### FR-001: Exportボタン

- **概要**: キャリブレーション結果をファイルにエクスポートするボタンを提供する。ボタンはCalibration QGroupBox内、Calibrateボタンの下に配置する
- **入力**: ユーザーの「Export」ボタンクリック
- **前提条件**: `CalibrationResult` が存在すること（キャリブレーション計算が完了していること）
- **処理**:
  1. `QFileDialog.getExistingDirectory()` で保存先ディレクトリをユーザーに選択させる
  2. ユーザーがキャンセルした場合は何もしない
  3. 選択されたディレクトリに TOML ファイルと JSON ファイルを順次出力する（FR-002, FR-003）
  4. 2ファイルの書き込みを順次実行し、いずれかが失敗した場合はエラーメッセージをステータスラベルに表示する。成功したファイルはそのまま残す
- **出力**: 2つのファイル（TOML, JSON）を指定ディレクトリに保存
- **受け入れ基準**:
  - キャリブレーション結果が存在しない場合、Exportボタンは無効化されている
  - キャリブレーション結果が存在する場合、Exportボタンが有効化される
  - ボタン押下でディレクトリ選択ダイアログが開く
  - ダイアログでキャンセルした場合、ファイルは生成されない
  - エクスポート成功後、ステータスラベルに保存先パスを表示する

### FR-002: Pose2Sim TOML エクスポート

- **概要**: Pose2Simが読み込めるTOML形式でキャリブレーション結果を出力する
- **入力**: CalibrationResult、カメラシリアル番号、画像サイズ
- **処理**:
  1. 以下の構造のTOMLファイルを生成する:
     ```toml
     [cam_{serial}]
     name = "cam_{serial}"
     size = [1920.0, 1080.0]
     matrix = [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]]
     distortions = [k1, k2, p1, p2]
     rotation = [0.0, 0.0, 0.0]
     translation = [0.0, 0.0, 0.0]
     fisheye = false

     [metadata]
     adjusted = false
     error = {rms_error}
     ```
  2. `distortions` は4パラメータ (k1, k2, p1, p2) とする（Pose2Sim互換。k3は除外する）。OpenCVの `dist_coeffs` の順序は `[k1, k2, p1, p2, k3]` であり、インデックス `[0:4]` を取り出して `[k1, k2, p1, p2]` とする
  3. `rotation` と `translation` はゼロベクトルとする（内部パラメータのみのため）
  4. `fisheye` は `false` 固定とする
  5. `metadata.adjusted` は `false` 固定とする（Pose2Simが外部パラメータ調整済みかどうかを示すフラグ。本案件はintrinsicsのみのため未調整）
  6. `metadata.error` にRMS再投影誤差を設定する
  7. 数値フォーマット: カメラ行列・歪み係数・RMS誤差は小数点以下4桁（`:.4f`）、`size` は小数点以下1桁（`:.1f`）で出力する。科学記法は使用しない
- **出力**: `{serial}_intrinsics.toml` ファイル
- **受け入れ基準**:
  - 出力されたTOMLファイルがTOMLパーサでエラーなくパースできること
  - 出力されたTOMLファイルがPose2Simの `retrieve_calib_params()` で読み込めること
  - カメラ行列の値がCalibrationResultの値と一致すること
  - 歪み係数が4パラメータ (k1, k2, p1, p2) で出力されること

### FR-003: JSON エクスポート

- **概要**: 汎用的なJSON形式でキャリブレーション結果を出力する
- **入力**: CalibrationResult、カメラシリアル番号、画像サイズ、キャプチャ数（呼び出し元で `len(captures)` を渡す。キャリブレーション計算後にキャプチャが変更されると結果がクリアされるため、Export時点で `len(captures)` と `len(CalibrationResult.per_image_errors)` は常に一致する）
- **処理**:
  1. 以下の構造のJSONファイルを生成する:
     ```json
     {
       "serial": "{serial}",
       "image_size": [1920, 1080],
       "camera_matrix": [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]],
       "dist_coeffs": [k1, k2, p1, p2, k3],
       "rms_error": 0.3220,
       "num_images": 53
     }
     ```
  2. `dist_coeffs` は5パラメータ (k1, k2, p1, p2, k3) とする（OpenCV完全互換）
  3. `image_size` は `[width, height]` の整数配列とする
  4. `camera_matrix` は3x3のネスト配列とする
  5. `num_images` はキャリブレーションに使用したキャプチャ数とする
- **出力**: `{serial}_intrinsics.json` ファイル
- **受け入れ基準**:
  - 出力されたJSONファイルが `json.load()` で読み込めること
  - カメラ行列・歪み係数がCalibrationResultの値と一致すること
  - 歪み係数が5パラメータで出力されること
  - `num_images` がキャリブレーションに使用したキャプチャ数と一致すること

### FR-004: Exportボタンのライフサイクル管理

- **概要**: Exportボタンの有効/無効状態をキャリブレーション結果の有無に連動させる
- **入力**: キャリブレーション結果の変化（計算完了、クリア）
- **処理**:
  1. キャリブレーション結果が存在する場合のみExportボタンを有効化する
  2. キャリブレーション結果がクリアされたらExportボタンを無効化する
- **出力**: Exportボタンの有効/無効状態の更新
- **受け入れ基準**:
  - キャリブレーション実行前: Export無効
  - キャリブレーション実行後: Export有効
  - キャプチャ追加/削除（結果クリア）: Export無効
  - カメラ切替（結果クリア）: Export無効

---

## 4. 非機能要求

### 4.1 パフォーマンス

| 項目 | 基準 |
|------|------|
| エクスポート処理 | 1秒以下。ファイル2つの書き込みのみ |

### 4.2 信頼性

- エクスポート先ディレクトリへの書き込み権限がない場合、エラーメッセージをステータスラベルに表示する
- 同名ファイルが存在する場合は確認ダイアログなしで上書きする（サイレント上書き）

### 4.3 ログ出力

Python標準の `logging` モジュールを使用する。ログ出力の詳細（レベル、出力ポイント）は機能設計書で定義する。

### 4.4 対応環境

feat-011と同一。Ubuntu Linux、micromamba SynchroCap環境。

---

## 5. 制約条件

### 5.1 使用必須ライブラリ

- `json`: Python標準ライブラリ。JSONエクスポートに使用
- 新規外部ライブラリの追加なし。TOMLファイルはf-string手動構築で生成する（Pose2Simと同一の方式）

### 5.2 カメラ設定変更禁止

CLAUDE.md「カメラ設定変更禁止ルール」に従う。

### 5.3 入力データ形式

feat-011で定義された `CalibrationResult` をそのまま使用する。

### 5.4 ファイル命名規約

- TOML: `{serial}_intrinsics.toml`（例: `49710379_intrinsics.toml`）
- JSON: `{serial}_intrinsics.json`（例: `49710379_intrinsics.json`）

### 5.5 Pose2Sim TOMLの制約

- Pose2Simの `retrieve_calib_params()` は `distortions` を4要素配列として読み込む
- Pose2Simの予約セクション名（`metadata`, `capture_volume`, `charuco`, `checkerboard`）をカメラ名に使用しない
- カメラ名はセクションヘッダと `name` フィールドで一致させる

---

## 6. 優先順位

| 優先度 | 機能ID | 機能名 |
|--------|--------|--------|
| **Must** | FR-001 | Exportボタン |
| **Must** | FR-002 | Pose2Sim TOML エクスポート |
| **Must** | FR-003 | JSON エクスポート |
| **Must** | FR-004 | Exportボタンのライフサイクル管理 |

### MVP範囲

FR-001〜FR-004すべてがMVP。

---

## 7. スコープ外

以下は本案件の対象外とする:

- 複数カメラの結果を1ファイルにまとめるマルチカメラエクスポート（feat-013のセッション管理で対応。その際 `[metadata]` の構造が変更される可能性がある）
- 外部パラメータ（extrinsics）のエクスポート（本案件はintrinsicsのみ）
- エクスポート先ディレクトリの記憶/デフォルト設定（feat-013のセッション管理で対応）
- インポート機能（エクスポートされたファイルの読み込み）
- Pose2Sim以外の特定ツール向けフォーマット対応
