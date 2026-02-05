# Architecture Overview

## システム構成図

```
┌─────────────────────────────────────────────────────────────────┐
│                         MainWindow                               │
│  ┌──────────────┐  ┌─────────────────┐  ┌──────────────────┐   │
│  │ChannelManager│  │ CameraSettings  │  │   MultiView      │   │
│  │   Widget     │  │    Widget       │  │    Widget        │   │
│  │   (Tab1)     │  │    (Tab2)       │  │    (Tab3)        │   │
│  └──────┬───────┘  └────────┬────────┘  └────────┬─────────┘   │
│         │                   │                    │              │
│         │                   │           ┌───────┴───────┐      │
│         │                   │           │ Recording     │      │
│         │                   │           │ Controller    │      │
│         │                   │           └───────┬───────┘      │
└─────────┼───────────────────┼───────────────────┼──────────────┘
          │                   │                   │
          ▼                   ▼                   ▼
    ┌───────────┐      ┌───────────┐       ┌───────────┐
    │ Channel   │      │  Device   │       │ ffmpeg    │
    │ Registry  │      │ Resolver  │       │ (hevc_nvenc)
    │ (JSON)    │      │           │       └───────────┘
    └───────────┘      └─────┬─────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ imagingcontrol4 │
                    │     (IC4)       │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Industrial      │
                    │ Cameras (GigE)  │
                    │ with PTP        │
                    └─────────────────┘
```

## コアコンポーネント

### 1. MainWindow (`mainwindow.py`)

アプリケーションのメインウィンドウ。3つのタブを管理。

- **Tab1**: Channel Manager - カメラとチャンネルIDの紐付け
- **Tab2**: Camera Settings - 個別カメラの設定
- **Tab3**: Multi View - 複数カメラプレビューと録画

### 2. ChannelRegistry (`channel_registry.py`)

カメラとチャンネルIDの対応関係を永続化。

```
ChannelRegistry
├── ChannelEntry (channel_id, device_identity, notes)
│   └── DeviceIdentity (serial, model, unique_name)
└── JSON永続化 (channels.json)
```

**主な責務**:
- チャンネルID（01-99）とカメラシリアルの対応管理
- 重複登録の防止
- JSONファイルへの保存・読み込み

### 3. DeviceResolver (`device_resolver.py`)

ChannelEntryから実際のカメラデバイスを解決。

- シリアル番号またはunique_nameでデバイスを検索
- 接続状態の取得

### 4. MultiViewWidget (`ui_multi_view.py`)

4カメラ同時プレビューと録画制御のUI。

```
MultiViewWidget
├── 4つのカメラスロット
│   ├── DisplayWidget (プレビュー)
│   ├── Grabber (カメラ制御)
│   └── QueueSink (フレーム受信)
├── 録画設定UI
│   ├── Start after (開始遅延)
│   └── Duration (録画時間)
└── RecordingController (録画制御)
```

### 5. RecordingController (`recording_controller.py`)

PTP同期録画のライフサイクル管理。

```
RecordingController
├── RecordingState (状態管理)
│   └── IDLE → PREPARING → SCHEDULED → RECORDING → STOPPING → IDLE
├── RecordingSlot (カメラ毎のコンテキスト)
│   ├── Grabber
│   ├── QueueSink (録画用)
│   └── ffmpegプロセス
└── 録画スレッド (1カメラ = 1スレッド)
```

**録画フロー**:
1. PTP Slave状態の待機
2. タイムスタンプオフセット計算
3. Action Scheduler設定
4. ffmpeg起動
5. DEFER_ACQUISITION_STARTでストリーム準備
6. 録画スレッドでフレーム取得→ffmpegへパイプ

## データフロー

### プレビュー時

```
Camera → IC4 Grabber → QueueSink → DisplayWidget
```

### 録画時

```
Camera → IC4 Grabber → QueueSink → Recording Thread → ffmpeg stdin → MP4
                                   (numpy_wrap → tobytes)
```

## 同期メカニズム

### PTP (IEEE 1588)

- 全カメラがPTP Slaveとして動作
- 外部PTP Grandmasterと同期

### Action Scheduler

- カメラ内蔵のスケジューラ機能
- `ActionSchedulerTime`: 開始時刻（ナノ秒）
- `ActionSchedulerInterval`: フレーム間隔（マイクロ秒）
- Action0 → FrameStartトリガー

### オフセット計算

```
TIMESTAMP_LATCH → カメラ時刻取得
delta_ns = camera_time_ns - host_time_ns
camera_target_ns = host_target_ns + delta_ns
```

## 外部依存

| ライブラリ | 用途 |
|-----------|------|
| imagingcontrol4 | カメラ制御SDK |
| PySide6 | GUI (Qt6) |
| ffmpeg | 動画エンコード |
| hevc_nvenc | NVIDIA GPUエンコーダ |

## ファイル構成

```
src/synchroCap/
├── main.py                 # エントリーポイント
├── mainwindow.py           # メインウィンドウ
├── channel_registry.py     # チャンネル管理
├── device_resolver.py      # デバイス解決
├── ui_channel_manager.py   # Tab1: チャンネル管理UI
├── ui_camera_settings.py   # Tab2: カメラ設定UI
├── ui_multi_view.py        # Tab3: マルチビュー・録画UI
├── recording_controller.py # 録画制御ロジック
├── ptp_sync_check.py       # PTP同期確認
├── chktimestat.py          # タイムスタンプ統計
└── resourceselector.py     # リソース管理
```
