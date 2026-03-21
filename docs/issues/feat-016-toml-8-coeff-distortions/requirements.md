# feat-016: TOML Export — 8-Coefficient Distortions 要求仕様書

## 1. プロジェクト概要

- **何を作るのか**: CalibrationExporter の TOML 出力における歪み係数を 4 パラメータから 8 パラメータに拡張する
- **なぜ作るのか**: feat-014 で CalibrationEngine が 8 係数 Rational Model（k1, k2, p1, p2, k3, k4, k5, k6）を算出するようになったが、TOML には k1, k2, p1, p2 の 4 個しか出力されず、k3〜k6 が失われている。Pose2Sim は配列長を検証せず OpenCV にそのまま渡すため、8 個書けば下流で有効に活用される
- **誰が使うのか**: SynchroCap ユーザー（Pose2Sim パイプラインでキャリブレーション結果を利用する研究者）
- **どこで使うのか**: メインアプリ（Tab5 Export ボタン）および tools/offline_calibration.py

## 2. 用語定義

| 用語 | 定義 |
|------|------|
| Rational Model | OpenCV の `cv2.CALIB_RATIONAL_MODEL` フラグで推定される 8 係数歪みモデル（k1, k2, p1, p2, k3, k4, k5, k6） |
| dist_coeffs | CalibrationResult.dist_coeffs。shape=(1,8), float64 |
| TOML | Pose2Sim 互換のカメラパラメータファイル形式 |
| JSON | OpenCV 完全互換のカメラパラメータファイル形式 |

## 3. 機能要求一覧

### FR-001: TOML 歪み係数 8 パラメータ出力

- **機能名**: TOML distortions フィールドの 8 要素化
- **概要**: `_build_toml()` が出力する `distortions` 配列を dist_coeffs の全 8 要素にする
- **入力**: CalibrationResult.dist_coeffs（shape=(1,8), float64）
- **出力**: TOML ファイル内の `distortions = [k1, k2, p1, p2, k3, k4, k5, k6]`（各値は小数点以下 4 桁）
- **受け入れ基準**:
  - TOML の `distortions` 配列が 8 要素である
  - 各要素が dist_coeffs の対応する値と一致する（小数点以下 4 桁で丸めた値）
  - JSON の `dist_coeffs` 出力は変更されない（8 要素のまま）

### FR-002: export() シグネチャ不変

- **機能名**: 公開 API の後方互換性維持
- **概要**: `CalibrationExporter.export()` のシグネチャは変更しない
- **入力**: 既存と同じ引数（result, serial, image_size, num_images, output_dir）
- **出力**: 既存と同じ戻り値（[toml_path, json_path]）
- **受け入れ基準**:
  - `export()` の引数・戻り値が変更されていない
  - `ui_calibration.py` の呼び出しコードに変更が不要である

## 4. 非機能要求

- **パフォーマンス**: 文字列フォーマットの変更のみであり、処理時間への影響はない
- **信頼性**: dist_coeffs の shape が (1,8) でない場合の動作は CalibrationEngine の仕様保証による（常に shape=(1,8) を返す）

## 5. 制約条件

- CalibrationEngine が返す dist_coeffs は常に shape=(1,8) である（feat-014 で確定）
- Pose2Sim の再保存処理は D[c][0]〜D[c][4] の 5 個に切り詰めるが、これは Pose2Sim 側の制約であり SynchroCap 側では対処しない

## 6. 優先順位

| ID | 優先度 | 備考 |
|----|--------|------|
| FR-001 | Must | 本案件の唯一の実質的変更 |
| FR-002 | Must | メインアプリへの影響を防ぐため必須 |
