# feat-002: ヘッダ付きRawファイル形式での録画対応

## Status: Closed (2026-02-11)

## Summary

カメラからの映像保存形式として、現在のMP4形式に加えてヘッダ付きRawファイル形式にも対応する。

## Background

現在、カメラからの映像はMP4形式での保存のみ対応している。
ヘッダ付きRawファイル形式での保存機能を追加することで、より柔軟なデータ活用を可能にする。

## Implementation Strategy

1. ミニマムアプリで実装方法を検証
2. 検証完了後、本番アプリに機能を追加

## File Format Specification

詳細は [design.md](design.md) を参照。

### FileHeader (40 bytes)
- magic: 'SRAW'
- version: 1
- camera_serial[16]
- recording_start_ns
- width, height
- pixel_format (0=BayerGR8, 1=BayerGR16, 2=BGR8)

### FrameHeader (24 bytes)
- magic: 'FRAM'
- payload_size
- frame_index
- timestamp_ns (device_timestamp_ns)

### File Splitting
- 基準: フレーム数ベース (デフォルト1000)
- 命名: `cam{serial}_{開始フレーム:06d}.raw`

## Progress

### Step 1: ミニマムアプリでの検証 (進行中)

対象ファイル: `dev/tutorials/12_rec_raw/s12_rec4cams.py`

#### 完了した作業

1. **録画フロー修正** (fix-recording-flow.md)
   - MP4モードで0フレームになる問題を修正
   - 本番アプリと同じ処理順序に変更:
     - Phase 1: カメラオープン + 基本設定
     - Phase 2: PTP Slave待機
     - Phase 3: Trigger + Action Scheduler設定
     - Phase 4: stream_setup + ffmpeg起動
     - Phase 5: キャプチャスレッド開始
   - `configure_camera_for_bayer_gr8()` → `configure_camera_basic()` に変更
   - `_check_offsets_and_schedule()` → `_configure_and_schedule()` に変更
   - Trigger設定をAction Scheduler設定の直前に移動

2. **録画時間計算の修正**
   - `scheduled_start_ns`パラメータを追加
   - 終了時刻をスケジュール開始時刻基準に変更

3. **フレームレート設定の修正**
   - ffmpegに渡すフレームレートを`TRIGGER_INTERVAL_FPS`(30fps)に修正

4. **レポート計算の修正**
   - `actual_fps`と`drift_ms`の計算を修正

5. **出力ディレクトリ構造の変更**
   - 本番アプリ準拠のセッション単位ディレクトリ構造に変更
   - `captures/mp4/`, `captures/csv/`, `captures/raw/` → `captures/YYYYMMDD-HHMMSS/`
   - `MP4_OUTPUT_DIR` 定数、`--output-dir` 引数を削除
   - `make_output_filename()` に `session_dir` パラメータを追加
   - `_worker()` のCSVを追記モード(`"a"`)から新規書き込み(`"w"`)に変更

#### 検証完了 (2026-02-11)

feat-003（Rawファイル検証・変換ツール）により以下を確認:
- `validate`: FileHeader/FrameHeaderの整合性、frame_index連続性、CSV一致（全項目PASS）
- `view`: デベイヤー後のカラー画像表示で映像内容を目視確認
- `encode`: Raw→MP4変換で正常な動画を生成

#### 凍結履歴

- 凍結 (2026-02-10): Rawファイル検証ツール未整備のため
- 再開 (2026-02-10): ディレクトリ構造変更のため
- 再凍結 (2026-02-10): feat-003（検証ツール）完了待ち
- 完了 (2026-02-11): feat-003によりStep 1の検証完了

### Step 2: 本番アプリへの機能追加

- (検証完了後に詳細を決定)

## Affected Files

- `dev/tutorials/12_rec_raw/s12_rec4cams.py` (検証用)
- (本番アプリ対象ファイルは検証後に決定)

## Related Documents

- [design.md](design.md) - ファイルフォーマット仕様
- [fix-recording-flow.md](fix-recording-flow.md) - 録画フロー修正設計書
