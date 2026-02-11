# feat-003 機能設計書: Rawファイル検証ツール

対象: `dev/tutorials/13_raw_viewer/s13_raw_tool.py`
基準文書: `requirements.md`（本ディレクトリ内）
参照仕様: `../feat-002-raw-file-recording/design.md`（SRAWフォーマット仕様）

---

## 1. 機能概要

### 1.1 機能名

Rawファイル検証CLIツール（Raw File Validation Tool）

### 1.2 機能説明

SRAWフォーマットのRawファイルとCSVファイルの検証を行う単一スクリプトのCLIツール。3つのサブコマンド（dump, validate, sync-check）を提供する。

---

## 2. ファイル構成

### 2.1 配置

```
dev/tutorials/13_raw_viewer/
└── s13_raw_tool.py    # 単一ファイル
```

### 2.2 外部依存

Python 3.x 標準ライブラリのみ:
- `struct` — バイナリ解析
- `csv` — CSV読み込み
- `glob` — ファイル探索
- `argparse` — CLI引数解析
- `os` — パス操作
- `statistics` — 統計計算
- `re` — シリアル番号抽出
- `sys` — 終了コード

---

## 3. データ構造設計

### 3.1 SRAWフォーマット定数

```python
SRAW_MAGIC = b'SRAW'
FRAM_MAGIC = b'FRAM'
SRAW_VERSION = 1

FILE_HEADER_FORMAT = '<4sI16sqHHHH'   # 40 bytes
FILE_HEADER_SIZE = 40
FRAME_HEADER_FORMAT = '<4sIQq'         # 24 bytes
FRAME_HEADER_SIZE = 24

PIXEL_FORMAT_NAMES = {
    0: "BayerGR8",
    1: "BayerGR16",
    2: "BGR8",
}
```

### 3.2 FileHeader NamedTuple

```python
class FileHeader(NamedTuple):
    magic: bytes           # 4 bytes — b'SRAW'
    version: int           # uint32
    camera_serial: str     # 16 bytes → null-terminated ASCII文字列
    recording_start_ns: int  # int64
    width: int             # uint16
    height: int            # uint16
    pixel_format: int      # uint16
    reserved: int          # uint16
```

### 3.3 FrameHeader NamedTuple

```python
class FrameHeader(NamedTuple):
    magic: bytes           # 4 bytes — b'FRAM'
    payload_size: int      # uint32
    frame_index: int       # uint64
    timestamp_ns: int      # int64
```

### 3.4 FrameInfo（ヘッダ情報のみ、Payload除外）

```python
class FrameInfo(NamedTuple):
    frame_index: int
    timestamp_ns: int
    payload_size: int
    file_offset: int       # FrameHeaderのファイル内オフセット
```

---

## 4. モジュール設計

### 4.1 関数一覧

| 関数名 | 責務 | 使用サブコマンド |
|--------|------|----------------|
| `read_file_header(f)` | FileHeaderをパース | dump, validate |
| `read_frame_header(f)` | FrameHeaderをパース | dump, validate |
| `iter_frame_infos(f, file_header)` | 全フレームのFrameInfoをイテレート（Payload skip） | dump, validate |
| `discover_session_files(session_dir)` | セッション内のRaw/CSVをシリアル別に分類 | validate, sync-check |
| `read_csv_timestamps(csv_path)` | CSVからframe_number, timestamp_nsを読み込み | validate, sync-check |
| `cmd_dump(args)` | dumpサブコマンド本体 | dump |
| `cmd_validate(args)` | validateサブコマンド本体 | validate |
| `cmd_sync_check(args)` | sync-checkサブコマンド本体 | sync-check |
| `main()` | argparse + サブコマンドディスパッチ | — |

### 4.2 共通パーサ関数

#### `read_file_header(f: BinaryIO) -> FileHeader`

```
1. f.read(40) でバイト列読み込み
2. struct.unpack(FILE_HEADER_FORMAT, data) で展開
3. camera_serial: 16バイトからnullターミネータまでをデコード
4. FileHeader NamedTuple を返す
```

#### `read_frame_header(f: BinaryIO) -> Optional[FrameHeader]`

```
1. f.read(24) でバイト列読み込み
2. 読み込みバイト数 < 24 → None を返す（EOF）
3. struct.unpack(FRAME_HEADER_FORMAT, data) で展開
4. FrameHeader NamedTuple を返す
```

