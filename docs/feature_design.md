# 機能設計書: PTP同期複数カメラ録画機能

対象: `ic4.demoapp/demoapp.py`
基準文書: `requirements.md`
参照実装: `debug.demoapp/s10_rec4cams.py`
調査記録: `investigation.md`

---

## 1. 機能概要

### 1.1 機能名
PTP同期複数カメラ同時録画（Multi-Camera PTP Synchronized Recording）

### 1.2 機能説明
Multi Viewタブにおいて、PTP同期された複数カメラ（最大4台）のFrameStartをAction Scheduler（Action0）で同時発火させ、各カメラの映像をMP4形式で録画する。

---

## 2. システム構成

### 2.1 コンポーネント図

```
┌─────────────────────────────────────────────────────────────┐
│                      MainWindow                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                    QTabWidget                         │  │
│  │  ┌─────────────┬─────────────┬─────────────────────┐  │  │
│  │  │ Tab1        │ Tab2        │ Tab3                │  │  │
│  │  │ Channel     │ Camera      │ MultiViewWidget     │  │  │
│  │  │ Manager     │ Settings    │ (録画機能追加対象)  │  │  │
│  │  └─────────────┴─────────────┴─────────────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 関連ファイル

| ファイル | 役割 | 変更種別 |
|---------|------|---------|
| `ui_multi_view.py` | 録画UIと録画制御ロジック | 主要変更 |
| `mainwindow.py` | タブロック連携（既存機能を活用） | 軽微変更 |
| `recording_controller.py` | 録画制御クラス（新規） | 新規作成 |

---

## 3. クラス設計

### 3.1 RecordingController クラス（新規）

録画のライフサイクル全体を管理する専用クラス。

```
RecordingController
├── 属性
│   ├── _slots: List[RecordingSlot]        # 録画対象スロット
│   ├── _state: RecordingState             # 状態（IDLE/PREPARING/RECORDING/STOPPING）
│   ├── _start_delay_s: float              # 開始遅延（秒）
│   ├── _duration_s: float                 # 録画時間（秒）
│   ├── _output_dir: Path                  # 出力ディレクトリ
│   ├── _threads: Dict[str, Thread]        # 録画スレッド
│   └── _host_target_ns: int               # スケジュール開始時刻（ns）
│
├── 公開メソッド
│   ├── prepare(slots, start_delay_s, duration_s) -> bool
│   ├── start() -> bool
│   ├── is_recording() -> bool
│   └── get_state() -> RecordingState
│
└── 内部メソッド
    ├── _wait_all_slaves() -> bool
    ├── _calculate_offsets() -> Dict[str, int]
    ├── _schedule_action(delta_map) -> int
    ├── _configure_trigger(grabber)
    ├── _worker(slot) -> int
    └── _cleanup()
```

### 3.2 RecordingSlot データクラス（新規）

各カメラスロットの録画コンテキスト。

```
@dataclass
RecordingSlot
├── serial: str
├── grabber: ic4.Grabber                    # 既存Grabber（スロットから取得）
├── recording_sink: ic4.QueueSink           # 録画専用sink（新規作成）
├── recording_listener: QueueSinkListener   # 録画専用リスナー（新規作成）
├── ffmpeg_proc: subprocess.Popen | None
├── output_path: Path
├── frame_count: int
├── width: int                              # カメラから動的取得
├── height: int                             # カメラから動的取得
└── fps: float                              # カメラから動的取得
```

**注**: 録画用sinkはプレビュー用sinkとは別に新規作成する（INV-002）。

### 3.3 RecordingState 列挙型（新規）

```
class RecordingState(Enum):
    IDLE = "idle"
    PREPARING = "preparing"      # PTP待機・オフセット計算中
    SCHEDULED = "scheduled"      # スケジュール確定、開始待ち
    RECORDING = "recording"      # 録画中
    STOPPING = "stopping"        # 停止処理中
