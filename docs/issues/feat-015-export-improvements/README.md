# feat-015: Export Improvements - Naming Convention & Completion Notification

## Status: On Hold（カメラが使えないため手動テスト不可。実装・自動テスト完了済み）

## 概要

キャリブレーション結果エクスポートの2点を改善する:
1. ファイル名・TOML内カメラ名を `cam{serial}` に統一（ディレクトリ名と一致させる）
2. エクスポート完了時にポップアップ（QMessageBox）で保存先パスを通知する

## 背景

- 現状のファイル名 `{serial}_intrinsics.toml` とTOML内 `cam_{serial}` がディレクトリ名 `cam{serial}` と不一致
- エクスポート完了がステータスラベルのみの通知で気づきにくい

## 依存

- feat-012 (Export) — エクスポート機能の改善
