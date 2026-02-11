# feat-004 機能設計書: 本番アプリへのRaw形式録画機能追加

## 1. 概要

本番アプリの `recording_controller.py` と `ui_multi_view.py` を変更し、MP4形式に加えてSRAWフォーマットによるRaw形式での録画を選択可能にする。

## 2. 変更対象ファイル

| ファイル | 変更種別 |
|---------|---------|
| `src/synchroCap/recording_controller.py` | 修正 |
| `src/synchroCap/ui_multi_view.py` | 修正 |

## 3. recording_controller.py の変更

### 3.1 新規追加: SRAWフォーマット定数

ファイル先頭（import文の後、RecordingState定義の前）に追加する。

```python
# SRAW file format constants
SRAW_MAGIC = b'SRAW'
FRAM_MAGIC = b'FRAM'
SRAW_VERSION = 1
PIXEL_FORMAT_BAYER_GR8 = 0

# SRAW file splitting
DEFAULT_FRAMES_PER_FILE = 1000
```

### 3.2 新規追加: OutputFormat列挙型

RecordingStateの直後に追加する。

```python
class OutputFormat(Enum):
    """出力フォーマット"""
    MP4 = "mp4"
    RAW = "raw"
```

### 3.3 RecordingSlot の拡張

既存フィールドに加え、Raw録画用フィールドを追加する。

```python
@dataclass
class RecordingSlot:
    """各カメラスロットの録画コンテキスト"""
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
    trigger_interval_fps: float = 50.0
    delta_ns: int = 0
    # CSV関連
    csv_path: Optional[Path] = None
    csv_file: Optional[TextIO] = None
    csv_writer: Optional[Any] = None
    csv_buffer: List[List] = field(default_factory=list)
    # Raw録画関連（追加）
    raw_file: Optional[BinaryIO] = None           # 現在書き込み中のRawファイル
    raw_file_start_frame: int = 0                  # 現在のファイルの開始フレーム番号
    raw_files_created: List[str] = field(default_factory=list)  # 作成済みファイル一覧
```

### 3.4 RecordingController のインスタンス変数追加

`__init__` に以下を追加:

```python
self._output_format: OutputFormat = OutputFormat.MP4
self._frames_per_file: int = DEFAULT_FRAMES_PER_FILE
```

### 3.5 prepare() シグネチャ変更

```python
def prepare(
    self,
    slots: List[Dict[str, Any]],
    start_delay_s: float,
    duration_s: float,
    output_format: OutputFormat = OutputFormat.MP4,   # 追加
    frames_per_file: int = DEFAULT_FRAMES_PER_FILE,   # 追加
) -> bool:
```

`prepare()` の先頭でインスタンス変数に保存:

```python
self._output_format = output_format
self._frames_per_file = frames_per_file
```

### 3.6 新規追加: SRAWヘッダ書き込み関数

モジュールレベルの関数として追加する（ミニマムアプリから移植）。

#### `_write_file_header()`

```python
def _write_file_header(
    file: BinaryIO,
    serial: str,
    recording_start_ns: int,
    width: int,
    height: int,
    pixel_format: int,
) -> None:
    """SRAWファイルヘッダ (40 bytes) を書き込む"""
    serial_bytes = serial.encode('ascii')[:15].ljust(16, b'\x00')
    header = struct.pack(
        '<4sI16sqHHHH',
        SRAW_MAGIC,
        SRAW_VERSION,
        serial_bytes,
        recording_start_ns,
        width,
        height,
        pixel_format,
        0,  # reserved
    )
    file.write(header)
```

#### `_write_frame_header()`

```python
def _write_frame_header(
    file: BinaryIO,
    payload_size: int,
    frame_index: int,
    timestamp_ns: int,
) -> None:
    """SRAWフレームヘッダ (24 bytes) を書き込む"""
    header = struct.pack(
        '<4sIQq',
        FRAM_MAGIC,
        payload_size,
        frame_index,
        timestamp_ns,
    )
    file.write(header)
```

