# feat-012: Camera Calibration - Export (Pose2Sim TOML + JSON)

## Status: Open

## 概要

キャリブレーション結果（内部パラメータ、歪み係数、画像サイズ）をファイルにエクスポートする機能を追加する。
Pose2Sim が読み込める TOML 形式と、汎用的な JSON 形式の2種類を出力する。

## 背景

- feat-011 でキャリブレーション計算・結果表示が完了したが、結果がメモリ上のみで永続化されない
- 他ツール（Pose2Sim 等）との比較検証や連携にはファイルエクスポートが必要
- feat-011 の手動テスト判定もエクスポート機能に依存している

## 依存

- feat-011 (Calibration Calculation) — キャリブレーション結果を前提とする
