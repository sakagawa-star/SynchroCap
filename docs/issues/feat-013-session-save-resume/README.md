# feat-013: Camera Calibration - Session Save/Resume

## Status: Closed

## 概要

キャリブレーションセッション（Board Settings、キャプチャデータ、キャリブレーション結果）を保存・復元する機能を追加する。アプリケーション再起動やカメラ切替後に、以前のセッションを再開できるようにする。

## 背景

- 現状ではキャプチャデータやキャリブレーション結果がメモリ上にのみ存在し、カメラ切替やアプリ終了で失われる
- Board Settings（board_type, cols, rows, square_mm, marker_mm）も毎回手動設定が必要
- 複数カメラのキャリブレーションを順次実施する運用で、セッションの保存/再開が必要

## 依存

- feat-011 (Calibration Calculation) — キャリブレーション結果の保存/復元
- feat-012 (Export) — エクスポート済みディレクトリ構造との整合性
