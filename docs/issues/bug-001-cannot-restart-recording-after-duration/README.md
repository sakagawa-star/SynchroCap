# bug-001: Duration経過後に録画再開できない

## Status: Closed (2026-02-05)

## Summary

録画開始からDurationで設定した時間を経過した後、GUIでは録画開始後のロック状態が解除されない。
Duration経過後の録画終了の状態管理とGUIの連携が取れていないことが原因と思われる。

## Reproduction Steps

1. Multi Viewタブで1台以上のカメラを選択
2. Durationを短い値（例: 10秒）に設定
3. Startボタンをクリックして録画開始
4. Duration経過後、録画が終了する
5. GUIのロック状態が解除されず、Startボタンが無効のまま

## Expected Behavior

Duration経過後、録画が正常終了し：
- Startボタンが再度有効になる
- ステータスが "Ready" に戻る
- タブのロックが解除される
- プレビューが再開される

## Actual Behavior

Duration経過後：
- Startボタンが無効のまま
- ステータスが更新されない
- タブのロックが解除されない
- 再録画ができない

## Affected Files

- `src/synchroCap/recording_controller.py`
- `src/synchroCap/ui_multi_view.py`

## Root Cause Analysis

**原因特定済み**

`_on_recording_state_changed()` で使用している `QTimer.singleShot()` が、
非Qtスレッド（Python threading.Thread）から呼び出されているため、タイマーイベントが発火しない。

詳細は [investigation.md](investigation.md) を参照。

## Related

- 機能設計書: `docs/feature_design.md`
