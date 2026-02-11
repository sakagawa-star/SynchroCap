# feat-004 要求仕様書: 本番アプリへのRaw形式録画機能追加

## 1. 目的

本番アプリ（`src/synchroCap/`）において、既存のMP4形式に加えてSRAWフォーマットによるRaw形式での録画を選択可能にする。

## 2. 背景

feat-002にてミニマムアプリ（`dev/tutorials/12_rec_raw/s12_rec4cams.py`）で実装・検証済みのヘッダ付きRawファイル形式での録画機能を、本番アプリに移植する。feat-003の検証ツールにより、SRAWフォーマットの整合性・映像内容・MP4変換の正常性が確認されている。

## 3. 機能要件

### FR-01: Output Format切り替えUI

- Recording GroupBox内の「Duration」行と「Status」行の間に「Output Format」行を追加する
- ラジオボタンで「MP4」と「Raw」を切り替え可能にする
- デフォルト選択は「MP4」とする
- 録画中はOutput Formatの変更を不可にする

```
Recording
  Start after:      [8 sec]
  Duration:         [30 sec]
  Output Format:    (●) MP4  ( ) Raw
  Frames per file:  [1000]           ← Raw選択時のみ表示
  Status:           Ready
  [Start] [Stop]
```

### FR-02: Frames per file設定UI

- Raw形式選択時のみ表示される「Frames per file」入力欄を追加する
- 入力タイプ: QSpinBox（整数値）
- 範囲: 100〜100000
- デフォルト値: 1000
- MP4形式選択時は非表示にする
- 録画中は変更不可にする

### FR-03: Raw形式での録画

- Output Formatで「Raw」が選択されている場合、ffmpegを使用せずSRAWフォーマットでファイルに直接書き込む
- SRAWフォーマット仕様は [feat-002 design.md](../feat-002-raw-file-recording/design.md) に準拠する
  - FileHeader (40 bytes): magic='SRAW', version=1, camera_serial, recording_start_ns, width, height, pixel_format
  - FrameHeader (24 bytes): magic='FRAM', payload_size, frame_index, timestamp_ns
  - Payload: BayerGR8生データ
- フレーム数がFrames per file設定値に達したらファイルを分割する
- ファイル命名規則: `cam{serial}_{開始フレーム番号:06d}.raw`
  - 例: `cam05520125_000000.raw`, `cam05520125_001000.raw`

### FR-04: セッションディレクトリ構造

- Raw形式でもMP4形式と同じセッションディレクトリ（`captures/YYYYMMDD-HHMMSS/`）に出力する
- Raw形式の出力ファイル:
  - `cam{serial}_{start_frame:06d}.raw` （1つ以上）
  - `cam{serial}.csv` （FR-05参照）

### FR-05: CSV出力

- Raw形式での録画時もMP4形式と同様にCSVファイルを出力する
- CSVフォーマット: `frame_number, device_timestamp_ns`
- 出力先: `captures/YYYYMMDD-HHMMSS/cam{serial}.csv`

### FR-06: ディスク使用量の推定表示

- Output Formatで「Raw」が選択された状態で録画を開始する際、推定ディスク使用量を表示する
- 表示内容:
  - 1カメラあたりの推定サイズ
  - 全カメラ合計の推定サイズ
- 計算式: `カメラ数 × (width × height) × (duration_s × trigger_interval_fps)`
  - ヘッダサイズ（FileHeader 40B + FrameHeader 24B/frame）は推定値に含めなくてよい（誤差の範囲）
- 表示方法: ログ出力（コンソール）
- 録画開始を阻止しない（警告のみ）

### FR-07: MP4形式との互換性

- Output Formatで「MP4」が選択されている場合、従来と全く同じ動作をすること
- MP4形式の録画に影響を与えないこと

### FR-08: Recording Report

- Raw形式での録画終了時もMP4形式と同様にRecording Reportを出力する
- 出力内容: カメラごとのframes, expected, delta

## 4. 非機能要件

### NFR-01: パフォーマンス

- Raw形式の書き込みはffmpegパイプ書き込みよりも低負荷であること（GPU不使用）
- フレーム落ちが発生しないよう、ファイルI/Oは各カメラスレッド内で行う（既存の1カメラ=1スレッドアーキテクチャに従う）

### NFR-02: 移植方針

- ミニマムアプリ（`s12_rec4cams.py`）から以下の関数・定数を本番アプリに移植する:
  - `SRAW_MAGIC`, `FRAM_MAGIC`, `SRAW_VERSION`, `PIXEL_FORMAT_BAYER_GR8`
  - `write_file_header()`
  - `write_frame_header()`
  - `make_raw_split_filename()`
- `RecordingController`クラスに対して、Raw録画パスを追加する

## 5. 変更対象ファイル（想定）

| ファイル | 変更内容 |
|---------|---------|
| `src/synchroCap/ui_multi_view.py` | Output Format UI、Frames per file UI追加 |
| `src/synchroCap/recording_controller.py` | Raw録画パス追加、RecordingSlot拡張 |

## 6. 制約事項

- PixelFormatは BayerGR8 のみ対応（ミニマムアプリと同様）
- Raw形式とMP4形式の同時録画は対象外（排他選択）
- 録画中のOutput Format変更は不可

## 7. 関連ドキュメント

- [feat-002 design.md](../feat-002-raw-file-recording/design.md) — SRAWフォーマット仕様
- [feat-002 README.md](../feat-002-raw-file-recording/) — ミニマムアプリでの検証結果
- [feat-003 README.md](../feat-003-raw-file-toolkit/) — Rawファイル検証・変換ツール
