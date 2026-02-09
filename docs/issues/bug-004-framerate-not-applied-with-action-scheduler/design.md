# bug-004: 機能設計書

## 1. 変更概要

### 1.1 変更対象ファイル

| ファイル | 変更種別 | 内容 |
|---------|---------|------|
| `src/synchroCap/ui_camera_settings.py` | 修正 | Trigger Interval UI追加 |
| `src/synchroCap/recording_controller.py` | 修正 | trigger_interval_fpsパラメータ対応 |
| `src/synchroCap/ui_multi_view.py` | 修正 | trigger_interval_fpsの受け渡し |

## 2. UI設計

### 2.1 Camera Settingタブへの追加

```
Frequent Settings
├── Resolution          [Change...]
├── PixelFormat         [Change...]
├── FrameRate (fps)     [30.00]
├── Trigger Interval (fps) [50.00]  ← 新規追加
├── ─────────────────────
├── Auto White Balance
...
```

### 2.2 新規UI要素

```python
# ui_camera_settings.py

# インスタンス変数追加
self._current_trigger_interval_fps: Optional[float] = None

# UI要素追加（FrameRateの直後）
self.trigger_interval_button = QPushButton("50.00", self.settings_group)
self.trigger_interval_button.clicked.connect(self._on_change_trigger_interval_clicked)
settings_layout.addRow("Trigger Interval (fps)", self.trigger_interval_button)
```

### 2.3 ダイアログ実装

`_prompt_frame_rate()` と同様の実装:

```python
def _prompt_trigger_interval(self, current_value: float) -> Optional[float]:
    dlg = QDialog(self)
    dlg.setWindowTitle("Set Trigger Interval")
    layout = QVBoxLayout(dlg)

    layout.addWidget(QLabel("Trigger Interval (fps)", dlg))
    line_edit = QLineEdit(dlg)
    validator = QDoubleValidator(0.0, 1000.0, 2, line_edit)
    validator.setNotation(QDoubleValidator.StandardNotation)
    line_edit.setValidator(validator)
    line_edit.setText(f"{current_value:.2f}")
    layout.addWidget(line_edit)

    # 変換後のµs表示
    interval_label = QLabel(f"= {round(1_000_000 / current_value)} µs", dlg)
    layout.addWidget(interval_label)

    def update_interval(text: str) -> None:
        try:
            fps = float(text)
            if fps > 0:
                interval_label.setText(f"= {round(1_000_000 / fps)} µs")
            else:
                interval_label.setText("= N/A")
        except ValueError:
            interval_label.setText("= N/A")

    line_edit.textChanged.connect(update_interval)

    buttons = QDialogButtonBox(...)
    # ... 以下_prompt_frame_rateと同様
```

## 3. データフロー設計

### 3.1 設定値の保存

```
Camera Setting UI
    ↓ _on_change_trigger_interval_clicked()
    ↓ _persist_update({"trigger_interval_fps": value})
    ↓
永続化（JSON）
```

### 3.2 録画時のデータフロー

```
Multi View タブ
    ↓ _start_recording()
    ↓ 各スロットからtrigger_interval_fpsを取得
    ↓
recording_controller.prepare(
    slots=[...],  # 各slotにtrigger_interval_fpsを含む
    start_delay_s=...,
    duration_s=...,
)
    ↓
_configure_action_scheduler()
    ↓ interval_us = round(1_000_000 / slot.trigger_interval_fps)
    ↓
prop_map.set_value(ACTION_SCHEDULER_INTERVAL, interval_us)
```

## 4. 詳細設計

### 4.1 ui_camera_settings.py の変更

#### 4.1.1 インスタンス変数追加

```python
def __init__(self, ...):
    # ... 既存コード ...
    self._current_trigger_interval_fps: Optional[float] = 50.0  # デフォルト値
```

#### 4.1.2 UI作成（__init__内）

```python
# FrameRateの直後に追加
self.trigger_interval_button = QPushButton("50.00", self.settings_group)
self.trigger_interval_button.clicked.connect(self._on_change_trigger_interval_clicked)
settings_layout.addRow("Trigger Interval (fps)", self.trigger_interval_button)
```

#### 4.1.3 メソッド追加

```python
def _on_change_trigger_interval_clicked(self) -> None:
    if self._updating_controls or not self._controls_enabled:
        return
    if self._current_trigger_interval_fps is None:
        return

    new_value = self._prompt_trigger_interval(self._current_trigger_interval_fps)
    if new_value is None:
        return

    self._current_trigger_interval_fps = new_value
    self._refresh_frequent_settings_ui()
    self._persist_update({"trigger_interval_fps": float(new_value)})

def _prompt_trigger_interval(self, current_value: float) -> Optional[float]:
    # 上記2.3参照

def get_trigger_interval_fps(self) -> Optional[float]:
    """録画時に呼び出される"""
    return self._current_trigger_interval_fps
```

#### 4.1.4 UI更新（_refresh_frequent_settings_ui）

```python
def _refresh_frequent_settings_ui(self) -> None:
    # ... 既存コード ...

    # Trigger Interval表示更新
    if self._current_trigger_interval_fps is not None:
        self.trigger_interval_button.setText(f"{self._current_trigger_interval_fps:.2f}")
        self.trigger_interval_button.setEnabled(self._controls_enabled)
    else:
        self.trigger_interval_button.setText("50.00")
        self.trigger_interval_button.setEnabled(self._controls_enabled)
```

### 4.2 recording_controller.py の変更

#### 4.2.1 RecordingSlot拡張

```python
@dataclass
class RecordingSlot:
    # ... 既存フィールド ...
    trigger_interval_fps: float = 50.0  # 新規追加
```

#### 4.2.2 _configure_action_scheduler変更

```python
def _configure_action_scheduler(self, slot: RecordingSlot) -> bool:
    # ... 既存コード ...

    # 変更: slot.fpsではなくslot.trigger_interval_fpsを使用
    interval_us = round(1_000_000 / slot.trigger_interval_fps)

    # ... 以下同様 ...
```

### 4.3 ui_multi_view.py の変更

#### 4.3.1 スロット情報にtrigger_interval_fpsを追加

```python
def _start_recording(self) -> None:
    # ... 既存コード ...

    active_slots = []
    for slot in self.slots:
        grabber = slot.get("grabber")
        # ...
        # trigger_interval_fpsを取得（Camera Settingから）
        trigger_interval_fps = self._get_trigger_interval_for_slot(slot)
        slot_info = {
            "grabber": grabber,
            "trigger_interval_fps": trigger_interval_fps,
        }
        active_slots.append(slot_info)
```

## 5. デフォルト値

| 項目 | 値 | 備考 |
|------|-----|------|
| trigger_interval_fps | 50.0 | 20,000µs = 20ms |

## 6. 永続化

既存の永続化機構を使用:

```python
self._persist_update({"trigger_interval_fps": float(value)})
```

読み込み時:

```python
def _apply_persisted_settings(self, prop_map) -> None:
    # ... 既存コード ...
    trigger_interval = settings.get("trigger_interval_fps")
    if trigger_interval is not None:
        self._current_trigger_interval_fps = float(trigger_interval)
```

## 7. 確認事項

### 7.1 設計判断が必要な点

1. **複数カメラでの扱い**:
   - A) 各カメラ個別にTrigger Intervalを設定
   - B) 全カメラ共通のTrigger Intervalを使用

   現在の設計: A) 各カメラ個別に設定

2. **デフォルト値**: 50.0 fps でよいか？
