# s12_rec4cams.py 録画フロー修正設計書

## 1. 問題の概要

MP4形式保存で0フレームになる問題。本番アプリと処理フローが異なることが原因と推定。

## 2. 現状分析

### 2.1 本番アプリのフロー (正常動作)

```
Phase 3: _wait_all_slaves()
         └─ PTP Slave待機

Phase 4: _calculate_and_schedule()
         └─ _configure_action_scheduler()
            ├─ Trigger設定
            │   ├─ TRIGGER_SELECTOR = "FrameStart"
            │   ├─ TRIGGER_SOURCE = "Action0"
            │   └─ TRIGGER_MODE = "On"
            └─ Action Scheduler設定
                ├─ CANCEL
                ├─ TIME
                ├─ INTERVAL
                └─ COMMIT

Phase 5: _setup_recording()
         └─ stream_setup()

Phase 6: acquisition_start()
```

### 2.2 s12_rec4cams.py の現状フロー (問題あり)

```
1. configure_camera_for_bayer_gr8()
   ├─ カメラ設定 (WIDTH, HEIGHT, PIXEL_FORMAT, FRAME_RATE)
   ├─ Action Scheduler設定 (1回目)  ← 無駄な設定
   │   ├─ CANCEL
   │   ├─ TIME = device_time + 10s
   │   ├─ INTERVAL
   │   └─ COMMIT
   └─ Trigger設定
       ├─ TRIGGER_SELECTOR
       ├─ TRIGGER_SOURCE
       └─ TRIGGER_MODE

2. allocate_queue_sink()
   └─ stream_setup()  ★ 問題: Action Scheduler設定前にstream_setup

3. _wait_for_cameras_slave()
   └─ PTP Slave待機

4. _check_offsets_and_schedule()
   └─ Action Scheduler設定 (2回目)
       ├─ CANCEL  ★ 問題: Trigger設定が影響を受ける可能性
       ├─ TIME = synchronized_time
       ├─ INTERVAL
       └─ COMMIT
       (Trigger設定なし!)  ★ 問題

5. acquisition_start()
```

### 2.3 主要な違い

| 項目 | 本番アプリ | s12_rec4cams.py |
|------|-----------|-----------------|
| stream_setup の位置 | Action Scheduler設定の**後** | Action Scheduler設定の**間** |
| Trigger設定の位置 | 最終CANCEL直前 | 最初のCOMMIT後 |
| Action Scheduler設定回数 | 1回 | 2回 |

## 3. 修正方針

### 3.1 修正案A: フロー順序の変更 (推奨)

本番アプリと同じフローにする。

**変更後のフロー:**
```
1. カメラ設定のみ
   └─ configure_camera_basic() (新規関数)
       └─ WIDTH, HEIGHT, PIXEL_FORMAT, FRAME_RATE のみ

2. _wait_for_cameras_slave()
   └─ PTP Slave待機

3. _configure_and_schedule() (関数名変更)
   ├─ Trigger設定  ← 追加
   └─ Action Scheduler設定 (1回のみ)
       ├─ CANCEL
       ├─ TIME = synchronized_time
       ├─ INTERVAL
       └─ COMMIT

4. allocate_queue_sink()  ← 移動
   └─ stream_setup()

5. ffmpeg起動  ← 移動

6. acquisition_start()
```

### 3.2 修正案B: Trigger設定の追加のみ (最小変更)

フロー順序は変えず、_check_offsets_and_schedule()にTrigger設定を追加。

**変更内容:**
- `_check_offsets_and_schedule()`でCANCEL前にTrigger設定を追加

## 4. 詳細設計 (案A)

### 4.1 変更対象関数

| 関数 | 変更種別 | 内容 |
|------|---------|------|
| `configure_camera_for_bayer_gr8()` | 修正 | Action Scheduler/Trigger設定を削除、名前を`configure_camera_basic()`に変更 |
| `_check_offsets_and_schedule()` | 修正 | Trigger設定を追加、名前を`_configure_and_schedule()`に変更 |
| `allocate_queue_sink()` | 変更なし | - |
| `main()` | 修正 | 処理順序を変更 |

### 4.2 configure_camera_basic() (旧 configure_camera_for_bayer_gr8)

