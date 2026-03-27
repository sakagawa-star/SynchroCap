# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed
- [bug-008](issues/bug-008-heatmap-overwrite/) ヒートマップの高密度領域が低密度領域に上書きされる
  - 相対正規化（max_val除算）から固定スケール正規化（SAT_CAPTURES=3で飽和）に変更
  - キャプチャ追加後も既存の高密度領域の赤色が維持される
- [bug-007](issues/bug-007-calibration-spinbox-wheel-scroll/) Calibration Board Settings 誤操作防止
  - SpinBox/ComboBoxを読み取り専用QPushButton + ダイアログ方式に変更
  - Camera Settings（Tab2）と同じ設計思想に統一

### Changed
- [feat-018](issues/feat-018-encode-quality-improvement/) Raw→MP4 Encode Quality Improvement
  - `tools/raw_tool.py` のエンコードオプションを高品質化: CBR 2200kbps → Constant QP (qp=20)、preset p4 → p7、yuv420p → yuv444p (profile rext)
  - `--qp` CLIオプション追加（0〜51、デフォルト20）
- [feat-017](issues/feat-017-live-view-during-recording/) Live View During Recording
  - 録画中もマルチビュー（Tab3）のライブビューが継続表示されるようになった
  - `stream_setup()` に display 引数を追加し、IC4 SDK が sink と display に独立してフレームを配信
- [feat-016](issues/feat-016-toml-8-coeff-distortions/) TOML Export — 8-Coefficient Distortions
  - TOML の `distortions` を4パラメータ（k1, k2, p1, p2）から8パラメータ（k1, k2, p1, p2, k3, k4, k5, k6）に拡張
  - Pose2Sim は配列長を検証せず OpenCV にそのまま渡すため、8係数が有効に活用される

### Added
- `tools/offline_calibration.py` — 保存済みChArUco画像からオフラインキャリブレーションを実行するCLIツール
  - 既存モジュール（BoardDetector, CalibrationEngine, CalibrationExporter）を再利用
  - カメラ未接続環境でもキャリブレーション・エクスポートの検証が可能
- [feat-013](issues/feat-013-session-save-resume/) Camera Calibration - Session Save/Resume (Board Settings)
  - Board Settings（board_type, cols, rows, square_mm, marker_mm）のJSON永続化
  - ダイアログOK押下時に自動保存（`~/.local/share/synchroCap/board_settings.json`）
  - アプリ起動時に自動復元（バリデーション付き、不正値はデフォルトにフォールバック）
- [feat-011](issues/feat-011-calibration-calculation/) Camera Calibration - Calibration Calculation + Result Display
  - `cv2.calibrateCamera()` によるカメラ内部パラメータ算出
  - カメラ行列（fx, fy, cx, cy）、歪み係数（k1, k2, p1, p2, k3）、RMS再投影誤差の表示
  - キャプチャごとの再投影誤差表示
  - OpenCVの他キャリブレーションコードと結果がほぼ一致することを確認済み
- [feat-012](issues/feat-012-export-pose2sim/) Camera Calibration - Export (Pose2Sim TOML + JSON)
  - Pose2Sim互換TOML形式エクスポート（カメラ行列、歪み係数4パラメータ、メタデータ）
  - 汎用JSON形式エクスポート（OpenCV完全互換、歪み係数5パラメータ）
  - Exportボタン（Calibration QGroupBox内、キャリブレーション結果存在時のみ有効）
  - Save/Exportの保存先ディレクトリ共有（`captures/{timestamp}/intrinsics/cam{serial}/`）
- [feat-010](issues/feat-010-coverage-heatmap/) Camera Calibration - Coverage Heatmap
  - ガウシアンカーネル（σ=画像幅×5%）によるカバレッジヒートマップ生成
  - ライブビューへの自動オーバーレイ表示（キャプチャ1件以上で自動、alpha 0.3）
  - COLORMAP_TURBOによる可視化（未カバー領域=黒、高密度=赤）
  - キャプチャ追加・削除時のキャッシュ自動更新
- [feat-009](issues/feat-009-manual-capture-calibration/) Camera Calibration - Auto Capture (Stability Trigger)
  - 安定検出トリガーによる自動キャプチャ（2.0秒連続成功で発火）
  - クールダウン制御（3.0秒）
  - キャプチャリスト管理（表示・削除・全クリア）
  - キャプチャ時フィードバック（ステータス表示、枠線フラッシュ）
  - 静止画一括保存（Save ボタンで全キャプチャの生フレームをPNG保存）
- [feat-008](issues/feat-008-camera-calibration/) Camera Calibration - Live View with Board Detection (Tab5)
  - カメラ選択・ライブビュー表示
  - ChArUco / チェッカーボードのリアルタイム検出オーバーレイ
  - ボード設定パネル（タイプ、列数、行数、サイズ）
  - デフォルト設定: 5x7 DICT_6X6_250（OpenCVチュートリアル準拠）
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
