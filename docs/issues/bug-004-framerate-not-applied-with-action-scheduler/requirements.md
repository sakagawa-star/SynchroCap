# bug-004: 要件定義書

## 概要

ACTION_SCHEDULER_INTERVALを独立して設定できるGUIを追加する。

## 背景

現状ではACTION_SCHEDULER_INTERVALはフレームレートから自動計算されるが、
フレームレートの値が時間的に余裕がない場合にフレームが正しく取得できない問題がある。

## 要求仕様

### 機能要求

| ID | 要求 |
|----|------|
| REQ-01 | Camera SettingタブにTrigger Interval設定UIを追加する |
| REQ-02 | fps単位で入力し、内部でµsに変換する |
| REQ-03 | 設定値は録画時にACTION_SCHEDULER_INTERVALに反映される |
| REQ-04 | 入力は常に手動で行う（自動計算なし） |

### UI仕様

| 項目 | 値 |
|------|-----|
| 配置場所 | Camera Settingタブ「Frequent Settings」グループ内 |
| 配置位置 | FrameRate (fps) の直後 |
| ラベル名 | Trigger Interval (fps) |
| 入力形式 | fps値（例: 50） |
| UI形式 | QPushButton + ダイアログ（FrameRateと同様） |

### バリデーション

- 現時点ではバリデーション不要
- 将来的に実装予定

### 変換式

```
interval_us = round(1_000_000 / trigger_interval_fps)
```

| 入力(fps) | 変換後(µs) |
|-----------|------------|
| 30 | 33,333 |
| 50 | 20,000 |
| 60 | 16,667 |

## 対象ファイル

- `src/synchroCap/ui_camera_settings.py` - UI追加
- `src/synchroCap/recording_controller.py` - 設定値の反映
