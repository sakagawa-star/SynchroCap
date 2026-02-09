# bug-002: Start after遅延が録画時間に含まれてしまう

## Status: Closed (2026-02-09)

## Summary

GUIの"Start after"で設定した遅延時間が、録画開始の遅延ではなく録画時間に加算されてしまう。

## Reproduction Steps

1. Multi Viewタブで4台のカメラを選択
2. Start after: 10sec, Duration: 10sec に設定
3. Startボタンをクリック
4. 録画完了後、保存された動画を確認

## Expected Behavior

- 10秒待機後に録画開始
- 10秒間録画（300フレーム @ 30fps）
- 合計約10秒の動画ファイル

## Actual Behavior

- 録画が約20秒（598フレーム）
- Start after の10秒が Duration に加算されている

## Evidence

### テスト1: Start after=1sec, Duration=10sec
```
[RecordingController] State: scheduled - Scheduled to start in 1.0s
frames=327, expected=300, delta=+27  (約11秒分)
```

### テスト2: Start after=10sec, Duration=10sec
```
[RecordingController] State: scheduled - Scheduled to start in 10.0s
frames=598, expected=300, delta=+298  (約20秒分)
```

## Affected Files

- `src/synchroCap/recording_controller.py`

## Root Cause Analysis

**原因特定済み**

Trigger設定（TRIGGER_SELECTOR, TRIGGER_SOURCE, TRIGGER_MODE）が
`driver_property_map` に設定されているが、正しくは `device_property_map` に設定すべき。

結果としてカメラがフリーランニングモードのまま動作し、
Action Schedulerによる遅延開始が効かない。

詳細は [investigation.md](investigation.md) を参照。

## Related

- 機能設計書: `docs/feature_design.md`
