# Investigation: bug-001

## Root Cause: CONFIRMED

**`QTimer.singleShot()` が非Qtスレッドから呼び出されている**

## 調査ログ

### コードトレース

1. `RecordingController.start()` で録画開始
2. `_monitor_completion()` がデーモンスレッド（Python `threading.Thread`）で起動
3. 録画ワーカースレッドが終了を待機
4. 全スレッド終了後、`_set_state(RecordingState.IDLE, ...)` を呼び出し
5. `_set_state()` がコールバック `_on_state_changed()` を実行
6. `_on_recording_state_changed()` が `QTimer.singleShot(0, lambda: ...)` を呼び出し

### 問題箇所

**ui_multi_view.py:517-520**
```python
def _on_recording_state_changed(self, state: RecordingState, message: str) -> None:
    """RecordingControllerからの状態変更コールバック（別スレッドから呼ばれる可能性あり）"""
    # QTimerを使ってメインスレッドで実行
    QTimer.singleShot(0, lambda: self._update_recording_ui(state, message))
```

### なぜ動かないのか

- `QTimer` はイベントループを持つスレッドでのみ動作する
- `_monitor_completion` は Python の `threading.Thread` で実行される（Qtイベントループなし）
- 非Qtスレッドから `QTimer.singleShot()` を呼んでも、タイマーイベントは発火しない
- 結果: `_update_recording_ui()` が呼ばれず、UIが更新されない

### なぜ録画開始時は動くのか

- `prepare()` と `start()` はメインスレッド（Qtイベントループあり）から呼ばれる
- この時の `_set_state()` 呼び出しはメインスレッドで実行される
- `QTimer.singleShot()` が正常に動作する

## 解決策

### 方法1: Qt Signal を使用（推奨）

`MultiViewWidget` に Signal を追加し、スレッド間通信を Qt に任せる。

```python
class MultiViewWidget(QWidget):
    tabs_lock_changed = Signal(bool)
    _recording_state_changed = Signal(object, str)  # 追加

    def __init__(self, ...):
        ...
        self._recording_state_changed.connect(self._update_recording_ui)
        self._recording_controller = RecordingController(
            on_state_changed=self._emit_recording_state_changed
        )

    def _emit_recording_state_changed(self, state: RecordingState, message: str) -> None:
        self._recording_state_changed.emit(state, message)
```

**メリット**: Qt の公式なスレッド間通信メカニズム

### 方法2: QMetaObject.invokeMethod を使用

```python
from PySide6.QtCore import QMetaObject, Qt, Q_ARG

def _on_recording_state_changed(self, state: RecordingState, message: str) -> None:
    QMetaObject.invokeMethod(
        self,
        "_update_recording_ui_slot",
        Qt.QueuedConnection,
        Q_ARG(object, state),
        Q_ARG(str, message),
    )
```

**メリット**: 既存構造を大きく変えずに対応可能

## 検証方法

1. 短いDuration（10秒）で録画開始
2. Duration経過後、以下を確認:
   - コンソールに `[RecordingController] State: idle - Recording complete` が出力される
   - GUIの Startボタンが有効になる
   - ステータスが "Ready" に戻る

## 影響範囲

- `src/synchroCap/ui_multi_view.py` の修正が必要
- `recording_controller.py` は変更不要

## 結論

**原因解明完了。修正は方法1（Qt Signal）を推奨。**
