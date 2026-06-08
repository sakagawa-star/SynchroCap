# 要求仕様書: feat-019 Offline Calibration - Lens Model Selection

## 1.1 プロジェクト概要

- **何を作るのか**: `tools/offline_calibration.py` にレンズ種別（通常 / 広角）の選択オプションを追加し、選択に応じて推定する歪み係数モデルを切り替える機能。
- **なぜ作るのか**: 現状 `CalibrationEngine` は常に Rational 8係数モデル（`cv2.CALIB_RATIONAL_MODEL`）で推定する。通常レンズでは8係数は過剰パラメータであり、過学習による歪み補正の外挿不安定を招くリスクがある。レンズに適したモデルを選択可能にする。
- **誰が使うのか**: SynchroCap の開発者・運用者（保存済みPNG画像からオフラインでキャリブレーションを実行する人）。
- **どこで使うのか**: Linux PC 上の CLI（Python 3.10、micromamba 環境 `SynchroCap`）。カメラ接続は不要。

## 1.2 用語定義

| 用語 | 定義 |
|---|---|
| 通常レンズ (normal) | 歪みが小さい標準的なレンズ。標準5係数モデルで補正する |
| 広角レンズ (wide) | 歪みが大きいレンズ（例: LM3NC1M 3.5mm）。Rational 8係数モデルで補正する |
| 標準5係数モデル | OpenCV の `(k1, k2, p1, p2, k3)`。`cv2.calibrateCamera()` flags=0 で推定される |
| Rational 8係数モデル | OpenCV の `(k1, k2, p1, p2, k3, k4, k5, k6)`。`cv2.CALIB_RATIONAL_MODEL` フラグで推定される |
| 内部パラメータ | カメラ行列（fx, fy, cx, cy）と歪み係数 |

本用語は機能設計書・コード内でも同一の語を使用する。

## 1.3 機能要求一覧

### FR-001: レンズ種別の CLI 指定

- **概要**: `tools/offline_calibration.py` に `--lens {normal,wide}` オプションを追加する。
- **入力**: CLI 引数 `--lens normal` または `--lens wide`。省略時のデフォルトは `wide`（現行動作との互換性維持）。
- **出力**: 選択されたレンズ種別に応じた歪みモデルでキャリブレーションが実行される。
- **受け入れ基準**: `--lens normal` 指定時に5係数、`--lens wide` 指定時および省略時に8係数で推定されること。`normal`/`wide` 以外の値は argparse がエラー終了（exit code 2）すること。

### FR-002: CalibrationEngine のモデル選択対応

- **概要**: `CalibrationEngine.calibrate()` が歪みモデルを引数で選択できるようにする。
- **入力**: 引数 `lens_model: str`。値は `"normal"` または `"wide"`。デフォルトは `"wide"`。
- **出力**: `CalibrationResult.dist_coeffs` の shape が `"normal"` 時 `(1,5)`、`"wide"` 時 `(1,8)` となる。
- **受け入れ基準**: 上記 shape が満たされること。`"normal"`/`"wide"` 以外の値で `ValueError` を送出すること。既存呼び出し元（`ui_calibration.py`）は引数なしで従来通り8係数となること。`"normal"` 時、合成データ（既知カメラ行列・歪みなし）に対する推定カメラ行列（fx, fy, cx, cy）が既知値の±5%以内、かつ RMS 再投影誤差が 1.0 px 未満であること。

### FR-003: 通常レンズ時のエクスポート出力（5要素）

- **概要**: 通常レンズ時、TOML の `distortions` および JSON の `dist_coeffs` を5要素 `(k1, k2, p1, p2, k3)` で出力する。
- **入力**: `CalibrationResult.dist_coeffs` shape=(1,5)。
- **出力**: TOML `distortions = [k1, k2, p1, p2, k3]`（5要素）、JSON `"dist_coeffs"` 配列（5要素）。広角時は従来通り8要素。
- **受け入れ基準**: 通常レンズで実行した出力ファイルの配列長が5、広角で実行した出力ファイルの配列長が8であること。

### FR-004: 結果表示のモデル対応

- **概要**: CLI の結果表示（歪み係数一覧）が係数数に応じたラベルを表示する。
- **入力**: `CalibrationResult.dist_coeffs`（5要素または8要素）。
- **出力**: 5係数時はラベル `k1, k2, p1, p2, k3` の5行、8係数時は `k1, k2, p1, p2, k3, k4, k5, k6` の8行を標準出力に表示する。
- **受け入れ基準**: 表示行数と係数数が一致すること。

## 1.4 非機能要求

- **パフォーマンス**: 既存処理と同等（モデル切り替えによる追加処理時間は `cv2.calibrateCamera()` 内部のみ）。
- **対応環境**: Linux、micromamba 環境 `SynchroCap`（Python 3.10）。GPU 不要。カメラ接続不要。
- **信頼性**: 不正な `lens_model` 値は即座にエラー終了し、ファイル出力を行わない。
- **互換性**: GUI（Tab5 Calibration）の動作は一切変更しない（デフォルト `"wide"` により従来動作を維持する）。

## 1.5 制約条件

- 使用ライブラリ: OpenCV (`cv2.calibrateCamera`)、標準ライブラリ argparse。新規ライブラリ導入なし。
- `src/synchroCap/calibration_exporter.py` の出力フォーマット（TOML キー名・JSON キー名）は変更しない。配列長のみ係数数に追従する。
- カメラ設定変更禁止ルールの対象外（カメラ非接続のオフラインツール）。

## 1.6 優先順位

| 要求ID | MoSCoW |
|---|---|
| FR-001 | Must |
| FR-002 | Must |
| FR-003 | Must |
| FR-004 | Should |

MVP = FR-001 + FR-002 + FR-003。
