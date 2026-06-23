# feat-022: GUI Calibration - Lens Model Selection (Normal / Wide-Angle)

## Status

Open

## 概要

GUI版のキャリブレーション（Tab5: Calibration）で、レンズ種別に応じて推定する歪み係数モデルを切り替えられるようにする。

現状、Tab5は `CalibrationEngine.calibrate()` を `lens_model` 未指定で呼んでおり、デフォルトの `"wide"`（Rational 8係数モデル）に固定されている。これを `normal` / `wide` から選択可能にする。

- **通常レンズ (normal)**: 標準5係数モデル `(k1, k2, p1, p2, k3)` — flags=0
- **広角レンズ (wide)**: Rational 8係数モデル `(k1, k2, p1, p2, k3, k4, k5, k6)` — `CALIB_RATIONAL_MODEL`（現状の動作）

オフライン版 `tools/offline_calibration.py` には feat-019 で同等の `--lens normal/wide` が既に存在する。本案件はその選択機能を GUI に提供するもの。

## 背景

- `CalibrationEngine.calibrate()` は feat-019 で `lens_model` 引数を持つが、GUI（`ui_calibration.py:641`）はこれを渡しておらずデフォルトの `wide` 固定
- 通常レンズでは8係数モデルは過剰パラメータで、過学習による外挿不安定のリスクがある
- レンズに応じた適切なモデル選択を GUI からも指定可能にする

## 決定事項（ユーザー確認済み）

- 選択UIは **Board Settings GroupBox に行を追加**（既存の QPushButton + QDialog 方式に準拠）
- 選択値は **セッションに永続化**する（`board_settings.json` / `BoardSettingsStore` に `lens_model` キー追加）

## 関連ファイル

- `src/synchroCap/ui_calibration.py` — Lens選択UI追加、`calibrate()` 呼び出しに `lens_model` を渡す、永続化の読み書き
- `src/synchroCap/board_settings_store.py` — 変更不要（ジェネリックな dict 保存。docstring追記のみ検討）
- `src/synchroCap/calibration_engine.py` — 変更不要（`lens_model` 引数は実装済み）

## ドキュメント

- [requirements.md](requirements.md) — 要求仕様書
- [design.md](design.md) — 機能設計書