### 3.7 _setup_recording() の変更

MP4モードとRawモードで分岐する。共通部分（CSV初期化、プレビュー停止、sink作成、stream_setup）は共有する。

```
_setup_recording():
    for slot in self._slots:
        # [共通] CSV初期化 （既存コードそのまま）

        if self._output_format == OutputFormat.MP4:
            # [MP4] ffmpeg起動 （既存コードそのまま）
            # [MP4] output_path設定: cam{serial}.mp4
        else:
            # [Raw] ffmpegは起動しない
            # [Raw] output_pathは設定しない（ファイルは_worker内で動的に作成）

        # [共通] プレビュー停止 （既存コードそのまま）
        # [共通] 録画用sink作成 （既存コードそのまま）
        # [共通] stream_setup (DEFER) （既存コードそのまま）

    # [Raw] ディスク使用量の推定表示
    if self._output_format == OutputFormat.RAW:
        self._log_raw_disk_estimate()
```

### 3.8 新規追加: _log_raw_disk_estimate()

```python
def _log_raw_disk_estimate(self) -> None:
    """Raw録画の推定ディスク使用量をログ出力"""
    if not self._slots:
        return
    slot = self._slots[0]  # 全カメラ同一解像度前提
    bytes_per_frame = slot.width * slot.height  # BayerGR8: 1 byte/pixel
    expected_frames = int(self._duration_s * slot.trigger_interval_fps)
    per_cam_bytes = expected_frames * bytes_per_frame
    total_bytes = per_cam_bytes * len(self._slots)
    per_cam_gib = per_cam_bytes / (1024 ** 3)
    total_gib = total_bytes / (1024 ** 3)
    self._log(
        f"[RAW] Estimated size: {per_cam_gib:.2f} GiB/camera, "
        f"total {total_gib:.2f} GiB ({len(self._slots)} cameras)"
    )
```

### 3.9 _worker() の変更

MP4モードとRawモードで分岐する。

```
_worker(slot):
    if self._output_format == OutputFormat.MP4:
        _worker_mp4(slot)       # 既存ロジックをそのまま移動
    else:
        _worker_raw(slot)       # 新規
```

#### _worker_mp4() — 既存ロジック

現在の`_worker()`の内容をそのまま `_worker_mp4()` に移動する。変更なし。

#### _worker_raw() — 新規追加

```
_worker_raw(slot):
    serial = slot.serial
    grabber = slot.grabber
    sink = slot.recording_sink

    grabber.acquisition_start()

    end_time = time.monotonic() + self._start_delay_s + self._duration_s
    slot.frame_count = 0
    RAW_FLUSH_INTERVAL = 30  # 30フレームごとにflush

    while time.monotonic() < end_time:
        buf = sink.try_pop_output_buffer()
        if buf is None:
            time.sleep(0.001)
            continue

        md = buf.meta_data
        timestamp = md.device_timestamp_ns

        # CSV記録 （MP4モードと同一のロジック）

        arr = buf.numpy_wrap()
        payload = arr.tobytes()
        payload_size = len(payload)

        # ファイル分割チェック: 最初のフレームまたは分割境界
        if slot.raw_file is None or (
            self._frames_per_file > 0
            and slot.frame_count > 0
            and slot.frame_count % self._frames_per_file == 0
        ):
            # 現在のファイルをクローズ
            if slot.raw_file is not None:
                slot.raw_file.flush()
                slot.raw_file.close()

            # 新しいファイルを開く
            slot.raw_file_start_frame = slot.frame_count
            raw_filename = f"cam{serial}_{slot.frame_count:06d}.raw"
            raw_path = self._output_dir / raw_filename
            slot.raw_file = open(raw_path, "wb")
            slot.raw_files_created.append(str(raw_path))
            self._log(f"[{serial}] New raw file: {raw_filename}")

            # FileHeader書き込み
            _write_file_header(
                slot.raw_file, serial, timestamp,
                slot.width, slot.height, PIXEL_FORMAT_BAYER_GR8,
            )

        # FrameHeader + Payload書き込み
        _write_frame_header(slot.raw_file, payload_size, slot.frame_count, timestamp)
        slot.raw_file.write(payload)
        slot.frame_count += 1

        if slot.frame_count % RAW_FLUSH_INTERVAL == 0:
            slot.raw_file.flush()

        buf.release()

    # 停止処理
    # Rawファイルクローズ
    if slot.raw_file is not None:
        slot.raw_file.flush()
        slot.raw_file.close()
        slot.raw_file = None

    grabber.acquisition_stop()
    grabber.stream_stop()

    self._log(f"[{serial}] Recording finished: {slot.frame_count} frames, "
              f"{len(slot.raw_files_created)} file(s)")
```