```

---

## 4. シーケンス設計

### 4.1 録画開始シーケンス

```
User        MultiViewWidget    RecordingController    Camera(Grabber)    ffmpeg
 │                │                    │                    │              │
 │──[Start]──────>│                    │                    │              │
 │                │                    │                    │              │
 │                │──prepare()────────>│                    │              │
 │                │                    │──wait_all_slaves()─>│              │
 │                │                    │<──Slave確認────────│              │
 │                │                    │                    │              │
 │                │                    │──TIMESTAMP_LATCH──>│              │
 │                │                    │<──camera_time_ns───│              │
 │                │                    │                    │              │
 │                │                    │──calculate delta───│              │
 │                │                    │                    │              │
 │                │                    │──configure_trigger─>│              │
 │                │                    │  (FrameStart=Action0)              │
 │                │                    │                    │              │
 │                │                    │──ACTION_SCHEDULER_TIME────────────>│
 │                │                    │──ACTION_SCHEDULER_COMMIT──────────>│
 │                │                    │                    │              │
 │                │<──prepare完了──────│                    │              │
 │                │                    │                    │              │
 │                │──start()──────────>│                    │              │
 │                │                    │                    │              │
 │                │                    │──Popen(ffmpeg)────────────────────>│
 │                │                    │                    │              │
 │                │                    │──stream_setup(DEFER)>│              │
 │                │                    │                    │              │
 │                │                    │──Thread.start()────│              │
 │                │                    │   └─acquisition_start()            │
 │                │                    │                    │              │
 │                │                    │      [Action0発火時刻到達]          │
 │                │                    │                    │──FrameStart──>│
 │                │                    │                    │              │
```

### 4.2 録画中フレーム処理シーケンス

```
Camera          QueueSink        RecordingThread        ffmpeg
  │                 │                   │                  │
  │──frame─────────>│                   │                  │
  │                 │                   │                  │
  │                 │<─pop_output_buffer│                  │
  │                 │──buffer──────────>│                  │
  │                 │                   │                  │
  │                 │                   │──tobytes()       │
  │                 │                   │──stdin.write()──>│
  │                 │                   │                  │
  │                 │                   │──buf.release()   │
  │                 │                   │                  │
```

### 4.3 録画停止シーケンス（Duration経過時）

```
RecordingThread    Grabber    ffmpeg    RecordingController
      │               │          │              │
      │ [duration経過]│          │              │
      │               │          │              │
      │──flush()─────────────────>│              │
      │──acquisition_stop()──────>│              │
      │──stream_stop()───────────>│              │
      │──Thread終了──────────────────────────────>│
      │               │          │              │
      │               │          │   [全スレッド終了後]
      │               │          │              │──stdin.close()─>│
      │               │          │              │──wait()─────────>│
      │               │          │              │
      │               │          │              │──acquisition_stop(保険)
      │               │          │              │──stream_stop(保険)
      │               │          │              │──device_close()
```

---

## 5. データフロー設計

### 5.1 時刻計算フロー

```
┌──────────────────────────────────────────────────────────────────┐
│ 入力                                                             │
│   start_delay_s: float (GUI入力、相対秒)                         │
│   duration_s: float (GUI入力)                                    │
└─────────────────────────────────────┬────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 1: ホスト参照時刻取得                                        │
│   host_ref_before_ns = time.time_ns()                            │
│   [TIMESTAMP_LATCH実行]                                          │
│   host_ref_after_ns = time.time_ns()                             │
│   host_ref_ns = (host_ref_before_ns + host_ref_after_ns) // 2    │
└─────────────────────────────────────┬────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 2: カメラ時刻取得（各カメラ）                                │
│   camera_time_ns = TIMESTAMP_LATCH_VALUE                         │
└─────────────────────────────────────┬────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 3: オフセット計算（各カメラ）                                │
│   delta_ns = camera_time_ns - host_ref_ns                        │
└─────────────────────────────────────┬────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 4: スケジュール時刻計算                                      │
│   host_target_ns = time.time_ns() + start_delay_s * 1e9          │
│   camera_target_ns = host_target_ns + delta_ns (各カメラ)        │
└─────────────────────────────────────┬────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 5: Action Scheduler設定（各カメラ）                          │
│   ACTION_SCHEDULER_TIME = camera_target_ns                       │
│   ACTION_SCHEDULER_COMMIT = True                                 │
└──────────────────────────────────────────────────────────────────┘
```

### 5.2 ファイル出力構造

```
captures/
└── YYYYMMDD-HHmmss/           # スケジュール確定時刻
    ├── cam05520125.mp4
    ├── cam05520126.mp4
    ├── cam05520128.mp4
    └── cam05520129.mp4
