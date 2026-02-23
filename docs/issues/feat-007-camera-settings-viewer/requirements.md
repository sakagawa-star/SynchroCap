# 要件定義書: Camera Settings Viewer (Tab4)

対象: feat-007
作成日: 2026-02-23
基準文書: `docs/issues/feat-007-camera-settings-viewer/README.md`

---

## 1. 目的と概要

### 1.1 目的

チャンネル紐付け済みの全カメラの設定値を一覧表示し、全カメラで設定が統一されているかを一目で確認できるようにする。

### 1.2 背景

同期録画では全カメラの Resolution・PixelFormat・Framerate 等の設定が揃っていることが前提となる。
現状は個別カメラごとに設定を確認する必要があり、一覧で比較する手段がない。

### 1.3 機能概要

- 新規タブ（Tab4）として設定一覧ビューを追加する
- 全カメラの7項目の設定値をテーブル形式で表示する
- 全カメラの設定一致チェック結果を全体OK/NGで表示する
- 読み取り専用（設定変更機能は持たない）

---

## 2. 表示項目

### 2.1 カメラ設定項目

以下の7項目をカメラから直接取得して表示する。

| # | 表示名 | IC4 PropId | 取得メソッド | 値の例 |
|---|--------|-----------|-------------|--------|
| 1 | Resolution | `WIDTH` + `HEIGHT` | `get_value_int` | `1920x1080` |
| 2 | PixelFormat | `PIXEL_FORMAT` | `get_value_str` | `BayerGR8` |
| 3 | Framerate (fps) | `ACQUISITION_FRAME_RATE` | `get_value_float` | `30.0` |
| 4 | Trigger Interval (fps) | `ACTION_SCHEDULER_INTERVAL` | `get_value_int` | `30.0` ※ |
| 5 | Auto White Balance | `BALANCE_WHITE_AUTO` | `get_value_str` | `Off` / `Continuous` |
| 6 | Auto Exposure | `EXPOSURE_AUTO` | `get_value_str` | `Off` / `Continuous` |
| 7 | Auto Gain | `GAIN_AUTO` | `get_value_str` | `Off` / `Continuous` |

※ Trigger Interval はカメラから `ACTION_SCHEDULER_INTERVAL`（μs単位）を取得し、fps に換算して表示する。
  計算式: `fps = 1_000_000 / interval_us`

### 2.2 カメラ識別情報

各カメラは以下の形式で識別表示する。

```
Ch-{channel_id} ({serial})
```

例: `Ch-01 (05520125)`

---

## 3. GUI要件

### 3.1 タブ配置

新規タブ（Tab4）を既存タブの末尾に追加する。

| Index | タブ名 | ウィジェット | 備考 |
|-------|--------|------------|------|
| 0 | Channel Manager | `ChannelManagerWidget` | 既存 |
| 1 | Camera Settings | `CameraSettingsWidget` | 既存 |
| 2 | Multi View | `MultiViewWidget` | 既存 |
| 3 | **Camera Settings Viewer** | **新規作成** | **今回追加** |

> **注**: 既存 Tab2 が "Camera Settings" という名称を使用している。
> Tab4 は "Camera Settings Viewer" とし、混同を避ける。

### 3.2 テーブルレイアウト

行 = カメラ、列 = 設定項目。最下行に一致チェック結果行（Match行）を配置する。

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  Camera Settings Viewer                                                             │
│                                                                                     │
│  ┌───────────────────────────────────────────────────────────────────────────────┐  │
│  │ Camera              │ Resolution │ PixelFmt │ FPS  │ Trig │ AWB │ AE  │ AG  │  │
│  ├─────────────────────┼────────────┼──────────┼──────┼──────┼─────┼─────┼─────┤  │
│  │ Ch-01 (05520125)    │ 1920x1080  │ BayerGR8 │ 30.0 │ 30.0 │ Off │ Off │ Off │  │
│  │ Ch-02 (05520126)    │ 1920x1080  │ BayerGR8 │ 30.0 │ 30.0 │ Off │ Off │ Off │  │
│  │ Ch-03 (05520128)    │ 1920x1080  │ BayerGR8 │ 25.0 │ 30.0 │ Off │ Off │ Off │  │
│  ├─────────────────────┼────────────┼──────────┼──────┼──────┼─────┼─────┼─────┤  │
│  │ Match               │     OK     │    OK    │  NG  │  OK  │ OK  │ OK  │ OK  │  │
│  └───────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                     │
│  ┌───────────────────────────────────────┐                                          │
│  │  All Settings Match:  NG              │                                          │
│  └───────────────────────────────────────┘                                          │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 不一致項目の視覚的強調

設定が不一致（NG）の項目は、該当セルの背景色を赤系に変更して視覚的に強調する。

| 状態 | 表示 | セル背景色 |
|------|------|-----------|
| 一致（OK） | `OK` | デフォルト（変更なし） |
| 不一致（NG） | `NG` | 赤系（例: `#FFCCCC`） |

Match行のOK/NGテキストおよび、不一致の値を持つカメラ行の該当セルの両方を着色する。

### 3.4 全体一致サマリー

テーブル下部に全体の一致結果をラベルで表示する。

- 全項目一致の場合: `All Settings Match: OK`
- 1項目でも不一致がある場合: `All Settings Match: NG`

---

## 4. データ取得要件

