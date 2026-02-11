# feat-003 要求仕様書: Rawファイル検証ツール

対象: `dev/tutorials/13_raw_viewer/s13_raw_tool.py`
スコープ: Step 1（Rawファイル検証ツール）のみ

> **注意**
> - 本文は「要求仕様」のみを記述する。
> - 実装コードは一切含めない。
> - Step 2（静止画切り出し）、Step 3（MP4エンコード）は本仕様の対象外。

---

## 1. 目的と成功条件

### 1.1 目的

feat-002で実装したヘッダ付きRawファイル形式（SRAWフォーマット）が仕様通りに作られているかを検証する手段を提供する。

### 1.2 成功条件

以下の3つの検証機能がCLIツールとして動作すること:

1. **ヘッダダンプ**: Rawファイルの構造を人間が読める形式で表示できる
2. **整合性チェック**: セッション内のRaw/CSVファイルが仕様に適合していることを自動検証できる
3. **カメラ間同期チェック**: 複数カメラのタイムスタンプ差が閾値以内であることを確認できる

---

## 2. 入力データ仕様

### 2.1 セッションディレクトリ構造

```
captures/YYYYMMDD-HHMMSS/
├── cam{serial}.csv                    # 各カメラ1ファイル
├── cam{serial}_{startframe:06d}.raw   # カメラ毎に1つ以上
└── ...
```

### 2.2 CSVファイル形式

| 列名 | 型 | 説明 |
|------|-----|------|
| frame_number | int | デバイスフレーム番号（4桁0埋め文字列） |
| device_timestamp_ns | int | デバイスタイムスタンプ（ナノ秒） |

- ヘッダ行あり
- エンコーディング: UTF-8
- 1セッションにつき各カメラ1ファイル

### 2.3 Rawファイル形式

feat-002 design.md で定義されたSRAWフォーマット:

- FileHeader (40 bytes): magic(`SRAW`), version, camera_serial, recording_start_ns, width, height, pixel_format, reserved
- FrameHeader (24 bytes) + Payload の繰り返し: magic(`FRAM`), payload_size, frame_index, timestamp_ns
- リトルエンディアン固定
- ファイル分割: `frames_per_file`フレームごとに新ファイル（デフォルト1000）

---

## 3. 機能要件

### 3.1 サブコマンド: `dump`

**目的**: Rawファイル1つのヘッダ情報をダンプ表示する。

**入力**: Rawファイルパス（1ファイル指定）

**表示内容**:
- FileHeader全フィールド
- FrameHeader一覧（デフォルト: 先頭10件 + 末尾10件）
- フレーム総数サマリ

**オプション**:
- `--all`: 全FrameHeaderを表示

**出力例**:
```
=== FileHeader ===
  magic:              SRAW
  version:            1
  camera_serial:      05520125
  recording_start_ns: 1234567890123456789
  width:              1920
  height:             1080
  pixel_format:       BayerGR8 (0)

=== Frames (150 total) ===
  [  0] frame_index=0      timestamp_ns=1234567890123456789  payload=2073600
  [  1] frame_index=1      timestamp_ns=1234567890156789012  payload=2073600
  ...
  [  9] frame_index=9      timestamp_ns=1234567890423456789  payload=2073600
  ... (130 frames omitted) ...
  [140] frame_index=140    timestamp_ns=1234567894789012345  payload=2073600
  ...
  [149] frame_index=149    timestamp_ns=1234567895089012345  payload=2073600
```

### 3.2 サブコマンド: `validate`

**目的**: セッションディレクトリ内のRaw/CSVファイルの整合性を検証する。

**入力**: セッションディレクトリパス

**チェック項目**:

| # | チェック内容 | 判定基準 |
|---|-------------|---------|
| V1 | FileHeader magic | == `SRAW` |
| V2 | FileHeader version | == 1 |
| V3 | FrameHeader magic | 全フレーム == `FRAM` |
| V4 | payload_size | == width * height（BayerGR8の場合） |
| V5 | frame_indexの連続性 | 分割ファイルを通して0から連番 |
| V6 | timestamp_nsの単調増加 | 前フレーム < 現フレーム |
| V7 | CSVフレーム数 == Rawフレーム数 | 一致 |
| V8 | CSVのtimestamp_ns == Rawのtimestamp_ns | 各フレームで一致 |