```

---

## 6. GUI設計

### 6.1 Recording GroupBox（既存UIを活用・拡張）

現在の `ui_multi_view.py` に存在する Recording GroupBox を拡張。

```
┌─ Recording ─────────────────────────────────┐
│                                             │
│  Start after  [    8    ] sec               │
│  Duration     [   30    ] sec               │
│                                             │
│  Status: [                              ]   │  ← 新規追加
│                                             │
│  [ Start ]  [ Stop ]                        │
│                                             │
└─────────────────────────────────────────────┘
```

### 6.2 UI状態遷移

| 状態 | Start after | Duration | Start | Stop | Status表示 |
|------|-------------|----------|-------|------|-----------|
| IDLE | 編集可 | 編集可 | 有効 | 無効 | "Ready" |
| PREPARING | 無効 | 無効 | 無効 | 無効 | "Waiting for PTP..." |
| SCHEDULED | 無効 | 無効 | 無効 | 無効 | "Scheduled: HH:MM:SS" |
| RECORDING | 無効 | 無効 | 無効 | 無効 | "Recording... XX sec" |
| STOPPING | 無効 | 無効 | 無効 | 無効 | "Stopping..." |

---

## 7. カメラ設定

### 7.1 Trigger設定（各カメラ共通）

| プロパティ | 値 | 設定先 |
|-----------|-----|-------|
| TriggerSelector | FrameStart | driver_property_map |
| TriggerSource | Action0 | driver_property_map |
| TriggerMode | On | driver_property_map |

### 7.2 Action Scheduler設定（各カメラ個別）

| プロパティ | 値 | 備考 |
|-----------|-----|------|
| ACTION_SCHEDULER_CANCEL | True | 既存スケジュールキャンセル |
| ACTION_SCHEDULER_TIME | camera_target_ns | カメラ時刻基準（単位: ns） |
| ACTION_SCHEDULER_INTERVAL | round(1_000_000 / fps) | **必須**: 連続フレーム取得間隔（単位: μs） |
| ACTION_SCHEDULER_COMMIT | True | スケジュール確定 |

**ACTION_SCHEDULER_INTERVAL について（INV-005）**:
- **役割**: Action0の発火間隔を指定。これがないと最初の1フレームのみ取得される。
- **計算式**: `interval_us = round(1_000_000 / fps)` (例: 30fps → 33333μs)
- **動作**: ACTION_SCHEDULER_TIME で最初のAction0が発火し、以後 INTERVAL ごとに繰り返し発火

---

## 8. ffmpeg設定

### 8.1 コマンドライン構成

```bash
ffmpeg \
  -hide_banner -nostats -loglevel error \
  -f rawvideo \
  -pix_fmt bayer_grbg8 \
  -s {WIDTH}x{HEIGHT} \
  -framerate {FRAME_RATE} \
  -i - \
  -vf format=yuv420p \
  -c:v hevc_nvenc \
  -b:v 2200k -maxrate 2200k -bufsize 4400k \
  -preset p4 \
  {output_path}