### 4.1 取得タイミング

- Tab4 を選択（表示）したタイミングで、全カメラの設定値を自動取得する
- 手動リフレッシュボタンは設けない

### 4.2 取得対象カメラ

以下の条件を全て満たすカメラが対象。

1. `ChannelRegistry` にチャンネル紐付けが登録されている
2. `device_resolver` でデバイスが解決可能である（物理的に接続されている）
3. Grabber でデバイスを open し、`device_property_map` にアクセスできる

### 4.3 取得方法

各カメラごとに一時的に Grabber を open し、`device_property_map` 経由で設定値を取得する。
取得完了後は Grabber を close する。

> **注**: 既存の Tab2 (`CameraSettingsWidget`) や Tab3 (`MultiViewWidget`) と
> Grabber の排他使用を考慮する必要がある。
> Tab 切り替え時に他タブの Grabber を停止する既存パターン（`mainwindow.py:178-198`）を踏襲する。

### 4.4 プロパティ取得パターン

既存コードで確立されている安全なアクセスパターンを使用する。

```python
# PropId の安全な取得
prop_id = getattr(ic4.PropId, "PROPERTY_NAME", None)

# 値の取得（try-except で保護）
try:
    value = prop_map.get_value_str(prop_id)
except ic4.IC4Exception:
    value = "N/A"
```

取得失敗時は `"N/A"` を表示する。`"N/A"` は不一致として扱い、他カメラの値と異なる場合は NG となる。

---

## 5. 一致チェック要件

### 5.1 チェック方法

各設定項目について、全カメラの値を比較する。

- 全カメラで同一値の場合: **OK**
- 1台でも異なる値がある場合: **NG**
- `"N/A"` が混在する場合: **NG**（N/Aは不一致として扱う）
- カメラが1台のみの場合: 全項目 **OK**
- カメラが0台の場合: チェック不実施

### 5.2 比較ルール

| 項目 | 比較方法 |
|------|---------|
| Resolution | WIDTH と HEIGHT の組み合わせを文字列化して比較 |
| PixelFormat | 文字列完全一致 |
| Framerate | 数値比較（小数点以下の丸め誤差を考慮し、小数第1位で丸めて比較） |
| Trigger Interval | 同上（fps換算後に比較） |
| Auto White Balance | 文字列完全一致 |
| Auto Exposure | 文字列完全一致 |
| Auto Gain | 文字列完全一致 |

---

## 6. 状態遷移

### 6.1 タブの有効/無効

| アプリケーション状態 | Tab4 の状態 |
|--------------------|-----------|
| 通常（カメラ未接続含む） | **有効**（選択可能） |
| 録画中 | **無効**（選択不可） |

録画中のタブ無効化は、既存の `set_tabs_locked()` 機構を拡張して対応する。

### 6.2 カメラ未接続時の表示

チャンネル紐付け済みカメラが0台の場合:

- テーブルは空（ヘッダ行のみ）
- メッセージを表示: `"No cameras connected. Please assign channels in Channel Manager."`

---

## 7. 既存機能との関係

### 7.1 Tab2 (Camera Settings) との違い

| 観点 | Tab2 (Camera Settings) | Tab4 (Camera Settings Viewer) |
|------|----------------------|------------------------------|
| 目的 | 個別カメラの設定変更 | 全カメラの設定一覧・比較 |
| 操作 | 読み書き可能 | 読み取り専用 |
| 対象 | 選択した1台 | 紐付け済み全カメラ |
| 一致チェック | なし | あり |

### 7.2 タブ切り替え時の排他制御

既存パターンに従い、Tab4 表示時に他タブの Grabber リソースを解放する。

| 遷移元 → 遷移先 | 必要な処理 |
|-----------------|----------|
| Tab2 → Tab4 | Tab2 のプレビュー停止 |
| Tab3 → Tab4 | Tab3 の全スロット停止 |
| Tab4 → Tab2 | Tab4 の Grabber 解放（取得完了後は自動解放のため不要の可能性あり） |
| Tab4 → Tab3 | 同上 |

---

## 8. 非要件

以下は本機能のスコープ外とする。

- カメラ設定の変更・書き込み
- 手動リフレッシュボタン
- 設定値の自動定期更新（ポーリング）
- 設定値のファイルエクスポート
- 設定不一致時の自動修正
- 個別プロパティの詳細表示（ツールチップ等）

---

## 9. 制約・前提条件

### 9.1 前提条件

- IC4 SDK (`imagingcontrol4`) がインストール済みであること
- カメラが PTP 対応の The Imaging Source 製であること
- チャンネル紐付けが `ChannelRegistry` で管理されていること

### 9.2 技術的制約

- Grabber は同時に1つのプロセス/スレッドからのみ open 可能
  → Tab4 表示時に他タブの Grabber を停止する必要がある
- `ACTION_SCHEDULER_INTERVAL` はカメラがストリーミング状態でなくても取得可能か要確認

---

## 10. 未決事項

| # | 項目 | 内容 | ステータス |
|---|------|------|----------|
| 1 | タブ名称 | "Camera Settings Viewer" に確定（2026-02-23） | **確定** |
| 2 | Trigger Interval 取得可否 | 取得可能な前提で実装。取得失敗時は `"N/A"` を表示し一致チェック対象外とする（2026-02-23） | **確定** |