#### `iter_frame_infos(f: BinaryIO, file_header: FileHeader) -> Iterator[FrameInfo]`

```
1. ファイルポインタはFileHeader直後（offset=40）にある前提
2. ループ:
   a. 現在のオフセットを記録
   b. read_frame_header(f) → None なら終了
   c. f.seek(frame_header.payload_size, SEEK_CUR) でPayloadをスキップ
   d. FrameInfo を yield
```

### 4.3 セッションファイル探索

#### `discover_session_files(session_dir: str) -> Dict[str, SessionFiles]`

```python
class SessionFiles(NamedTuple):
    serial: str
    raw_files: List[str]    # startframeの昇順でソート済み
    csv_path: Optional[str]
```

**探索ロジック**:
```
1. glob("cam*.raw") → 正規表現 r"cam(\d+)_(\d+)\.raw" でシリアルとstartframeを抽出
2. glob("cam*.csv") → 正規表現 r"cam(\d+)\.csv" でシリアルを抽出
3. シリアルをキーにしてグループ化
4. Rawファイルはstartframeの昇順でソート
```

### 4.4 CSV読み込み

#### `read_csv_timestamps(csv_path: str) -> List[Tuple[str, int]]`

```
1. csv.reader で読み込み
2. ヘッダ行をスキップ
3. 各行から (frame_number, device_timestamp_ns) を返す
   - frame_number: 文字列のまま保持（"0042" 等）
   - device_timestamp_ns: int 変換
```

---

## 5. サブコマンド設計

### 5.1 `dump` サブコマンド

#### 処理フロー

```
1. 引数: raw_file パス, --all フラグ
2. ファイルを開く (mode="rb")
3. read_file_header(f) → FileHeader表示
4. iter_frame_infos(f, file_header) で全フレーム情報を収集
5. 表示:
   a. --all: 全フレーム表示
   b. デフォルト: 先頭10件 + 末尾10件（中間は "... (N frames omitted) ..." 表示）
6. サマリ: 総フレーム数
```

#### 表示フォーマット

```
=== FileHeader ===
  magic:              SRAW
  version:            1
  camera_serial:      {serial}
  recording_start_ns: {ns}
  width:              {w}
  height:             {h}
  pixel_format:       {name} ({value})

=== Frames ({total} total) ===
  [{index:>4}] frame_index={fi:<8}  timestamp_ns={ts}  payload={ps}
```

### 5.2 `validate` サブコマンド

#### 処理フロー

```
1. 引数: session_dir パス
2. discover_session_files(session_dir) でファイル一覧取得
3. 各シリアルについて以下を実行:
   a. Rawファイル検証（V1〜V6）
   b. CSV読み込み
   c. Raw-CSV整合性検証（V7〜V8）
4. 結果サマリ表示
5. 終了コード: 全PASS → 0, FAIL有り → 1
```

#### チェック項目の実装方針

| # | チェック | 実装方法 |
|---|---------|---------|
| V1 | FileHeader magic == SRAW | 各Rawファイルの先頭4バイトを検証 |
| V2 | FileHeader version == 1 | FileHeader.version を検証 |
| V3 | FrameHeader magic == FRAM | 全フレームのFrameHeaderで検証 |
| V4 | payload_size == width * height | BayerGR8: 1byte/pixel なので width*height |
| V5 | frame_index連続性 | 分割ファイルを跨いで0,1,2,...,Nの連番を検証 |
| V6 | timestamp_ns単調増加 | 前フレームのtimestamp_ns < 現フレームのtimestamp_ns |
| V7 | CSVフレーム数 == Rawフレーム数 | len(csv_rows) == sum(raw_frame_counts) |
| V8 | CSV timestamp == Raw timestamp | 各フレームでtimestamp_nsを比較 |

#### V5: 分割ファイル間のframe_index連続性チェック

```
expected_index = 0
for raw_file in sorted_raw_files:
    for frame_info in iter_frame_infos(f, file_header):
        if frame_info.frame_index != expected_index:
            → FAIL (gap detected)
        expected_index += 1
```

#### V8: CSV-Raw タイムスタンプ照合

```
csv_timestamps = read_csv_timestamps(csv_path)
raw_timestamps = []  # iter_frame_infos から収集

for i, (csv_ts, raw_ts) in enumerate(zip(csv_timestamps, raw_timestamps)):
    if csv_ts[1] != raw_ts.timestamp_ns:
        → FAIL
```

### 5.3 `sync-check` サブコマンド

#### 処理フロー