```

### 8.2 固定パラメータ

| パラメータ | 値 | 備考 |
|-----------|-----|------|
| 入力形式 | rawvideo | stdin入力 |
| ピクセルフォーマット | bayer_grbg8 | BayerGR8対応 |
| エンコーダ | hevc_nvenc | NVIDIA GPU必須 |
| ビットレート | 2200kbps | CBR相当 |
| プリセット | p4 | 品質/速度バランス |

---

## 9. エラーハンドリング方針

本フェーズでは高度なエラーハンドリングは対象外。以下の基本方針のみ適用。

### 9.1 録画開始前のエラー（全体中止）

| 状況 | 対応 |
|------|------|
| PTP Slave待機タイムアウト（30秒） | **全体中止**、エラーメッセージ表示、IDLE状態に戻る |
| ffmpeg起動失敗 | **全体中止**、エラーメッセージ表示、IDLE状態に戻る |

**理由（INV-006, INV-007）**: 同期録画の目的上、一部カメラのみの録画は意味をなさないため。

**エラーメッセージ例**:
- PTP失敗: `"PTP synchronization failed. Please check camera connections."`
- ffmpeg失敗: `"Failed to start ffmpeg encoder."`

### 9.2 録画中のエラー（継続または早期停止）

| 状況 | 対応 |
|------|------|
| ffmpeg異常終了（録画中） | 該当カメラのみ早期停止 |
| フレーム書き込み失敗 | Warning出力、継続 |
| デバイスロスト | 該当スロットのみ停止（既存動作） |

---

## 10. スレッドモデル

### 10.1 スレッド構成

```
┌─────────────────────────────────────────────────────────────┐
│ Main Thread (Qt Event Loop)                                 │
│   ├── UI更新                                                │
│   ├── タイマー処理                                          │
│   └── RecordingController.prepare() / start() 呼び出し      │
└─────────────────────────────────────────────────────────────┘
         │
         │ Thread.start()
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Recording Threads (1カメラ = 1スレッド)                      │
│   ├── CaptureThread-05520125                                │
│   ├── CaptureThread-05520126                                │
│   ├── CaptureThread-05520128                                │
│   └── CaptureThread-05520129                                │
│                                                             │
│   各スレッドの責務:                                          │
│     1. acquisition_start()                                  │
│     2. QueueSink.pop_output_buffer() ループ                 │
│     3. ffmpeg stdin書き込み                                 │
│     4. Duration経過で停止処理                               │
└─────────────────────────────────────────────────────────────┘
```

### 10.2 同期ポイント

| ポイント | 同期方法 |
|---------|---------|
| 全カメラPTP Slave確認 | ポーリング + タイムアウト |
| Action Scheduler設定 | 順次実行（メインスレッド） |
| 録画スレッド開始 | 順次Thread.start() |
| 録画スレッド終了待機 | Thread.join() |

---

## 11. 既存コードとの統合

### 11.1 MultiViewWidget 変更点

| 項目 | 現状 | 変更後 |
|------|------|--------|
| `_recording` フラグ | シミュレーション用 | 実録画状態管理 |
| `rec_start_button` | 未接続 | `_on_start_recording` 接続 |
| `rec_stop_button` | 未接続 | 無効化（本フェーズ対象外） |
| Recording GroupBox | GUI only表示 | 実機能として動作 |

**前提条件（INV-008）: 録画中はチャンネル変更不可**

本フェーズでは、録画中にユーザーがコンボボックスでチャンネル変更しないことを前提とする。
- 既存のタブロック機能により、他タブへの遷移は防止される
- コンボボックスの無効化は次回改修で実装予定
- 録画中の `_slot_start()` / `_slot_stop()` 呼び出しは想定しない

### 11.2 Grabber/Sink/Display 併用と録画中プレビュー

**本フェーズの方針（INV-001）: 録画中はプレビュー停止**

技術的にはDisplay + QueueSinkの併用は可能だが、`stream_setup()` 再呼び出し時に
`stream_stop()` が必要でプレビューが途切れる。シンプルさを優先し、本フェーズでは
録画中のプレビューは停止する。

```python
# 録画開始時のシーケンス
if grabber.is_streaming:
    grabber.stream_stop()  # プレビュー停止

# 録画用sinkを新規作成（INV-002: 既存sinkは再利用しない）
recording_listener = _RecordingQueueSinkListener()
recording_sink = ic4.QueueSink(recording_listener,
                               accepted_pixel_formats=[ic4.PixelFormat.BayerGR8])

# DEFER_ACQUISITION_STARTで録画用にsetup
grabber.stream_setup(
    recording_sink,
    setup_option=ic4.StreamSetupOption.DEFER_ACQUISITION_START,
)
recording_sink.alloc_and_queue_buffers(500)

