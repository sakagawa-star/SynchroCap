# feat-009: Camera Calibration - Auto Capture (Stability Trigger)

## Status: Closed

## 概要

Calibrationタブ（Tab5）に安定検出トリガーによる自動キャプチャ機能を追加。ボード検出が2.0秒連続成功するとハンズフリーで自動キャプチャを実行する。

## 完了日

2026-03-09

## 成果物

- `src/synchroCap/stability_trigger.py` — 安定検出トリガーエンジン（新規）
- `src/synchroCap/ui_calibration.py` — キャプチャUI統合（変更）
- `tests/test_stability_trigger.py` — 単体テスト13件（新規）
- `tests/conftest.py` — テスト共通設定（新規）