```
1. 引数: session_dir パス, --threshold-ms (float, default=1.0)
2. discover_session_files(session_dir) でCSVファイル一覧取得
3. 各カメラのCSVを読み込み: {serial: {frame_number: timestamp_ns}}
4. 全カメラに共通するframe_numberの集合を算出
5. 各共通フレームについて:
   a. 全カメラのtimestamp_nsを収集
   b. diff = max(timestamps) - min(timestamps) を算出
   c. diff > threshold_ns → 違反リストに追加
6. 統計計算: mean, max, p99
7. 結果表示
8. 終了コード: 違反0件 → 0, 違反有り → 1
```

#### p99の計算

```python
diffs_sorted = sorted(all_diffs)
p99_index = int(len(diffs_sorted) * 0.99)
p99 = diffs_sorted[min(p99_index, len(diffs_sorted) - 1)]
```

#### 統計表示単位

- 内部計算: ナノ秒 (int)
- 表示: ミリ秒 (小数点以下3桁)

---

## 6. CLI設計

### 6.1 argparse構成

```python
parser = argparse.ArgumentParser(
    description="SynchroCap Raw file validation tool"
)
subparsers = parser.add_subparsers(dest="command", required=True)

# dump
dump_parser = subparsers.add_parser("dump", help="Dump raw file headers")
dump_parser.add_argument("raw_file", help="Path to .raw file")
dump_parser.add_argument("--all", action="store_true",
                         help="Show all frame headers")

# validate
validate_parser = subparsers.add_parser("validate",
                                         help="Validate session files")
validate_parser.add_argument("session_dir", help="Path to session directory")

# sync-check
sync_parser = subparsers.add_parser("sync-check",
                                     help="Check inter-camera sync")
sync_parser.add_argument("session_dir", help="Path to session directory")
sync_parser.add_argument("--threshold-ms", type=float, default=1.0,
                         help="Sync threshold in ms (default: 1.0)")
```

### 6.2 終了コード

```python
EXIT_OK = 0        # 正常（PASS）
EXIT_FAIL = 1      # 検証失敗（FAIL）
EXIT_ERROR = 2     # 入力エラー
```

---

## 7. エラーハンドリング

### 7.1 入力エラー

| 状況 | 対応 | 終了コード |
|------|------|-----------|
| ファイル/ディレクトリが存在しない | エラーメッセージ出力 | 2 |
| Rawファイルが見つからない | エラーメッセージ出力 | 2 |
| CSVファイルが見つからない（validate時） | 該当カメラをWARNING表示、V7/V8はスキップ | — |
| ファイルサイズがFileHeader未満 | エラーメッセージ出力 | 2 |

### 7.2 データエラー

| 状況 | 対応 | 終了コード |
|------|------|-----------|
| magic不一致 | FAIL報告、検証継続 | 1 |
| 読み込み中のIOError | WARNING表示、該当ファイルスキップ | 1 |
| CSV行数不整合 | FAIL報告 | 1 |

---

## 8. 処理性能への考慮

### 8.1 Payloadスキップ

validate/dumpではPayloadデータの読み込みは不要。`f.seek(payload_size, SEEK_CUR)` でスキップすることで、大容量ファイルでも高速に処理する。

### 8.2 メモリ使用量

- dump: FrameInfoリストを全件メモリに保持（先頭/末尾表示のため）。1フレームあたり約40バイトのため、100万フレームでも約40MB。
- validate: 1カメラ分のFrameInfo + CSVデータを保持。カメラ単位で逐次処理。
- sync-check: 全カメラのCSVデータをメモリに保持。CSVは1フレームあたり約30バイトのため、4カメラ x 10万フレームでも約12MB。

---

## 9. テスト方針

### 9.1 検証方法

実機で録画したセッションデータに対してツールを実行し、結果を目視確認する。

### 9.2 確認項目

1. `dump`: FileHeader/FrameHeaderが仕様通りの値で表示されること
2. `validate`: 正常データに対して全項目PASSとなること
3. `sync-check`: カメラ間タイムスタンプ差の統計が妥当な値であること
4. 終了コード: 正常時0、異常時1、入力エラー時2

---

## 10. 影響範囲

### 変更対象ファイル

| ファイル | 変更種別 |
|---------|---------|
| `dev/tutorials/13_raw_viewer/s13_raw_tool.py` | 新規作成 |

### 既存機能への影響

- なし（読み取り専用のスタンドアロンツール）