# Action Scheduler設定後、録画スレッド内で acquisition_start()
```

**次回改修で検討**: 録画中もプレビュー継続（Display併用）

### 11.3 タブロック連携

既存の `set_tabs_locked()` / `tabs_lock_changed` シグナルを活用。

```python
# 録画開始時
self.tabs_lock_changed.emit(True)

# 録画終了時
self.tabs_lock_changed.emit(False)
```

---

## 12. 定数・設定値

### 12.1 カメラ設定

**方針（INV-004）: カメラ現在値を動的取得**

録画開始時に各カメラの `device_property_map` から以下を取得する。

| パラメータ | 取得方法 | 備考 |
|-----------|---------|------|
| WIDTH | `grabber.device_property_map.get_value_int(ic4.PropId.WIDTH)` | 動的取得 |
| HEIGHT | `grabber.device_property_map.get_value_int(ic4.PropId.HEIGHT)` | 動的取得 |
| FRAME_RATE | `grabber.device_property_map.get_value_float(ic4.PropId.ACQUISITION_FRAME_RATE)` | 動的取得 |
| PIXEL_FORMAT | 固定: `BayerGR8` | 要求仕様より固定 |

**注**: 取得した値は `RecordingSlot` に保持し、ffmpegコマンド構築時に使用する。

### 12.2 PTP設定

| 定数名 | 値 | 備考 |
|--------|-----|------|
| PTP_SLAVE_TIMEOUT_S | 30.0 | Slave待機タイムアウト |
| PTP_POLL_INTERVAL_S | 1.0 | ポーリング間隔 |
| OFFSET_THRESHOLD_MS | 3.0 | オフセット閾値（将来用） |

### 12.3 バッファ設定

| 定数名 | 値 | 備考 |
|--------|-----|------|
| QUEUE_BUFFER_COUNT | 500 | QueueSinkバッファ数 |
| FFMPEG_FLUSH_INTERVAL | 30 | フレーム単位 |

---

## 13. 出力ディレクトリ

| パス | 説明 |
|------|------|
| `captures/` | 録画ファイルルート |
| `captures/YYYYMMDD-HHmmss/` | セッションディレクトリ |
| `captures/YYYYMMDD-HHmmss/cam{serial}.mp4` | 各カメラのMP4ファイル |

---

## 14. 実装順序（推奨）

1. **Phase 1**: `RecordingSlot`, `RecordingState` データ構造作成
2. **Phase 2**: `RecordingController` 基本構造作成
3. **Phase 3**: PTP Slave待機機能実装
4. **Phase 4**: オフセット計算・スケジュール設定実装
5. **Phase 5**: ffmpeg起動・録画スレッド実装
6. **Phase 6**: Duration自動停止・クリーンアップ実装
7. **Phase 7**: `MultiViewWidget` UI統合
8. **Phase 8**: 結合テスト

---

## 付録A: 参照実装との対応表

| 参照実装（s10_rec4cams.py） | 本設計 |
|----------------------------|--------|
| `_wait_for_cameras_slave()` | `RecordingController._wait_all_slaves()` |
| `_check_offsets_and_schedule()` | `RecordingController._calculate_offsets()` + `_schedule_action()` |
| `configure_camera_for_bayer_gr8()` | `RecordingController._configure_trigger()` |
| `allocate_queue_sink()` | `RecordingSlot` 初期化時 |
| `record_raw_frames()` | `RecordingController._worker()` |
| `_worker()` | `RecordingController._worker()` |
| `build_ffmpeg_command()` | `RecordingController._build_ffmpeg_command()` |

---

## 付録B: 用語集

| 用語 | 説明 |
|------|------|
| PTP | Precision Time Protocol (IEEE 1588) |
| Action Scheduler | カメラ内蔵の時刻ベーストリガー機構 |
| Action0 | Action Schedulerのアクション識別子 |
| FrameStart | フレーム取得開始トリガー |
| TIMESTAMP_LATCH | カメラ内部時刻をラッチするコマンド |
| DEFER_ACQUISITION_START | stream_setup時にacquisition開始を遅延するオプション |
| QueueSink | フレームバッファキュー |
| hevc_nvenc | NVIDIA GPUのHEVCエンコーダ |
