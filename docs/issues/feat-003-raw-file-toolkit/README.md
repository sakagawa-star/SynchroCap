# feat-003: Rawファイル検証・変換ツール

## Status: Closed (全Step完了 2026-02-11)

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

### Step 1: Rawファイル検証ツール (実機テスト完了 2026-02-11)

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

### Step 2: Rawフレームビューワー (実機テスト完了 2026-02-11)

#### サブコマンド: `view`

Rawファイルから指定フレームをデベイヤー（BayerGR8→BGR）してカラー画像表示する。

```
python s13_raw_tool.py view <raw_file> [--frame N]
```

- `--frame N`: 表示するフレーム番号（0始まり、デフォルト: 0）
- キー操作: `s` でPNG保存、`q` または `ESC` で終了
- PNG保存先: Rawファイルと同じディレクトリに `{stem}_frame{N:06d}.png`
- 依存: opencv-python

使用例:
```bash
# 先頭フレームを表示
python s13_raw_tool.py view captures/20260211-123456/cam05520125_000000.raw

# 50番目のフレームを表示
python s13_raw_tool.py view captures/20260211-123456/cam05520125_000000.raw --frame 50
```

### Step 3: Raw→MP4エンコード (実機テスト完了 2026-02-11)

#### サブコマンド: `encode`

セッション内の指定カメラのRawファイル群からMP4を生成する。

```
python s13_raw_tool.py encode <session_dir> --serial <serial> [--fps 30]
```

- `--serial`: 対象カメラのシリアル番号（必須）
- `--fps`: MP4のフレームレート（デフォルト: 30）
- 出力先: `<session_dir>/cam{serial}.mp4`（自動命名、既存ファイルがある場合はエラー）
- タイムスタンプベースのフレーム選択（固定fps、フレーム落ち補完）
- ffmpeg (hevc_nvenc) によるエンコード
- 異なるシリアル番号であれば複数プロセスで並列実行可能

使用例:
```bash
# 30fpsでMP4生成
python s13_raw_tool.py encode captures/20260211-123456 --serial 05520125

# 60fpsで生成
python s13_raw_tool.py encode captures/20260211-123456 --serial 05520125 --fps 60

# 4カメラ分を並列実行
python s13_raw_tool.py encode captures/20260211-123456 --serial 05520125 &
python s13_raw_tool.py encode captures/20260211-123456 --serial 05520126 &
python s13_raw_tool.py encode captures/20260211-123456 --serial 05520128 &
python s13_raw_tool.py encode captures/20260211-123456 --serial 05520129 &
```

### Step 4: encodeサブコマンドの統計表示改善 (実機テスト完了 2026-02-11)

- encodeの出力メッセージで duplicated/skipped の原因が判別できない問題を改善
- Raw実効fpsの表示追加
- 状況判定ノートの付与（timestamp jitter / downsampled / upsampled / WARNING）

## 凍結理由 (2026-02-10) → 再開 (2026-02-10)

feat-002で作成したRawデータとCSVファイルの保存ディレクトリ構造を変更する必要が出たため、先にfeat-002側の対応を行う。

→ feat-002でディレクトリ構造の変更完了。要件整理を再開。

## Related Documents

- [requirements.md](requirements.md) - 要求仕様書（Step 1）
- [design.md](design.md) - 機能設計書（Step 1）
- [requirements_step2.md](requirements_step2.md) - 要求仕様書（Step 2）
- [design_step2.md](design_step2.md) - 機能設計書（Step 2）
- [requirements_step3.md](requirements_step3.md) - 要求仕様書（Step 3）
- [design_step3.md](design_step3.md) - 機能設計書（Step 3）
- [requirements_step4.md](requirements_step4.md) - 要求仕様書（Step 4）
- [design_step4.md](design_step4.md) - 機能設計書（Step 4）
- [feat-002](../feat-002-raw-file-recording/) - ヘッダ付きRawファイル形式での録画対応
- [feat-002 design.md](../feat-002-raw-file-recording/design.md) - SRAWフォーマット仕様
