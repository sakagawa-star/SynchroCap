# bug-004 実装エラー修正: appdata_directory スコープ問題

## 要件定義

### 概要

bug-004の実装（Trigger Interval UI追加）において、`mainwindow.py`で`appdata_directory`変数のスコープ問題が発生し、アプリが起動できなくなった。

### エラー内容

```
File "/home/sakagawa/git/SynchroCap/src/synchroCap/mainwindow.py", line 153, in createUI
    appdata_directory=appdata_directory,
NameError: name 'appdata_directory' is not defined
```

### 原因

- `appdata_directory`は`__init__`メソッド内のローカル変数
- `createUI()`メソッドからはアクセス不可
- Pythonのスコープルールに違反

### 要求仕様

| ID | 要求 |
|----|------|
| REQ-01 | `appdata_directory`を`createUI()`メソッドからアクセス可能にする |
| REQ-02 | 既存の動作に影響を与えない |

---

## 機能設計

### 変更対象ファイル

| ファイル | 変更種別 | 内容 |
|---------|---------|------|
| `src/synchroCap/mainwindow.py` | 修正 | appdata_directoryをインスタンス変数化 |

### 変更詳細

#### 変更前（__init__内）

```python
appdata_directory = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
QDir(appdata_directory).mkpath(".")

self.device_file = appdata_directory + "/device.json"
self.channels_file = appdata_directory + "/channels.json"
```

#### 変更後（__init__内）

```python
self.appdata_directory = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
QDir(self.appdata_directory).mkpath(".")

self.device_file = self.appdata_directory + "/device.json"
self.channels_file = self.appdata_directory + "/channels.json"
```

#### 変更前（createUI内）

```python
self.multi_view_widget = MultiViewWidget(
    registry=self.channel_registry,
    resolver=self.device_resolver,
    appdata_directory=appdata_directory,
    parent=self,
)
```

#### 変更後（createUI内）

```python
self.multi_view_widget = MultiViewWidget(
    registry=self.channel_registry,
    resolver=self.device_resolver,
    appdata_directory=self.appdata_directory,
    parent=self,
)
```

### 影響範囲

- `mainwindow.py`内で`appdata_directory`を参照している箇所すべてを`self.appdata_directory`に変更
- 他のファイルへの影響なし
