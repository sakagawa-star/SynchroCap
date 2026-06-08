# feat-019: Offline Calibration - Lens Model Selection (Normal / Wide-Angle)

## Status

Open

## 概要

`tools/offline_calibration.py` でレンズ種別に応じて推定する歪み係数モデルを切り替えられるようにする。

- **通常レンズ**: 標準5係数モデル `(k1, k2, p1, p2, k3)` — `cv2.calibrateCamera()` flags=0
- **広角レンズ**: Rational 8係数モデル `(k1, k2, p1, p2, k3, k4, k5, k6)` — `CALIB_RATIONAL_MODEL`（現状の動作）

通常レンズ選択時、TOML/JSON の `distortions` / `dist_coeffs` は **5要素**で出力する（ユーザー決定事項）。

## 背景

- feat-016 で TOML 出力を 4→8 係数に拡張し、`CalibrationEngine` は常に `CALIB_RATIONAL_MODEL` を使用している
- 通常レンズでは 8係数モデルは過剰パラメータで、過学習による外挿不安定のリスクがある
- レンズに応じた適切なモデル選択を CLI から指定可能にする

## 関連ファイル

- `tools/offline_calibration.py` — CLI オプション追加
- `src/synchroCap/calibration_engine.py` — `calibrate()` にモデル選択引数追加
- `src/synchroCap/calibration_exporter.py` — 変更不要（係数長に非依存）

## ドキュメント

- [requirements.md](requirements.md) — 要求仕様書
- [design.md](design.md) — 機能設計書
