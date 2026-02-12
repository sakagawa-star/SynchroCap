# feat-006 要求仕様書: Multi Viewの8カメラ対応

## 1. 概要

本番アプリのMulti View（Tab 3）を4カメラから最大8カメラに拡張する。Live ViewとPTP同期録画の両方を8カメラに対応させる。

## 2. 対象

- `src/synchroCap/ui_multi_view.py` — Multi View UI
- `src/synchroCap/recording_controller.py` — 録画制御（必要に応じて）

### スコープ外

- Channel Manager（Tab 1）— 既に制限なし（feat-005で確認済み）
- Camera Settings（Tab 2）— 別案件として扱う

## 3. 機能要求

### FR-01: プレビュースロット数の拡張

- プレビュースロットを4から8に拡張する
- 常に8スロットを表示する（カメラ未選択のスロットも表示）

### FR-02: グリッドレイアウトの変更

- 現行: 2列 x 2行（4スロット）
- 変更後: 4列 x 2行（8スロット）

### FR-03: Live View（8カメラ）

- 最大8台のカメラのLive Viewを同時表示できること
- 各スロットにチャンネル選択コンボボックスを配置（現行通り）
- 各スロットにPTPステータスを表示（現行通り）

### FR-04: PTP同期録画（8カメラ）

- 最大8台のカメラでPTP同期録画ができること
- 録画対象はチャンネルが選択され、カメラが接続されているスロットのみ
- MP4形式・Raw形式の両方に対応（現行通り）

### FR-05: カメラ台数の柔軟性

- 8台未満のカメラ構成でもLive View・録画が正常に動作すること
- 1台〜8台の任意の台数で使用可能であること
- カメラが選択されていないスロットは「Disconnected」表示（現行通り）

## 4. 非機能要求

### NFR-01: 既存動作の維持

- 4台以下のカメラ構成での動作が従来と変わらないこと
- 録画制御ロジック（RecordingController）の動作に影響を与えないこと

### NFR-02: UIの視認性

- 8スロット表示時でも各プレビューが視認可能なサイズであること

## 5. 現行コードの分析

### 変更が必要な箇所

| 箇所 | 現行 | 変更後 |
|------|------|--------|
| `ui_multi_view.py:129` | `for index in range(4):` | `for index in range(8):` |
| `ui_multi_view.py:132` | `index // 2, index % 2`（2列） | `index // 4, index % 4`（4列） |

### 変更不要な箇所

| 箇所 | 理由 |
|------|------|
| `recording_controller.py` | スロット数に依存しない設計（可変長リストで受け取る） |
| `channel_registry.py` | チャンネル数1〜99で制限なし |
| `_create_slot()` | スロット生成ロジックはindex依存なし |
| `_on_start_recording()` | `for slot in self.slots` で全スロットを走査、台数非依存 |
