# 機能設計書: Camera Settings Viewer (Tab4)

対象: feat-007
基準文書: `docs/issues/feat-007-camera-settings-viewer/requirements.md`
参照実装: `ui_camera_settings.py` (プロパティ取得パターン), `mainwindow.py` (タブ切り替え)

---

## 1. 機能概要

### 1.1 機能名

Camera Settings Viewer（カメラ設定一覧ビューワー）

### 1.2 機能説明

チャンネル紐付け済みの全カメラの設定値を QTableWidget で一覧表示し、
全カメラ間の設定一致チェック結果を OK/NG で表示する読み取り専用タブ。

---

## 2. システム構成

### 2.1 コンポーネント図

```
┌──────────────────────────────────────────────────────────────────┐
│                        MainWindow                                │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                      QTabWidget                            │  │
│  │  ┌──────────┬──────────┬──────────┬─────────────────────┐  │  │
│  │  │ Tab1     │ Tab2     │ Tab3     │ Tab4                │  │  │
│  │  │ Channel  │ Camera   │ Multi    │ CameraSettings      │  │  │
│  │  │ Manager  │ Settings │ View     │ ViewerWidget (新規) │  │  │
│  │  └──────────┴──────────┴──────────┴─────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 関連ファイル

| ファイル | 役割 | 変更種別 |
|---------|------|---------|
| `ui_camera_settings_viewer.py` | Tab4 ウィジェット（新規） | **新規作成** |
| `mainwindow.py` | タブ追加・切り替え制御 | 軽微変更 |

---

## 3. クラス設計

### 3.1 CameraSettingsViewerWidget クラス（新規）

```
CameraSettingsViewerWidget(QWidget)
├── 属性
│   ├── _registry: ChannelRegistry          # チャンネル登録情報
│   ├── _resolver: device_resolver           # デバイス解決モジュール
│   ├── _table: QTableWidget                 # 設定値テーブル
│   ├── _summary_label: QLabel               # 全体一致サマリー
│   ├── _message_label: QLabel               # 未接続時メッセージ
│   └── _camera_data: list[CameraSettings]   # 取得済み設定データ
│
├── 公開メソッド
│   ├── refresh()                            # 全カメラの設定を再取得・テーブル更新
│   └── stop_all_grabbers()                  # 不要（独自open/closeのため）
│
└── 内部メソッド
    ├── _create_ui()                         # UI構築
    ├── _fetch_all_camera_settings() -> list[CameraSettings]
    ├── _fetch_single_camera(entry) -> CameraSettings | None
    ├── _read_properties(prop_map) -> dict[str, str]
    ├── _update_table(data: list[CameraSettings])
    ├── _check_consistency(data) -> dict[str, bool]
    └── _apply_cell_highlight(row, col, is_match: bool)
```

### 3.2 CameraSettings データクラス（新規）

各カメラから取得した設定値を保持する。

```python
@dataclass
class CameraSettings:
    channel_id: int                 # チャンネルID
    serial: str                     # シリアル番号
    resolution: str                 # "1920x1080" or "N/A"
    pixel_format: str               # "BayerGR8" or "N/A"
    framerate: str                  # "30.0" or "N/A"
    trigger_interval: str           # "30.0" or "N/A"
    auto_white_balance: str         # "Off" / "Continuous" / "N/A"
    auto_exposure: str              # "Off" / "Continuous" / "N/A"
    auto_gain: str                  # "Off" / "Continuous" / "N/A"
