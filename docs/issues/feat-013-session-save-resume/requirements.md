# 要求仕様書: Camera Calibration - Session Save/Resume (Board Settings)

対象: feat-013
作成日: 2026-03-18
基準文書: `docs/REQUIREMENTS_STANDARD.md`

---

## 1. プロジェクト概要

### 1.1 何を作るか

Calibrationタブ（Tab5）の Board Settings（board_type, cols, rows, square_mm, marker_mm）をJSONファイルに永続化し、アプリケーション起動時に自動復元する機能を追加する。

### 1.2 なぜ作るか

現状では Board Settings がメモリ上にのみ存在し、アプリケーション終了やカメラ切替のたびにデフォルト値（ChArUco, 5, 7, 30.0, 22.0）にリセットされる。実運用では同じボードを繰り返し使用するため、毎回手動で設定し直す手間を排除する。

### 1.3 誰が使うか

SynchroCapを使用してモーションキャプチャ用の同期録画を行うオペレーター。

### 1.4 どこで使うか

SynchroCapと同一のPC環境（Ubuntu Linux、micromamba SynchroCap環境）。

---

## 2. 用語定義

| 用語 | 定義 |
|------|------|
| Board Settings | キャリブレーションボードの設定。board_type, cols, rows, square_mm, marker_mm の5項目 |
| BoardSettingsStore | Board Settings の永続化を担当するクラス。CameraSettingsStore と同じ設計パターン |
| AppDataLocation | `QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)` が返すディレクトリ。Ubuntu では `~/.local/share/synchroCap/` |

---

## 3. 機能要求一覧

### FR-001: Board Settings の自動保存

- **概要**: Board Settings ダイアログでOKを押下した時点で、設定値をJSONファイルに自動保存する
- **入力**: ユーザーが Board Settings ダイアログでOKを押下
- **処理**:
  1. ダイアログのOK押下後、既存の `_apply_board_config()` が呼ばれた後に `BoardSettingsStore.save()` を呼び出す
  2. 以下の5項目をJSONファイルに書き込む:
     - `board_type`: str（`"charuco"` または `"checkerboard"`）
     - `cols`: int（3〜20）
     - `rows`: int（3〜20）
     - `square_mm`: float（1.0〜200.0）
     - `marker_mm`: float（1.0〜200.0）
  3. 保存先: `{AppDataLocation}/board_settings.json`
- **出力**: JSONファイルへの書き込み
- **受け入れ基準**:
  - Board Type ダイアログでOK → board_type が保存される
  - Columns ダイアログでOK → cols が保存される
  - Rows ダイアログでOK → rows が保存される
  - Square Size ダイアログでOK → square_mm が保存される
  - Marker Size ダイアログでOK → marker_mm が保存される
  - 保存失敗時（ディスクフル等）はログ出力のみ。UIへのエラー通知は行わない（設定変更自体は成功している）

### FR-002: Board Settings の自動復元

- **概要**: アプリケーション起動時（`CalibrationWidget.__init__()`）に、保存済みの Board Settings をJSONファイルから読み込み、内部状態とUIに反映する
- **入力**: なし（自動実行）
- **処理**:
  1. `CalibrationWidget.__init__()` で `BoardSettingsStore.load()` を呼び出す
  2. JSONファイルが存在し、有効な値が含まれている場合:
     - 内部変数（`_board_type`, `_cols`, `_rows`, `_square_mm`, `_marker_mm`）に値を設定する
     - UIのボタンテキスト（`_type_button`, `_cols_button`, `_rows_button`, `_square_button`, `_marker_button`）を更新する
     - `_apply_board_config()` を呼び出してボード検出器に反映する
  3. JSONファイルが存在しない場合、またはパースに失敗した場合: デフォルト値（ChArUco, 5, 7, 30.0, 22.0）を使用する（現行動作と同一）
- **出力**: 内部状態とUIの更新
- **受け入れ基準**:
  - アプリ起動後、Calibrationタブに前回保存した Board Settings が表示される
  - 設定ファイルが存在しない場合はデフォルト値が表示される（初回起動と同一）
  - 設定ファイルが壊れている場合（JSONパースエラー）はデフォルト値が表示される

---

## 4. 非機能要求

### 4.1 パフォーマンス

| 項目 | 基準 |
|------|------|
| 保存処理 | 1ms以下。5項目のJSON書き込みのみ |
| 復元処理 | 1ms以下。JSONファイルの読み込みと5項目の代入のみ |

### 4.2 信頼性

- 保存失敗時はログ出力（WARNING）のみ。アプリの動作には影響しない
- 復元失敗時はデフォルト値にフォールバック。アプリの動作には影響しない

### 4.3 ログ出力

Python標準の `logging` モジュールを使用する。ログ出力の詳細は機能設計書で定義する。

### 4.4 対応環境

Ubuntu Linux、Python 3.10、micromamba SynchroCap環境。

---

## 5. 制約条件

### 5.1 使用必須ライブラリ

- `json`: Python標準ライブラリ。JSONファイルの読み書きに使用
- `PySide6.QtCore.QStandardPaths`: 保存先ディレクトリの取得に使用（既存の Camera Settings と同一）
- 新規外部ライブラリの追加なし

### 5.2 カメラ設定変更禁止

CLAUDE.md「カメラ設定変更禁止ルール」に従う。

### 5.3 保存ファイル仕様

- パス: `{QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)}/board_settings.json`
- フォーマット: JSON、UTF-8、indent=2
- グローバル設定（カメラ非依存）。1ファイルに1セットの Board Settings を保存する

### 5.4 Camera Settings への非影響

- 本案件の変更は既存の Camera Settings タブ（Tab2）の動作に悪影響を与えてはならない
- Camera Settings の設定保存・復元・適用が従来通り正常に動作すること
- `camera_settings.json` と `board_settings.json` は独立したファイルとし、互いに干渉しないこと

### 5.5 デフォルト値

| 項目 | デフォルト値 |
|------|------------|
| board_type | `"charuco"` |
| cols | 5 |
| rows | 7 |
| square_mm | 30.0 |
| marker_mm | 22.0 |

---

## 6. 優先順位

| 優先度 | 機能ID | 機能名 |
|--------|--------|--------|
| **Must** | FR-001 | Board Settings の自動保存 |
| **Must** | FR-002 | Board Settings の自動復元 |

### MVP範囲

FR-001〜FR-002すべてがMVP。

---

## 7. スコープ外

以下は本案件の対象外とする:

- キャプチャデータの保存/復元
- キャリブレーション結果の保存/復元
- カメラごとの Board Settings 保存（グローバル設定のみ）
- 複数カメラの結果を1ファイルにまとめるマルチカメラエクスポート
- Board Settings のインポート機能（外部ファイルからの読み込み）
