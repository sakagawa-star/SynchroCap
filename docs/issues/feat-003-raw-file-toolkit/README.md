# feat-003: Rawファイル検証・変換ツール

## Status: Open (Step 1, 2 完了 — Step 3は未着手)

## Summary

feat-002で定義したヘッダ付きRawファイル形式の検証・変換ツールを作成する。

## Background

feat-002でヘッダ付きRawファイル形式での録画機能を実装したが、仕様通りに作られているかを確定するための検証手段がない。Rawファイルの中身を確認・検証するツールを整備し、feat-002の品質を担保する。

## 実装方針

- **実装形態**: CLIツール（単一スクリプト + サブコマンド）
- **配置場所**: `dev/tutorials/13_raw_viewer/`
- **ファイル名**: `s13_raw_tool.py`
- **出力形式**: テキスト（人間が読みやすい形式）

### 入力データ

セッションディレクトリ `captures/YYYYMMDD-HHMMSS/` 配下:
- `cam{serial}.csv` — frame_number, device_timestamp_ns
- `cam{serial}_{startframe:06d}.raw` — SRAW FileHeader + (FRAM FrameHeader + Payload) の繰り返し

## Steps

### Step 1: Rawファイル検証ツール (実装完了 2026-02-11)

#### サブコマンド: `dump`

Rawファイルのヘッダ情報をダンプ表示する。

```
python s13_raw_tool.py dump <raw_file>
```

表示内容:
- FileHeader: magic, version, camera_serial, recording_start_ns, width, height, pixel_format
- FrameHeader一覧: frame_index, timestamp_ns, payload_size（全フレーム or 先頭N件）

#### サブコマンド: `validate`

Rawファイルとセッションデータの整合性チェックを行う。

```
python s13_raw_tool.py validate <session_dir>
```

チェック項目:
- FileHeader magic == `SRAW`, version == 1
- FrameHeader magic == `FRAM`
- payload_size == width * height（BayerGR8の場合）
- frame_indexの連続性（分割ファイル間を通して）
- CSVのフレーム数 == Rawファイルの合計フレーム数
- CSVのtimestamp_ns == FrameHeaderのtimestamp_ns

#### サブコマンド: `sync-check`

複数カメラのCSVを比較し、カメラ間の同期精度を確認する。

```
python s13_raw_tool.py sync-check <session_dir> [--threshold-ms 1.0]
```

チェック内容:
- 同一frame_numberのtimestamp_nsをカメラ間で比較
- 各フレームのmax - min差を算出
- 閾値（デフォルト: 1ms）を超えるフレームを報告
- 統計情報: mean, max, p99 のカメラ間タイムスタンプ差

### Step 2: Rawフレームビューワー (実装完了 2026-02-11)

- Rawファイルから指定フレームをデベイヤーしてカラー画像表示
- OpenCV (`cv2.imshow`) によるビューワー
- `s` キーでPNG保存、`q` キーで終了

### Step 3: MP4エンコード

- RawファイルからMP4ファイルへの変換

## 凍結理由 (2026-02-10) → 再開 (2026-02-10)

feat-002で作成したRawデータとCSVファイルの保存ディレクトリ構造を変更する必要が出たため、先にfeat-002側の対応を行う。

→ feat-002でディレクトリ構造の変更完了。要件整理を再開。

## Related Documents

- [requirements.md](requirements.md) - 要求仕様書（Step 1）
- [design.md](design.md) - 機能設計書（Step 1）
- [requirements_step2.md](requirements_step2.md) - 要求仕様書（Step 2）
- [design_step2.md](design_step2.md) - 機能設計書（Step 2）
- [feat-002](../feat-002-raw-file-recording/) - ヘッダ付きRawファイル形式での録画対応
- [feat-002 design.md](../feat-002-raw-file-recording/design.md) - SRAWフォーマット仕様