```

---

## 4. シーケンス設計

### 4.1 タブ表示時の設定取得シーケンス

```
User        MainWindow          Tab4(Viewer)       Tab2/Tab3        Grabber       Camera
 │               │                   │                │               │              │
 │──[Tab4選択]──>│                   │                │               │              │
 │               │                   │                │               │              │
 │               │──stop_all() ─────────────────────>│               │              │
 │               │  or stop_preview_only()───────────>│               │              │
 │               │                   │                │               │              │
 │               │──refresh()──────>│                │               │              │
 │               │                   │                │               │              │
 │               │                   │──list_channels()              │              │
 │               │                   │<──[ChannelEntry list]         │              │
 │               │                   │                │               │              │
 │               │                   │  [各カメラについて繰り返し]     │              │
 │               │                   │──find_device_for_entry()      │              │
 │               │                   │<──DeviceInfo───│               │              │
 │               │                   │                │               │              │
 │               │                   │──────────────────Grabber()────>│              │
 │               │                   │──────────────────device_open()─>│             │
 │               │                   │──────────────────get props ────────────────>│
 │               │                   │<─────────────────values────────────────────│
 │               │                   │──────────────────device_close()>│             │
 │               │                   │  [繰り返し終了]  │               │              │
 │               │                   │                │               │              │
 │               │                   │──_check_consistency()          │              │
 │               │                   │──_update_table()               │              │
 │               │                   │                │               │              │
 │<──────────────────[表示完了]──────│                │               │              │
```

### 4.2 設定取得処理フロー

```
refresh()
  │
  ├── _fetch_all_camera_settings()
  │     │
  │     ├── registry.list_channels()
  │     │     └── [ChannelEntry, ChannelEntry, ...]
  │     │
  │     └── for entry in channels:
  │           ├── resolver.find_device_for_entry(entry)
  │           │     └── DeviceInfo or None
  │           │
  │           └── _fetch_single_camera(entry)
  │                 ├── grabber = ic4.Grabber()
  │                 ├── grabber.device_open(device_info)
  │                 ├── _read_properties(grabber.device_property_map)
  │                 │     ├── WIDTH + HEIGHT → resolution
  │                 │     ├── PIXEL_FORMAT → pixel_format
  │                 │     ├── ACQUISITION_FRAME_RATE → framerate
  │                 │     ├── ACTION_SCHEDULER_INTERVAL → trigger_interval
  │                 │     ├── BALANCE_WHITE_AUTO → auto_white_balance
  │                 │     ├── EXPOSURE_AUTO → auto_exposure
  │                 │     └── GAIN_AUTO → auto_gain
  │                 ├── grabber.device_close()
  │                 └── return CameraSettings
  │
  ├── _check_consistency(camera_data)
  │     └── {column_name: bool, ...}  # True=一致, False=不一致
  │
  └── _update_table(camera_data)
        ├── テーブルクリア・再構築
        ├── カメラ行の描画
        ├── Match 行の描画
        ├── _apply_cell_highlight() でNG列を着色
        └── _summary_label 更新
```

---

## 5. プロパティ取得設計

### 5.1 取得方法一覧

既存コード (`ui_camera_settings.py`) で確立されたパターンに従い、
`getattr(ic4.PropId, ...)` + `try-except` で安全に取得する。

| 項目 | PropId | 取得コード | 変換 |
|------|--------|-----------|------|
| Resolution | `WIDTH`, `HEIGHT` | `get_value_int()` × 2 | `f"{w}x{h}"` |
| PixelFormat | `PIXEL_FORMAT` | `get_value_str()` | そのまま |
| Framerate | `ACQUISITION_FRAME_RATE` | `get_value_float()` | `f"{v:.1f}"` |
| Trigger Interval | `ACTION_SCHEDULER_INTERVAL` | `get_value_int()` | `f"{1_000_000/v:.1f}"` (μs→fps) |
| Auto White Balance | `BALANCE_WHITE_AUTO` | `get_value_str()` | そのまま |
| Auto Exposure | `EXPOSURE_AUTO` | `get_value_str()` | そのまま |
| Auto Gain | `GAIN_AUTO` | `get_value_str()` | そのまま |

### 5.2 フォールバック

PropId が存在しない場合、文字列キーでもフォールバック取得を試みる。
（既存コードの `ui_camera_settings.py` のパターンに準拠）

```python
# PropId での取得を試みる
prop_id = getattr(ic4.PropId, "BALANCE_WHITE_AUTO", None)
if prop_id is not None:
    try:
        value = prop_map.get_value_str(prop_id)
    except ic4.IC4Exception:
        value = None

