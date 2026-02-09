# inv-001: PixelFormat/Trigger設定の検証

## Status: Closed (2026-02-09)

## Summary

bug-003（Triggerプロパティが見つからない）の原因切り分けのための検証用ミニマムアプリ。
PixelFormatとTrigger設定の関係を調査する。

## Background

- bug-003: `driver_property_map`でTriggerプロパティが見つからない
- 対策（drv_map → prop_map）を試行したが、カメラ設定全般に影響が出たためリバート
- Action Schedulerが設定通りに動作しない（約10秒早く録画開始）

## Investigation Target

1. PixelFormatの設定とTriggerプロパティの関係
2. device_property_map vs driver_property_map の挙動差異
3. Trigger設定が有効になる条件

## Test Environment

- 雛形アプリ: `dev/tutorials/10_csv_continuity/ptp-synchronizecapture.py`
- 検証用ディレクトリ: `dev/tutorials/11_pixelformat/`

## Related Issues

- [bug-003](../bug-003-trigger-properties-not-found/): Triggerプロパティが見つからない（Frozen）
