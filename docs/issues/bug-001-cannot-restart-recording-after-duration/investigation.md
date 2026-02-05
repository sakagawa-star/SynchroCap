# Investigation: bug-001

## Investigation Log

（調査メモをここに記録）

## Hypotheses

1. RecordingControllerの状態遷移がGUIに正しく通知されていない
2. _monitor_completion スレッドからのコールバックがメインスレッドに届いていない
3. QTimer.singleShotによるスレッド間通信が失敗している

## Code Analysis

### 関連コード: recording_controller.py

```python
def _monitor_completion(self) -> None:
    """録画完了を監視するスレッド"""
    # 全スレッドの終了を待機
    for serial, thread in self._threads.items():
        thread.join()

    # クリーンアップ
    self._set_state(RecordingState.STOPPING, "Finalizing...")
    self._cleanup()
    self._set_state(RecordingState.IDLE, "Recording complete")
```

### 関連コード: ui_multi_view.py

```python
def _on_recording_state_changed(self, state: RecordingState, message: str) -> None:
    """RecordingControllerからの状態変更コールバック（別スレッドから呼ばれる可能性あり）"""
    # QTimerを使ってメインスレッドで実行
    QTimer.singleShot(0, lambda: self._update_recording_ui(state, message))
```

## Test Cases

（テストケースをここに記録）

## Resolution

（解決策をここに記録）
