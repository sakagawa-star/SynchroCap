# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- [feat-003](issues/feat-003-raw-file-toolkit/) Rawファイル検証CLIツール (Step 1)
  - `dump`: Rawファイルのヘッダ情報ダンプ表示
  - `validate`: セッション内Raw/CSVの整合性チェック (V1〜V8)
  - `sync-check`: カメラ間タイムスタンプ同期精度の確認
- [feat-003](issues/feat-003-raw-file-toolkit/) Rawフレームビューワー (Step 2)
  - `view`: BayerGR8フレームをデベイヤーしてカラー画像表示・PNG保存
- [feat-003](issues/feat-003-raw-file-toolkit/) Raw→MP4エンコード (Step 3)
  - `encode`: タイムスタンプベースのフレーム選択でRawからMP4を生成（hevc_nvenc）
- [feat-002](issues/feat-002-raw-file-recording/) ヘッダ付きRawファイル形式での録画対応
  - SRAWフォーマット（FileHeader + FrameHeader + Payload）によるRaw録画
  - フレーム数ベースのファイル分割
  - セッション単位のディレクトリ構造

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

### Fixed
- [bug-001](issues/bug-001-cannot-restart-recording-after-duration/) Duration経過後に録画再開できない
  - 原因: 非QtスレッドからのQTimer.singleShot()呼び出し
  - 修正: Qt Signalによるスレッド間通信に変更

### Known Issues
- [bug-002](issues/bug-002-start-delay-included-in-recording-duration/) Start after遅延が録画時間に含まれる (Frozen)
- [bug-003](issues/bug-003-trigger-properties-not-found/) Triggerプロパティが見つからない

### Added
- [feat-001](issues/feat-001-csv-frame-timestamp-logging/) フレームタイムスタンプのCSV記録
  - 録画中の各フレームのframe_number, device_timestamp_nsをCSVに記録
  - 動画と同じディレクトリに `cam{serial}.csv` を出力
