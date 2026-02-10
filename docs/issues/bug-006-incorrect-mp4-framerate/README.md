# bug-006: MP4ファイルのフレームレートが正しくない

## Status: Closed (2026-02-10)

## Summary

本番アプリで作成されたMP4ファイルのフレームレートが意図した値になっていない。

## Symptom

- 保存されたMP4ファイルのフレームレートが50fpsで作成されている
- 実際のトリガー間隔（`trigger_interval_fps`、例: 30fps）の値を使用すべき

## Expected Behavior

MP4ファイルのフレームレートは、Action Schedulerのトリガー間隔（`trigger_interval_fps`）と一致するべき。

## Actual Behavior

MP4ファイルのフレームレートがカメラの`ACQUISITION_FRAME_RATE`（`slot.fps` = 50fps）で作成されている。

## Root Cause

`_build_ffmpeg_command()`でffmpegに渡すframerateパラメータに`slot.fps`を使用している。

```python
# src/synchroCap/recording_controller.py:471
"-framerate", f"{slot.fps}",  # slot.fps = 50fps (ACQUISITION_FRAME_RATE)
```

しかし、実際にカメラから取得されるフレームレートはAction Schedulerのトリガー間隔（`slot.trigger_interval_fps`）である。

## Solution

`slot.fps` → `slot.trigger_interval_fps` に変更する。

```python
# 変更前
"-framerate", f"{slot.fps}",

# 変更後
"-framerate", f"{slot.trigger_interval_fps}",
```

## Affected Files

| ファイル | 変更内容 |
|---------|---------|
| `src/synchroCap/recording_controller.py` | L471: `slot.fps` → `slot.trigger_interval_fps` |

## Related

- s12_rec4cams.pyで同様の問題を修正済み（feat-002作業中に発見・修正）
