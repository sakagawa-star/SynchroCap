# bug-005: Recording Reportのexpected値が間違っている

## Status: Closed (2026-02-09)

## Summary

録画終了後のRecording Reportで表示されるexpected（期待フレーム数）の値が間違っている。

## Reproduction Steps

1. 4台のカメラで録画を実行
2. 録画終了後、ターミナルのRecording Reportを確認

## Expected Behavior

- expected値がtrigger_interval_fpsに基づいて計算される
- 例: duration=3600秒, trigger_interval_fps=30の場合 → expected=108000

## Actual Behavior

- expected値がフレームレート(fps)で計算されている
- 例: duration=3600秒, fps=50の場合 → expected=180000

## Evidence

```
[RecordingController] === Recording Report ===
[RecordingController]   [05520125] frames=108003, expected=180000, delta=-71997
[RecordingController]   [05520126] frames=108004, expected=180000, delta=-71996
[RecordingController]   [05520128] frames=108003, expected=180000, delta=-71997
[RecordingController]   [05520129] frames=108004, expected=180000, delta=-71996
```

実際のフレーム数(約108000)はtrigger_interval_fps=30fpsで計算した値に近い（3600秒 × 30fps = 108000）。
しかしexpected=180000はfps=50fpsで計算した値（3600秒 × 50fps = 180000）。

## Root Cause

`recording_controller.py`の`_cleanup()`メソッドで、expected計算に`slot.fps`を使用しているが、
実際のフレーム取得は`slot.trigger_interval_fps`で行われている。

## Affected Files

- `src/synchroCap/recording_controller.py`

## Related

- bug-004: フレームレート設定が反映されない場合がある（Closed）