# フォールバック: 文字列キーで取得
if value is None:
    try:
        value = prop_map.get_value_str("BalanceWhiteAuto")
    except (ic4.IC4Exception, Exception):
        value = "N/A"
```

### 5.3 フォールバック文字列キー一覧

| PropId 名 | フォールバック文字列キー |
|-----------|----------------------|
| `BALANCE_WHITE_AUTO` | `"BalanceWhiteAuto"` |
| `EXPOSURE_AUTO` | `"ExposureAuto"` |
| `GAIN_AUTO` | `"GainAuto"` |
| `ACTION_SCHEDULER_INTERVAL` | `"ActionSchedulerInterval"` |

### 5.4 エラー時の表示

プロパティ取得に失敗した場合、該当セルに `"N/A"` を表示する。
`"N/A"` の項目は一致チェックの対象外とする。

---

## 6. 一致チェック設計

### 6.1 チェックロジック

```python
def _check_consistency(self, data: list[CameraSettings]) -> dict[str, bool]:
    """各列の一致チェック結果を返す。True=全一致, False=不一致"""
    if len(data) <= 1:
        # 0台 or 1台の場合は全てOK
        return {col: True for col in SETTING_COLUMNS}

    result = {}
    for col in SETTING_COLUMNS:
        values = [getattr(cam, col) for cam in data]
        # "N/A" も含めて全値が一致している場合のみ OK
        result[col] = len(set(values)) == 1
    return result
```

### 6.2 Framerate / Trigger Interval の比較

数値項目は文字列化済み（小数第1位で丸め）の状態で比較する。
これにより浮動小数点の微小誤差を吸収する。

```python
# 取得時に丸めて文字列化
framerate_str = f"{prop_map.get_value_float(prop_id):.1f}"
```

---

## 7. GUI設計

### 7.1 ウィジェットレイアウト

```
CameraSettingsViewerWidget (QWidget)
│
├── QVBoxLayout
│   ├── _table: QTableWidget           # 設定値テーブル
│   │   ├── ヘッダ行 (カラム名)
│   │   ├── カメラ行 × N台
│   │   └── Match 行 (最下行)
│   │
│   ├── _summary_label: QLabel          # "All Settings Match: OK/NG"
│   │
│   └── _message_label: QLabel          # "No cameras connected..." (未接続時)
```

### 7.2 テーブル定義

| 列 Index | ヘッダ名 | 対応フィールド | 幅 |
|----------|---------|---------------|-----|
| 0 | Camera | `channel_id` + `serial` | 可変（Stretch） |
| 1 | Resolution | `resolution` | 120px |
| 2 | PixelFormat | `pixel_format` | 100px |
| 3 | FPS | `framerate` | 70px |
| 4 | Trigger (fps) | `trigger_interval` | 100px |
| 5 | AWB | `auto_white_balance` | 90px |
| 6 | AE | `auto_exposure` | 90px |
| 7 | AG | `auto_gain` | 90px |

### 7.3 テーブルプロパティ

```python
table.setEditTriggers(QAbstractItemView.NoEditTriggers)   # 編集不可
table.setSelectionMode(QAbstractItemView.NoSelection)      # 選択不可
table.verticalHeader().setVisible(False)                   # 行番号非表示
table.horizontalHeader().setStretchLastSection(False)
table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)  # Camera列のみ伸縮
```

### 7.4 不一致セルの着色

```python
COLOR_NG = QColor("#FFCCCC")   # 赤系背景

def _apply_cell_highlight(self, row: int, col: int, is_match: bool) -> None:
    item = self._table.item(row, col)
    if item is None:
        return
    if not is_match:
        item.setBackground(COLOR_NG)