**変更前 (284-350行目):**
```python
def configure_camera_for_bayer_gr8(
    serial: str, grabber: ic4.Grabber, width: int, height: int, fps: float,
    trigger_interval_fps: float,
) -> None:
    dmap = grabber.device_property_map
    # カメラ設定
    dmap.set_value(ic4.PropId.WIDTH, width)
    dmap.set_value(ic4.PropId.HEIGHT, height)
    dmap.set_value(ic4.PropId.PIXEL_FORMAT, "BayerGR8")
    dmap.set_value(ic4.PropId.ACQUISITION_FRAME_RATE, float(fps))

    # Action Scheduler設定 (削除対象)
    ...

    # Trigger設定 (削除対象)
    ...
```

**変更後:**
```python
def configure_camera_basic(
    serial: str, grabber: ic4.Grabber, width: int, height: int, fps: float,
) -> None:
    """カメラ基本設定のみ (Action Scheduler/Triggerは別途設定)"""
    dmap = grabber.device_property_map
    try:
        dmap.set_value(ic4.PropId.WIDTH, width)
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to set WIDTH", e)
    try:
        dmap.set_value(ic4.PropId.HEIGHT, height)
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to set HEIGHT", e)
    try:
        dmap.set_value(ic4.PropId.PIXEL_FORMAT, "BayerGR8")
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to set PIXEL_FORMAT BayerGR8", e)
    try:
        dmap.set_value(ic4.PropId.ACQUISITION_FRAME_RATE, float(fps))
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to set ACQUISITION_FRAME_RATE", e)
```

### 4.3 _configure_and_schedule() (旧 _check_offsets_and_schedule)

**追加内容 (CANCEL前に):**
```python
# Trigger設定
try:
    prop_map.set_value(ic4.PropId.TRIGGER_SELECTOR, "FrameStart")
except ic4.IC4Exception as e:
    sys.stderr.write(f"[{serial}] Warning: failed to set TRIGGER_SELECTOR: {e}\n")
try:
    prop_map.set_value(ic4.PropId.TRIGGER_SOURCE, "Action0")
except ic4.IC4Exception as e:
    sys.stderr.write(f"[{serial}] Warning: failed to set TRIGGER_SOURCE: {e}\n")
try:
    prop_map.set_value(ic4.PropId.TRIGGER_MODE, "On")
except ic4.IC4Exception as e:
    sys.stderr.write(f"[{serial}] Warning: failed to set TRIGGER_MODE: {e}\n")

# Action Scheduler設定 (既存)
prop_map.try_set_value(ic4.PropId.ACTION_SCHEDULER_CANCEL, True)
prop_map.set_value(ic4.PropId.ACTION_SCHEDULER_TIME, int(camera_target_ns))
prop_map.set_value(ic4.PropId.ACTION_SCHEDULER_INTERVAL, interval_us)
prop_map.try_set_value(ic4.PropId.ACTION_SCHEDULER_COMMIT, True)
```

### 4.4 main() の処理順序変更

**変更前:**
```python
for serial in SERIAL_NUMBERS:
    grabber.device_open(device_info)
    _ensure_camera_ptp_enabled(grabber)
    configure_camera_for_bayer_gr8(...)  # Action Scheduler + Trigger含む
    sink, listener = allocate_queue_sink(...)  # stream_setup
    # ffmpeg起動
    camera_contexts[serial] = {...}

_wait_for_cameras_slave(camera_contexts)
_check_offsets_and_schedule(...)  # Action Scheduler 2回目
# スレッド開始
```

**変更後:**
```python
# Phase 1: カメラオープンと基本設定
for serial in SERIAL_NUMBERS:
    grabber.device_open(device_info)
    _ensure_camera_ptp_enabled(grabber)
    configure_camera_basic(...)  # カメラ設定のみ
    camera_contexts[serial] = {"grabber": grabber, "device_info": device_info}

# Phase 2: PTP待機
_wait_for_cameras_slave(camera_contexts)

# Phase 3: Trigger + Action Scheduler設定
_configure_and_schedule(...)

# Phase 4: stream_setup + ffmpeg起動
for serial, ctx in camera_contexts.items():
    grabber = ctx["grabber"]
    sink, listener = allocate_queue_sink(grabber, WIDTH, HEIGHT)
    ctx["sink"] = sink
    ctx["listener"] = listener
    # ffmpeg起動
    ...

# Phase 5: スレッド開始
```

## 5. 影響範囲

| ファイル | 変更内容 |
|---------|---------|
| `s12_rec4cams.py` | 上記全ての変更 |

## 6. テスト計画

1. MP4モードで録画実行
2. フレーム数が正常 (expected ≒ actual) であることを確認
3. 生成されたMP4ファイルが再生可能であることを確認