### 3.10 _cleanup() の変更

Rawモード固有のクリーンアップを追加する。

```
_cleanup():
    for slot in self._slots:
        # [共通] CSV終了処理 （既存コードそのまま）

        if self._output_format == OutputFormat.MP4:
            # [MP4] ffmpeg終了 （既存コードそのまま）
        else:
            # [Raw] 安全策: raw_fileが閉じられていなければ閉じる
            if slot.raw_file is not None:
                slot.raw_file.flush()
                slot.raw_file.close()
                slot.raw_file = None

        # [共通] 保険的な停止処理 （既存コードそのまま）

    # [共通] レポート出力 （既存コードそのまま、MP4/Raw共通）
```

### 3.11 import文の追加

既存importに `struct` を追加:

```python
import struct  # 追加
```

## 4. ui_multi_view.py の変更

### 4.1 import文の追加

```python
from PySide6.QtWidgets import (
    ...
    QRadioButton,     # 追加
    ...
)
from recording_controller import RecordingController, RecordingState, OutputFormat  # OutputFormat追加
```

### 4.2 _build_ui() への UI追加

Recording GroupBox内の「Duration」行と「Status」行の間に以下を挿入する。

```python
# Output Format ラジオボタン
format_layout = QHBoxLayout()
self.rec_format_mp4 = QRadioButton("MP4", recording_group)
self.rec_format_raw = QRadioButton("Raw", recording_group)
self.rec_format_mp4.setChecked(True)  # デフォルト: MP4
format_layout.addWidget(self.rec_format_mp4)
format_layout.addWidget(self.rec_format_raw)
format_layout.addStretch(1)
recording_layout.addRow("Output Format", format_layout)

# Frames per file (Raw選択時のみ表示)
self.rec_frames_per_file = QSpinBox(recording_group)
self.rec_frames_per_file.setRange(100, 100000)
self.rec_frames_per_file.setValue(1000)
self.rec_frames_per_file_label = QLabel("Frames per file", recording_group)
recording_layout.addRow(self.rec_frames_per_file_label, self.rec_frames_per_file)
self.rec_frames_per_file_label.setVisible(False)
self.rec_frames_per_file.setVisible(False)

# ラジオボタン変更時のハンドラ接続
self.rec_format_mp4.toggled.connect(self._on_output_format_changed)
```

最終的なRecording GroupBoxのaddRow順序:

```
recording_layout.addRow("Start after",     self.rec_start_after_sec)
recording_layout.addRow("Duration",        self.rec_duration_sec)
recording_layout.addRow("Output Format",   format_layout)
recording_layout.addRow(self.rec_frames_per_file_label, self.rec_frames_per_file)
recording_layout.addRow("Status",          self.rec_status_label)
recording_layout.addRow(buttons_layout)
```

### 4.3 新規追加: _on_output_format_changed()

```python
def _on_output_format_changed(self, mp4_checked: bool) -> None:
    """Output Format変更時のハンドラ"""
    is_raw = not mp4_checked
    self.rec_frames_per_file_label.setVisible(is_raw)
    self.rec_frames_per_file.setVisible(is_raw)
```

