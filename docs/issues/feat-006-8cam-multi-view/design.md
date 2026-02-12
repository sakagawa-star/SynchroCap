# feat-006 機能設計書: Multi Viewの8カメラ対応

## 1. 概要

Multi View（Tab 3）のプレビュースロットを4から8に拡張し、グリッドレイアウトを4列x2行に変更する。

## 2. 変更対象

| ファイル | 変更内容 |
|---------|---------|
| `src/synchroCap/ui_multi_view.py` | 定数追加、`_build_ui()` のスロット生成・グリッド配置変更 |

変更なし: `recording_controller.py`, `channel_registry.py`, `ui_channel_manager.py`, `_create_slot()`, その他全関数

## 3. 変更内容

### 3.1 定数の追加

`MultiViewWidget` クラスの直前（モジュールレベル）に定数を追加する。

```python
MAX_SLOTS = 8
GRID_COLUMNS = 4
```

### 3.2 `_build_ui()` の変更

#### 変更前（129〜132行目）

```python
        for index in range(4):
            slot = self._create_slot(index)
            self.slots.append(slot)
            grid.addWidget(slot["container"], index // 2, index % 2)
```

#### 変更後

```python
        for index in range(MAX_SLOTS):
            slot = self._create_slot(index)
            self.slots.append(slot)
            grid.addWidget(slot["container"], index // GRID_COLUMNS, index % GRID_COLUMNS)
```

### 3.3 変更箇所の詳細

| 項目 | 変更前 | 変更後 |
|------|--------|--------|
| スロット数 | `range(4)` | `range(MAX_SLOTS)` (= 8) |
| グリッド行 | `index // 2` | `index // GRID_COLUMNS` (= index // 4) |
| グリッド列 | `index % 2` | `index % GRID_COLUMNS` (= index % 4) |

### 3.4 レイアウト結果

```
         Col0     Col1     Col2     Col3
Row0  [ Cam1 ] [ Cam2 ] [ Cam3 ] [ Cam4 ]
Row1  [ Cam5 ] [ Cam6 ] [ Cam7 ] [ Cam8 ]
```

Full HD (1920px) での各プレビュー幅: 約 460px（余白考慮）。
現行の最小サイズ 320x240px は変更不要。

## 4. 変更不要の根拠

| 箇所 | 理由 |
|------|------|
| `_create_slot()` | index引数を受け取りスロットを生成。8でも動作に問題なし |
| `refresh_channels()` | `for slot in self.slots` で全スロットを走査。台数非依存 |
| `stop_all()` / `resume_selected()` | 同上 |
| `_on_start_recording()` | `for slot in self.slots` で有効スロットを収集。台数非依存 |
| `_update_ptp_all()` | 同上 |
| `recording_controller.py` | `prepare(slots=...)` で可変長リストを受け取る設計 |

## 5. テスト確認項目

1. アプリ起動時に8スロットが4列x2行で表示されること
2. 8台のカメラを選択してLive Viewが表示されること
3. 8台でPTP同期録画（MP4/Raw）が正常に動作すること
4. 4台以下の構成で従来通り動作すること（未選択スロットは「Disconnected」表示）
