# feat-002 機能設計書: ヘッダ付きRawファイル形式での録画対応

## 1. 概要

ミニマムアプリ `s12_rec4cams.py` にヘッダ付きRaw形式での録画機能を実装する。

## 2. ファイルフォーマット仕様

### 2.1 ファイル構造

```
[FileHeader]           # 40 bytes - ファイル先頭に1回
[FrameHeader][Payload] # 24 bytes + payload_size - フレーム毎に繰り返し
[FrameHeader][Payload]
...
```

### 2.2 FileHeader (40 bytes)

```c
struct FileHeader {
    uint32_t magic;              // 'SRAW' (0x57415253 little-endian)
    uint32_t version;            // 1
    char     camera_serial[16];  // null-terminated ASCII
    int64_t  recording_start_ns; // device_timestamp_ns of first frame
    uint16_t width;              // 画像幅
    uint16_t height;             // 画像高さ
    uint16_t pixel_format;       // PixelFormat enum
    uint16_t reserved;           // 0
};
```

### 2.3 FrameHeader (24 bytes)

```c
struct FrameHeader {
    uint32_t magic;           // 'FRAM' (0x4D415246 little-endian)
    uint32_t payload_size;    // 画像データサイズ (bytes)
    uint64_t frame_index;     // 0から始まる連番
    int64_t  timestamp_ns;    // device_timestamp_ns
};
```

### 2.4 PixelFormat enum

| 値 | 名前 | 説明 |
|----|------|------|
| 0 | BayerGR8 | 8bit Bayer (Green-Red) |
| 1 | BayerGR16 | 16bit Bayer (Green-Red) |
| 2 | BGR8 | 8bit BGR |

### 2.5 エンディアン

- リトルエンディアン固定

## 3. ファイル分割仕様

### 3.1 分割基準

- フレーム数ベース
- デフォルト: 1000フレーム/ファイル
- コマンドライン引数で変更可能

### 3.2 ファイル命名規則

```
cam{serial}_{開始フレーム番号:06d}.raw
```

例:
- `cam05520125_000000.raw` (フレーム 0-999)
- `cam05520125_001000.raw` (フレーム 1000-1999)
- `cam05520125_002000.raw` (フレーム 2000-2999)

## 4. 実装設計

### 4.1 新規追加する定数

```python
# ファイルフォーマット
SRAW_MAGIC = b'SRAW'           # 0x53524157
FRAM_MAGIC = b'FRAM'           # 4652414D
SRAW_VERSION = 1

# PixelFormat enum
PIXEL_FORMAT_BAYER_GR8 = 0
PIXEL_FORMAT_BAYER_GR16 = 1
PIXEL_FORMAT_BGR8 = 2

# ファイル分割
DEFAULT_FRAMES_PER_FILE = 1000
```

### 4.2 新規追加するコマンドライン引数

```python
parser.add_argument(
    "--frames-per-file",
    type=int,
    default=1000,
    help="Number of frames per raw file (default: 1000)",
)
```

### 4.3 新規追加する関数

#### `write_file_header()`

```python
def write_file_header(
    file: BinaryIO,
    serial: str,
    recording_start_ns: int,
    width: int,
    height: int,
    pixel_format: int,
) -> None:
    """ファイルヘッダを書き込む"""
```

#### `write_frame_header()`

```python
def write_frame_header(
    file: BinaryIO,
    payload_size: int,
    frame_index: int,
    timestamp_ns: int,
) -> None:
    """フレームヘッダを書き込む"""
```

#### `make_raw_split_filename()`

```python
def make_raw_split_filename(serial: str, start_frame: int) -> str:
    """分割ファイル名を生成する"""
    return f"cam{serial}_{start_frame:06d}.raw"
```

### 4.4 変更する関数

#### `record_raw_frames()` の変更点

1. フレームループ内でヘッダ書き込みを追加
2. フレームカウントが閾値に達したらファイルを切り替え
3. 新しいファイルを開く際にFileHeaderを書き込む

### 4.5 処理フロー

```
1. 最初のフレーム受信時:
   - FileHeader書き込み (recording_start_ns = 最初のフレームのtimestamp)

2. 各フレーム受信時:
   a. frame_index % frames_per_file == 0 かつ frame_index > 0 の場合:
      - 現在のファイルをクローズ
      - 新しいファイルを開く
      - FileHeader書き込み
   b. FrameHeader書き込み
   c. Payload書き込み
   d. frame_index++
```

## 5. テスト計画

### 5.1 基本動作確認

1. `--raw-output` で録画を実行
2. 生成されたファイルのヘッダを確認
3. フレーム数が閾値を超えた場合にファイルが分割されることを確認

### 5.2 ヘッダ検証

- magic値が正しいこと
- payload_sizeが width * height と一致すること
- frame_indexが連番であること
- timestamp_nsが単調増加すること

## 6. 影響範囲

### 変更対象ファイル

| ファイル | 変更内容 |
|---------|---------|
| `dev/tutorials/12_rec_raw/s12_rec4cams.py` | ヘッダ付きRaw形式の実装 |

### 既存機能への影響

- MP4出力モード: 影響なし
- CSV出力: 影響なし
