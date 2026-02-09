# Investigation: bug-002

## Root Cause: CONFIRMED

**Trigger設定が誤ったPropertyMapに適用されている**

## 調査ログ

### 症状の分析

| テスト | Start after | Duration | 期待フレーム | 実際フレーム | 差分 |
|-------|------------|----------|-------------|-------------|------|
| 1 | 1sec | 10sec | 300 | 327 | +27 (~0.9sec) |
| 2 | 10sec | 10sec | 300 | 598 | +298 (~10sec) |

差分がほぼ `start_delay_s` と一致 → カメラがフリーランニングモードで動作している

### 問題箇所

**recording_controller.py:340-354**

```python
def _configure_action_scheduler(self, slot: RecordingSlot) -> bool:
    prop_map = slot.grabber.device_property_map
    drv_map = slot.grabber.driver_property_map

    # Trigger設定（失敗しても警告のみで続行 - 参照実装準拠）
    try:
        drv_map.set_value(ic4.PropId.TRIGGER_SELECTOR, "FrameStart")  # ← ここが問題
    except ic4.IC4Exception as e:
        ...
    try:
        drv_map.set_value(ic4.PropId.TRIGGER_SOURCE, "Action0")       # ← ここが問題
    except ic4.IC4Exception as e:
        ...
    try:
        drv_map.set_value(ic4.PropId.TRIGGER_MODE, "On")              # ← ここが問題
    except ic4.IC4Exception as e:
        ...
```

### なぜ動かないのか

1. Trigger設定（TRIGGER_SELECTOR, TRIGGER_SOURCE, TRIGGER_MODE）は**カメラのプロパティ**
2. これらは `device_property_map` (`prop_map`) に設定すべき
3. 現在は `driver_property_map` (`drv_map`) に設定している
4. 結果: Trigger設定が効かず、カメラはフリーランニングモードのまま
5. Action Schedulerは設定されているが、TriggerModeがOffのため無視される

### 正しい動作フロー（期待）

```
t=0                    t=start_delay          t=start_delay+duration
|----------------------|----------------------|
  Trigger待機           フレーム取得開始        終了
  (フレームなし)        (Action Scheduler発火)
```

### 現在の動作フロー（実際）

```
t=0                                           t=start_delay+duration
|---------------------------------------------|
  フリーランニングでフレーム取得               終了
  (Trigger設定が効いていない)
```

## 解決策

`drv_map` を `prop_map` に変更:

```python
def _configure_action_scheduler(self, slot: RecordingSlot) -> bool:
    prop_map = slot.grabber.device_property_map

    # Trigger設定
    try:
        prop_map.set_value(ic4.PropId.TRIGGER_SELECTOR, "FrameStart")  # prop_mapに変更
    ...
    try:
        prop_map.set_value(ic4.PropId.TRIGGER_SOURCE, "Action0")       # prop_mapに変更
    ...
    try:
        prop_map.set_value(ic4.PropId.TRIGGER_MODE, "On")              # prop_mapに変更
```

## 影響範囲

- `src/synchroCap/recording_controller.py` の `_configure_action_scheduler` メソッド
- 3箇所の `drv_map` → `prop_map` 変更

## 結論

**原因解明完了。Trigger設定のPropertyMapが誤っている。**