**ファイル探索**:
- セッションディレクトリ内の `cam*.raw` と `cam*.csv` をグロブで自動検出
- シリアル番号でRawファイルとCSVファイルを紐付け
- 同一シリアルのRawファイルが複数ある場合はstartframeの昇順で処理

**出力例**:
```
=== Validating session: captures/20260210-153000/ ===

--- cam05520125 ---
  Raw files: cam05520125_000000.raw (1000 frames), cam05520125_001000.raw (500 frames)
  CSV file:  cam05520125.csv (1500 rows)
  [PASS] V1: FileHeader magic
  [PASS] V2: FileHeader version
  [PASS] V3: FrameHeader magic (1500 frames checked)
  [PASS] V4: payload_size == 2073600 (1920*1080)
  [PASS] V5: frame_index continuous (0..1499)
  [PASS] V6: timestamp_ns monotonically increasing
  [PASS] V7: CSV rows (1500) == Raw frames (1500)
  [PASS] V8: CSV timestamps match Raw timestamps

--- cam05520126 ---
  ...

=== Result: 8/8 PASS (2 cameras) ===
```

**異常時出力例**:
```
  [FAIL] V5: frame_index gap at index 500 (expected 500, got 502)
  [FAIL] V8: timestamp mismatch at frame 42: CSV=123456789 Raw=123456790
```

### 3.3 サブコマンド: `sync-check`

**目的**: 複数カメラのCSVタイムスタンプを比較し、カメラ間同期精度を確認する。

**入力**: セッションディレクトリパス

**前提**: `validate` でCSVの整合性が確認済みであること（本サブコマンドでは検証しない）。

**処理内容**:
- 各カメラのCSVを読み込み、frame_numberをキーにtimestamp_nsを比較
- 全カメラが持つ共通frame_numberを対象
- 各フレームについてカメラ間のtimestamp_ns差（max - min）を算出

**オプション**:
- `--threshold-ms`（デフォルト: 1.0）: NG判定の閾値（ミリ秒）

**出力内容**:
- 統計情報: mean, max, p99 のカメラ間タイムスタンプ差
- 閾値超過フレームの一覧（あれば）
- 全体の判定結果（PASS/FAIL）

**出力例**:
```
=== Sync Check: captures/20260210-153000/ ===

Cameras: 05520125, 05520126, 05520128, 05520129
Common frames: 1500
Threshold: 1.000 ms

--- Statistics (max-min per frame) ---
  mean:  0.045 ms
  max:   0.892 ms
  p99:   0.234 ms

--- Threshold violations (0 frames) ---
  (none)

=== Result: PASS ===
```

**閾値超過時の出力例**:
```
--- Threshold violations (3 frames) ---
  frame=0042  max-min=1.234 ms  (max: 05520129, min: 05520125)
  frame=0043  max-min=1.567 ms  (max: 05520129, min: 05520125)
  frame=0100  max-min=1.012 ms  (max: 05520126, min: 05520128)

=== Result: FAIL (3 frames exceed threshold) ===
```

---

## 4. CLI インターフェース

### 4.1 コマンド体系

```
python s13_raw_tool.py dump <raw_file> [--all]
python s13_raw_tool.py validate <session_dir>
python s13_raw_tool.py sync-check <session_dir> [--threshold-ms 1.0]
```

### 4.2 終了コード

| コード | 意味 |
|-------|------|
| 0 | 正常終了（validate/sync-checkではPASS） |
| 1 | 検証失敗（FAIL） |
| 2 | 入力エラー（ファイル不在、引数不正等） |

---

## 5. 非要件

- GUIは提供しない（CLIのみ）
- JSON出力形式は提供しない
- Rawファイルの修復・書き換え機能は提供しない
- Step 2（静止画切り出し）、Step 3（MP4エンコード）は本仕様の対象外
- imagingcontrol4（IC4）ライブラリへの依存は不要（ファイル解析のみ）

---

## 6. 依存関係

- Python 3.x 標準ライブラリのみ（struct, csv, glob, argparse, os, statistics等）
- 外部ライブラリ不要
- feat-002 design.md のSRAWフォーマット仕様に準拠