```

不一致時は以下を着色する:
- **Match 行**: NG の列のセル
- **カメラ行**: 不一致項目に該当する全カメラの該当列セル

### 7.5 未接続時の表示

カメラが 0 台の場合:
- `_table` はヘッダ行のみ（データ行 0）
- `_message_label` に `"No cameras connected. Please assign channels in Channel Manager."` を表示

カメラが 1 台以上の場合:
- `_message_label` は非表示（`hide()`）

---

## 8. MainWindow 統合設計

### 8.1 タブ追加

`mainwindow.py` の `createUI()` に Tab4 を追加する。

```python
# 既存タブの後に追加
self.camera_settings_viewer_widget = CameraSettingsViewerWidget(
    registry=self.channel_registry,
    resolver=self.device_resolver,
    parent=self,
)
self.tabs.addTab(self.camera_settings_viewer_widget, "Camera Settings Viewer")
```

### 8.2 タブ切り替え制御

`onTabChanged()` に Tab4 への遷移処理を追加する。

```
遷移元 → Tab4 の場合:
  1. Tab2 (CameraSettings) が active → stop_preview_only()
  2. Tab3 (MultiView) が active → stop_all()
  3. QTimer.singleShot(0, viewer_widget.refresh)
```

既存パターン準拠で、他タブの Grabber を解放してから Tab4 の refresh() を呼ぶ。

```python
elif self.tabs.widget(index) is self.camera_settings_viewer_widget:
    print("[tab-switch] to Tab4: stopping other tabs")
    try:
        self.multi_view_widget.stop_all()
    except Exception:
        pass
    try:
        self.camera_settings_widget.stop_preview_only()
    except Exception:
        pass
    QTimer.singleShot(0, self.camera_settings_viewer_widget.refresh)
```

### 8.3 Tab4 からの遷移時

Tab4 は refresh 完了後に Grabber を全て close 済みのため、
他タブへの遷移時に特別な停止処理は不要。

### 8.4 タブロック拡張

`set_tabs_locked()` に Tab4 の無効化を追加する。

```python
tab4_index = self.tabs.indexOf(self.camera_settings_viewer_widget)
if tab4_index != -1:
    self.tabs.setTabEnabled(tab4_index, not locked)
```

---

## 9. エラーハンドリング

### 9.1 エラー発生箇所と対応

| 箇所 | エラー | 対応 |
|------|--------|------|
| `find_device_for_entry()` | デバイス未検出 | 該当カメラをスキップ（テーブルに含めない） |
| `device_open()` | open 失敗 | 該当カメラをスキップ、コンソールに警告出力 |
| 個別プロパティ取得 | `IC4Exception` | 該当セルに `"N/A"` を表示（一致チェックではNGとして扱う） |
| `device_close()` | close 失敗 | 例外を握りつぶし、次のカメラに進む |

### 9.2 部分取得

8 台中 3 台しか接続されていない場合、接続されている 3 台分のみテーブルに表示する。
未接続カメラはテーブルに行を作らない。

---

## 10. 定数定義

```python
# テーブルカラム定義
COLUMNS = [
    "Camera",
    "Resolution",
    "PixelFormat",
    "FPS",
    "Trigger (fps)",
    "AWB",
    "AE",
    "AG",
]

# 一致チェック対象のフィールド名 (CameraSettings のフィールドに対応)
SETTING_COLUMNS = [
    "resolution",
    "pixel_format",
    "framerate",
    "trigger_interval",
    "auto_white_balance",
    "auto_exposure",
    "auto_gain",
]

# 不一致時の背景色
COLOR_NG = QColor("#FFCCCC")
```

---

## 11. 実装順序（推奨）

1. **Phase 1**: `CameraSettings` データクラスと定数定義
2. **Phase 2**: `CameraSettingsViewerWidget` の UI 構築（`_create_ui()`）
3. **Phase 3**: プロパティ取得ロジック（`_fetch_all_camera_settings()`, `_read_properties()`）
4. **Phase 4**: 一致チェックロジック（`_check_consistency()`）
5. **Phase 5**: テーブル更新・着色ロジック（`_update_table()`, `_apply_cell_highlight()`）
6. **Phase 6**: `mainwindow.py` 統合（タブ追加、切り替え制御、ロック拡張）
7. **Phase 7**: 結合テスト
