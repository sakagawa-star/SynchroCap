# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- [inv-002](issues/inv-002-device-timestamp-meaning/) device_timestamp_ns タイムスタンプ切り分け実験ツール
  - ソフトウェアトリガー + TIMESTAMP_LATCH 方式で device_timestamp_ns の意味を判定
  - `tools/timestamp_test.py` として独立スクリプトで提供
- [feat-007](issues/feat-007-camera-settings-viewer/) Camera Settings Viewer (Tab4)
  - 全カメラの設定値（Resolution, PixelFormat, FPS, Trigger, AWB, AE, AG）を一覧表示
  - 全カメラ間の設定一致チェック（OK/NG）とサマリー表示
  - 不一致セルの赤系背景色による視覚的強調
  - 録画中はタブ無効化
- [feat-003](issues/feat-003-raw-file-toolkit/) Rawファイル検証CLIツール (Step 1)
  - `dump`: Rawファイルのヘッダ情報ダンプ表示
  - `validate`: セッション内Raw/CSVの整合性チェック (V1〜V8)
  - `sync-check`: カメラ間タイムスタンプ同期精度の確認
- [feat-003](issues/feat-003-raw-file-toolkit/) Rawフレームビューワー (Step 2)
  - `view`: BayerGR8フレームをデベイヤーしてカラー画像表示・PNG保存
- [feat-003](issues/feat-003-raw-file-toolkit/) Raw→MP4エンコード (Step 3)
  - `encode`: タイムスタンプベースのフレーム選択でRawからMP4を生成（hevc_nvenc）
- [feat-003](issues/feat-003-raw-file-toolkit/) encode統計表示改善 (Step 4)
  - `encode`: Raw実効fps表示と duplicated/skipped 状況判定ノート追加
- [feat-004](issues/feat-004-raw-recording-in-app/) 本番アプリへのRaw形式録画機能追加
  - Output Format切り替えUI（MP4 / Raw）
  - SRAWフォーマットによるRaw録画パス
  - Frames per file設定（Raw選択時）
  - ディスク使用量の事前見積もり表示
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
