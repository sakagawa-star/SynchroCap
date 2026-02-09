# bug-004 実装エラー修正: カメラ切り替え時のTrigger Intervalリセット問題

## 要件定義

### 概要

Camera Settingタブでカメラを切り替えた際、`_current_trigger_interval_fps`が前のカメラの値のままになり、UIに誤った値が表示される問題を修正する。

### 問題の詳細

**発生シナリオ**:
1. カメラ05520125を選択 → `trigger_interval_fps=30.0`が読み込まれる
2. カメラ05520126に切り替え → recordに`trigger_interval_fps`がない
3. `_current_trigger_interval_fps`は30.0のまま（リセットされない）
4. UIには30.0が表示される（実際は未設定）
5. ユーザーは設定済みと思い込み、変更しない
6. 録画時にデフォルト50.0が使用される

### 原因

`_apply_persisted_settings()`で、recordに`trigger_interval_fps`が存在しない場合に`_current_trigger_interval_fps`をデフォルト値にリセットしていない。

### 要求仕様

| ID | 要求 |
|----|------|
| REQ-01 | カメラ切り替え時、recordに`trigger_interval_fps`がない場合はデフォルト値（50.0）にリセットする |
| REQ-02 | 既存のtrigger_interval_fps読み込み処理に影響を与えない |

---

## 機能設計

### 変更対象ファイル

| ファイル | 変更種別 | 内容 |
|---------|---------|------|
| `src/synchroCap/ui_camera_settings.py` | 修正 | trigger_interval_fpsのリセット処理追加 |

### 変更詳細

#### 変更箇所: `_apply_persisted_settings()` (931-933行目付近)

#### 変更前

```python
trigger_interval_fps = record.get("trigger_interval_fps")
if trigger_interval_fps is not None:
    self._current_trigger_interval_fps = float(trigger_interval_fps)
```

#### 変更後

```python
trigger_interval_fps = record.get("trigger_interval_fps")
if trigger_interval_fps is not None:
    self._current_trigger_interval_fps = float(trigger_interval_fps)
else:
    self._current_trigger_interval_fps = 50.0  # デフォルト値にリセット
```

### 動作確認

1. カメラAでTrigger Interval=30を設定・保存
2. カメラBに切り替え（未設定のカメラ）
3. UIに50.0（デフォルト値）が表示されることを確認
4. カメラAに戻る
5. UIに30.0が表示されることを確認
