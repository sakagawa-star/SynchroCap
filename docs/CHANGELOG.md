# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [v1.0.0] - 2026-02-05

### Added
- **PTP同期マルチカメラ録画機能**
  - Action Scheduler (Action0) によるフレーム同期トリガー
  - ffmpeg (hevc_nvenc) によるリアルタイムMP4エンコード
  - 1カメラ = 1スレッドの録画アーキテクチャ
  - DEFER_ACQUISITION_STARTによる同時開始

- **チャンネル管理機能**
  - カメラとチャンネルID (01-99) の紐付け
  - JSON永続化
  - 重複登録防止

- **マルチビュープレビュー**
  - 4カメラ同時プレビュー
  - PTPステータス表示
  - チャンネル選択UI

- **カメラ設定機能**
  - 個別カメラの設定変更
  - プロパティダイアログ

### Known Issues
- [bug-001](issues/bug-001-cannot-restart-recording-after-duration/) Duration経過後に録画再開できない