### 4.4 _on_start_recording() の変更

prepare()呼び出し時に `output_format` と `frames_per_file` を渡す。

```python
# 既存コードの後に追加:
output_format = OutputFormat.RAW if self.rec_format_raw.isChecked() else OutputFormat.MP4
frames_per_file = self.rec_frames_per_file.value()

success = self._recording_controller.prepare(
    slots=active_slots,
    start_delay_s=float(start_delay_s),
    duration_s=float(duration_s),
    output_format=output_format,        # 追加
    frames_per_file=frames_per_file,    # 追加
)
```

### 4.5 _set_recording_ui_enabled() の変更

録画中はOutput Format・Frames per fileも無効化する。

```python
def _set_recording_ui_enabled(self, enabled: bool) -> None:
    """録画関連UIの有効/無効を切り替え"""
    self.rec_start_after_sec.setEnabled(enabled)
    self.rec_duration_sec.setEnabled(enabled)
    self.rec_start_button.setEnabled(enabled)
    self.recording_checkbox.setEnabled(enabled)
    self.lock_tabs_checkbox.setEnabled(enabled)
    # 追加
    self.rec_format_mp4.setEnabled(enabled)
    self.rec_format_raw.setEnabled(enabled)
    self.rec_frames_per_file.setEnabled(enabled)

    if enabled:
        self.rec_status_label.setText("Ready")
```

## 5. 処理フロー

### 5.1 MP4モード（変更なし）

```
[Start]
  → _on_start_recording()
    → prepare(output_format=MP4)
      → Phase 3: PTP待機
      → Phase 4: オフセット計算・スケジュール
      → Phase 5: CSV初期化 → ffmpeg起動 → sink準備
    → start()
      → _worker() → _worker_mp4()
        → acquisition_start
        → フレームループ: buf → ffmpeg stdin.write
        → acquisition_stop / stream_stop
      → _cleanup(): CSV閉 → ffmpeg閉 → Report
```

### 5.2 Rawモード（新規）

```
[Start]
  → _on_start_recording()
    → prepare(output_format=RAW, frames_per_file=1000)
      → Phase 3: PTP待機
      → Phase 4: オフセット計算・スケジュール
      → Phase 5: CSV初期化 → (ffmpegスキップ) → sink準備
      → ディスク使用量推定ログ出力
    → start()
      → _worker() → _worker_raw()
        → acquisition_start
        → フレームループ:
            buf → ファイル分割チェック
                → 新ファイルopen → FileHeader書き込み
            → FrameHeader + Payload書き込み
            → CSV記録
        → Rawファイルclose
        → acquisition_stop / stream_stop
      → _cleanup(): CSV閉 → (ffmpegスキップ) → Rawファイル安全閉 → Report
```

## 6. エラーハンドリング

| エラー | 対処 |
|--------|------|
| Rawファイルopen失敗 (OSError) | ログ出力、ループ脱出、frame_countは途中の値で停止 |
| Rawファイルwrite失敗 (OSError) | ログ出力、ループ脱出 |
| ファイルクローズ失敗 | ログ出力のみ（無視して続行） |

## 7. 影響範囲

### 既存機能への影響

- **MP4録画**: `output_format=MP4`（デフォルト）の場合、既存コードパスがそのまま実行される。動作変更なし。
- **CSV出力**: MP4/Raw共通。変更なし。
- **Recording Report**: MP4/Raw共通。変更なし。
- **プレビュー停止/再開**: MP4/Raw共通。変更なし。

### テスト確認項目

1. MP4モードで録画し、従来と同じ動作をすること
2. Rawモードで録画し、SRAWファイルが正しく作成されること
3. Rawモードで`frames_per_file`を超える録画をし、ファイルが正しく分割されること
4. feat-003ツール(`validate`)でRawファイルの整合性を検証すること
5. Output Format切り替え時にFrames per fileの表示/非表示が正しく動作すること
6. 録画中にOutput Format・Frames per fileが変更不可であること
