# feat-016: TOML Export — 8-Coefficient Distortions

## Status: Closed

## 概要
CalibrationExporter の TOML 出力で歪み係数を4パラメータ（k1, k2, p1, p2）から8パラメータ（k1, k2, p1, p2, k3, k4, k5, k6）に拡張する。

## 背景
- feat-014 で CalibrationEngine が 8 係数（Rational Model）を算出するようになった
- 現在 TOML は k1, k2, p1, p2 の4個のみ出力し、k3〜k6 は JSON のみ
- Pose2Sim 側の調査により、distortions 配列の長さチェックはなく、8 個書けば OpenCV にそのまま渡されて有効に使われることが確認済み
- ただし Pose2Sim の書き出し処理は D[c][0]〜D[c][4] の5個固定で再保存時に切り詰められる

## 影響範囲
- `src/synchroCap/calibration_exporter.py` — TOML生成ロジック変更
- `tests/test_calibration_exporter.py` — TOMLアサーション修正
- `ui_calibration.py` — 変更不要（`export()` シグネチャは変わらない）
- `tools/offline_calibration.py` — 変更不要
