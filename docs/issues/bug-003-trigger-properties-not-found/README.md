# bug-003: Triggerプロパティが見つからない

## Status: Closed (2026-02-09)

## Summary

録画開始時にTrigger関連プロパティ（TriggerSelector, TriggerSource, TriggerMode）が
カメラに存在しないためエラーが発生する。

## Reproduction Steps

1. Multi Viewタブで4台のカメラを選択
2. Startボタンをクリック
3. ターミナルにWarningが出力される

## Expected Behavior

- Trigger設定が正常に適用される
- Warningが出力されない

## Actual Behavior

全カメラで以下のWarningが出力される：
```
Warning: failed to set TRIGGER_SELECTOR: Property 'TriggerSelector' not found
Warning: failed to set TRIGGER_SOURCE: Property 'TriggerSource' not found
Warning: failed to set TRIGGER_MODE: Property 'TriggerMode' not found
```

## Evidence

```
[RecordingController] [05520125] Warning: failed to set TRIGGER_SELECTOR:
  (<ErrorCode.GenICamFeatureNotFound: 101>, "ic4_propmap_set_value_string: Property 'TriggerSelector' not found")
[RecordingController] [05520125] Warning: failed to set TRIGGER_SOURCE:
  (<ErrorCode.GenICamFeatureNotFound: 101>, "ic4_propmap_set_value_string: Property 'TriggerSource' not found")
[RecordingController] [05520125] Warning: failed to set TRIGGER_MODE:
  (<ErrorCode.GenICamFeatureNotFound: 101>, "ic4_propmap_set_value_string: Property 'TriggerMode' not found")
```

## Affected Files

- `src/synchroCap/recording_controller.py`

## Root Cause Analysis

### 調査結果

driver_property_mapとdevice_property_mapの両方でTriggerプロパティが見つからない。
カメラハードウェア自体の問題の可能性が高い。

### 試行した対策（リバート済み）

**案B**: `drv_map` → `prop_map` への変更を試行したが、カメラの設定変更全般に影響を及ぼしたため
リバートした（2026-02-06）。

リバート理由: 正常に動作していたテストプログラムも動作しなくなったため、カメラ自体のバグの可能性が高いと判断。

### 現在の対応

Warning出力のみで録画は継続する（参照実装準拠）。
カメラハードウェア/ファームウェアの問題として保留。

## Related

- bug-002: Start after遅延が録画時間に含まれる（関連する可能性あり）
- 機能設計書: `docs/feature_design.md`
