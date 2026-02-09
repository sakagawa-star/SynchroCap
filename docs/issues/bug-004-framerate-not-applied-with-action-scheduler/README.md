# bug-004: フレームレート設定が反映されない場合がある

## Status: Closed (2026-02-09)

## Summary

カメラのフレームレート設定が反映されない場合がある。
ACTION_SCHEDULER_INTERVALの値に対してフレームレートの設定値が時間的に余裕がない場合に発生。

## Reproduction Steps

1. 以下の設定で撮影:
   - フレームレート: 30fps
   - ACTION_SCHEDULER_INTERVAL: 32ms
   - ピクセルフォーマット: BayerGR8
   - 露光時間: 16335µs
   - 解像度: 1920x1080
2. 撮影されたフレームのタイムスタンプを確認

## Expected Behavior

- フレーム間隔: 約33ms (30fps)

## Actual Behavior

- フレーム間隔: 約64ms (実質15fps)
- フレームレート設定が反映されていない

## Root Cause

ACTION_SCHEDULER_INTERVALの値（32ms）に対して、フレームレートの設定値（30fps = 33.3ms）が時間的に余裕がない。

## Solution

フレームレートの値を上げる（例: 30fps → 50fps）

## Affected Files

- 設定ファイル/パラメータ

## Related

- bug-003: Triggerプロパティが見つからない（Closed）
- inv-001: PixelFormat/Trigger設定の検証（Closed）
