# Feature Design: feat-001 フレームタイムスタンプのCSV記録

## 1. 変更概要

### 1.1 変更対象ファイル

| ファイル | 変更種別 | 内容 |
|---------|---------|------|
| `src/synchroCap/recording_controller.py` | 修正 | CSV記録機能の追加 |

### 1.2 変更なしファイル

- `ui_multi_view.py` - UIからの操作は不要（自動的にCSV出力）

## 2. データ構造の変更

### 2.1 RecordingSlot拡張

```python
from typing import TextIO
import csv

@dataclass
class RecordingSlot:
    """各カメラスロットの録画コンテキスト"""
    # 既存フィールド
    serial: str
    grabber: ic4.Grabber
    recording_sink: Optional[ic4.QueueSink] = None
    recording_listener: Optional[ic4.QueueSinkListener] = None
    ffmpeg_proc: Optional[subprocess.Popen] = None
    output_path: Optional[Path] = None
    frame_count: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    delta_ns: int = 0

    # CSV関連（新規追加）
    csv_path: Optional[Path] = None
    csv_file: Optional[TextIO] = None
    csv_writer: Optional[Any] = None  # csv.writer型
    csv_buffer: List[List] = field(default_factory=list)
```

### 2.2 定数追加

```python
class RecordingController:
    # 既存定数
    PTP_SLAVE_TIMEOUT_S = 30.0
    PTP_POLL_INTERVAL_S = 1.0
    QUEUE_BUFFER_COUNT = 500
    FFMPEG_FLUSH_INTERVAL = 30

    # CSV関連（新規追加）
    CSV_FLUSH_INTERVAL = 10  # フレーム数
```

## 3. 処理フローの変更

### 3.1 シーケンス図

```
_setup_recording()
    │
    ├── [既存] ffmpeg起動
    ├── [既存] 録画sink作成
    ├── [既存] stream_setup
    │
    └── [新規] CSV初期化
            ├── CSVファイルパス設定
            ├── CSVファイルオープン
            ├── csv.writer作成
            └── ヘッダー書き込み

_worker() [フレームループ内]
    │
    ├── [既存] buf = sink.try_pop_output_buffer()
    │
    ├── [新規] メタデータ取得
    │       ├── md = buf.meta_data
    │       ├── frame_no = f"{md.device_frame_number:05}"
    │       └── timestamp = md.device_timestamp_ns
    │
    ├── [新規] CSVバッファ追加
    │       └── csv_buffer.append([frame_no, timestamp])
    │
    ├── [新規] CSVフラッシュ判定
    │       └── if len(csv_buffer) >= CSV_FLUSH_INTERVAL:
    │               csv_writer.writerows(csv_buffer)
    │               csv_buffer.clear()
    │               csv_file.flush()
    │
    ├── [既存] ffmpegへ書き込み
    └── [既存] buf.release()

_cleanup()
    │
    ├── [新規] CSV終了処理
    │       ├── 残りバッファをフラッシュ
    │       ├── csv_file.flush()
    │       └── csv_file.close()
    │
    └── [既存] ffmpeg終了処理
```

## 4. 詳細設計

### 4.1 _setup_recording() の変更

```python
def _setup_recording(self) -> bool:
    """ffmpeg起動と録画用sink準備"""
    for slot in self._slots:
        # [既存] 出力パス設定
        slot.output_path = self._output_dir / f"cam{slot.serial}.mp4"

        # [新規] CSVパス設定・初期化
        slot.csv_path = self._output_dir / f"cam{slot.serial}.csv"
        try:
            slot.csv_file = open(slot.csv_path, "w", newline="", encoding="utf-8")
            slot.csv_writer = csv.writer(slot.csv_file)
            slot.csv_writer.writerow(["frame_number", "device_timestamp_ns"])
            slot.csv_buffer = []
        except Exception as e:
            self._log(f"[{slot.serial}] Warning: failed to open CSV: {e}")
            slot.csv_file = None
            slot.csv_writer = None

        # [既存] ffmpeg起動...
```

### 4.2 _worker() の変更

```python
def _worker(self, slot: RecordingSlot) -> None:
    # ... 既存コード ...

    while time.monotonic() < end_time:
        # ... ffmpegチェック ...

        buf = sink.try_pop_output_buffer()
        if buf is None:
            time.sleep(0.001)
            continue

        # [新規] メタデータ取得・CSV記録
        if slot.csv_writer is not None:
            try:
                md = buf.meta_data
                frame_no = f"{md.device_frame_number:05}"
                timestamp = md.device_timestamp_ns
                slot.csv_buffer.append([frame_no, timestamp])

                if len(slot.csv_buffer) >= self.CSV_FLUSH_INTERVAL:
                    slot.csv_writer.writerows(slot.csv_buffer)
                    slot.csv_buffer.clear()
                    slot.csv_file.flush()
            except Exception as e:
                self._log(f"[{serial}] Warning: CSV write error: {e}")

        # [既存] ffmpegへ書き込み
        try:
            arr = buf.numpy_wrap()
            output_stream.write(arr.tobytes())
            slot.frame_count += 1
            # ...
```

### 4.3 _cleanup() の変更

```python
def _cleanup(self) -> None:
    """リソースのクリーンアップ"""
    for slot in self._slots:
        # [新規] CSV終了処理
        if slot.csv_file is not None:
            try:
                # 残りバッファをフラッシュ
                if slot.csv_writer is not None and slot.csv_buffer:
                    slot.csv_writer.writerows(slot.csv_buffer)
                    slot.csv_buffer.clear()
                slot.csv_file.flush()
                slot.csv_file.close()
            except Exception as e:
                self._log(f"[{slot.serial}] Warning: CSV close error: {e}")

        # [既存] ffmpeg終了処理...
```

## 5. エラーハンドリング

### 5.1 エラー発生時の動作

| 箇所 | エラー | 動作 |
|-----|-------|------|
| CSVファイルオープン | 失敗 | 警告ログ、録画継続（CSVなし） |
| CSVバッファ書き込み | 失敗 | 警告ログ、録画継続 |
| CSVフラッシュ | 失敗 | 警告ログ、録画継続 |
| CSVクローズ | 失敗 | 警告ログ |

### 5.2 警告ログフォーマット

```
[RecordingController] [{serial}] Warning: failed to open CSV: {error}
[RecordingController] [{serial}] Warning: CSV write error: {error}
[RecordingController] [{serial}] Warning: CSV close error: {error}
```

## 6. 参照実装からの採用・変更点

### 6.1 採用する設計

| 項目 | 参照実装 | 採用 |
|-----|---------|------|
| バッファリング | 10フレームごとフラッシュ | ✓ |
| エラー時継続 | 警告のみで録画継続 | ✓ |
| finally句でクリーンアップ | 残りバッファ書き込み | ✓ |

### 6.2 変更する設計

| 項目 | 参照実装 | 本実装 | 理由 |
|-----|---------|--------|------|
| frame_number桁数 | 4桁 | 5桁 | 要件定義による |
| ファイルモード | append ("a") | write ("w") | 毎回新規作成 |
| 出力先 | 固定パス | 動画と同じディレクトリ | 要件定義による |
| フラッシュログ | 出力する | 出力しない | ログ量削減 |

## 7. import追加

```python
import csv
from typing import Any, TextIO  # TextIOを追加
```

## 8. 要調査事項

**なし**

参照実装で以下が確認済み:
- `buf.meta_data.device_frame_number` の取得方法
- `buf.meta_data.device_timestamp_ns` の取得方法
- csv.writerの使用方法
- バッファリング・フラッシュの実装パターン
