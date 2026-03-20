# 要求仕様書: Export Improvements - Naming Convention & Completion Notification

対象: feat-015
作成日: 2026-03-20
基準文書: `docs/REQUIREMENTS_STANDARD.md`

---

## 1. プロジェクト概要

### 1.1 何を作るか

キャリブレーション結果エクスポート（feat-012）の2点を改善する:
1. ファイル名・TOML内カメラ名を `cam{serial}` に統一する（ディレクトリ名 `cam{serial}` と一致させる）
2. エクスポート完了時にQMessageBoxで保存先パスをポップアップ通知する

### 1.2 なぜ作るか

- 現状のファイル名 `{serial}_intrinsics.toml` とTOML内 `cam_{serial}`（アンダースコア付き）がディレクトリ名 `cam{serial}`（アンダースコアなし）と不一致であり、命名規則が統一されていない
- エクスポート完了がステータスラベルの更新のみで、ユーザーが見落としやすい

### 1.3 誰が使うか

SynchroCapを使用してモーションキャプチャ用の同期録画を行うオペレーター。

### 1.4 どこで使うか

Ubuntu Linux、Python 3.10、micromamba SynchroCap環境。

---

## 2. 用語定義

| 用語 | 定義 |
|------|------|
| `cam{serial}` | カメラの命名規則。アンダースコアなし（例: `cam49710379`）。ディレクトリ名 `cam{serial}/` と一致させる |

---

## 3. 機能要求一覧

### FR-001: ファイル名の `cam{serial}` 統一

- **概要**: エクスポートファイル名のプレフィックスを `{serial}` から `cam{serial}` に変更する
- **入力**: なし（内部変更）
- **処理**:
  1. TOML ファイル名を `{serial}_intrinsics.toml` → `cam{serial}_intrinsics.toml` に変更する
  2. JSON ファイル名を `{serial}_intrinsics.json` → `cam{serial}_intrinsics.json` に変更する
- **出力**: ファイル名が `cam{serial}_intrinsics.toml` / `cam{serial}_intrinsics.json` になる
- **受け入れ基準**:
  - エクスポートされたファイル名が `cam{serial}_intrinsics.toml` / `cam{serial}_intrinsics.json` であること
  - ディレクトリ名 `cam{serial}/` とファイル名プレフィックス `cam{serial}_` が一致すること

### FR-002: TOML内カメラ名の `cam{serial}` 統一

- **概要**: TOML内のセクション名と `name` フィールドを `cam_{serial}` → `cam{serial}` に変更する
- **入力**: なし（内部変更）
- **処理**:
  1. TOMLセクション名を `[cam_{serial}]` → `[cam{serial}]` に変更する
  2. `name` フィールドを `"cam_{serial}"` → `"cam{serial}"` に変更する
- **出力**: TOML内のカメラ名が `cam{serial}` になる
- **受け入れ基準**:
  - TOMLのセクション名が `[cam{serial}]`（アンダースコアなし）であること
  - `name` フィールドが `"cam{serial}"` であること
  - Pose2Simの予約セクション名（metadata, capture_volume, charuco, checkerboard）と衝突しないこと

### FR-003: エクスポート完了ポップアップ

- **概要**: エクスポート完了時にQMessageBoxで保存先パスを通知する
- **入力**: エクスポート成功
- **処理**:
  1. エクスポート成功後、`QMessageBox.information()` でポップアップを表示する
  2. タイトル: `"Export Complete"`
  3. メッセージ: `"Exported to:\n{export_dir}"` （保存先ディレクトリの絶対パスを表示する）
- **出力**: ポップアップダイアログの表示
- **受け入れ基準**:
  - エクスポート成功後にポップアップが表示されること
  - ポップアップに保存先パスが含まれること
  - エクスポート失敗時はポップアップを表示しないこと（ステータスラベルのエラー表示のみ）

---

## 4. 非機能要求

### 4.1 対応環境

Ubuntu Linux、Python 3.10、micromamba SynchroCap環境。

---

## 5. 制約条件

### 5.1 使用必須ライブラリ

既存と同一。`QMessageBox` は PySide6.QtWidgets に含まれる（追加インポートのみ）。

### 5.2 Pose2Sim互換性

`cam{serial}` はTOMLの有効なセクション名であり、Pose2Simの予約セクション名と衝突しない。Pose2Simの `retrieve_calib_params()` はセクション名を動的に読み込むため、`cam_{serial}` → `cam{serial}` の変更は互換性に影響しない。

---

## 6. 優先順位

| 優先度 | 機能ID | 機能名 |
|--------|--------|--------|
| **Must** | FR-001 | ファイル名の `cam{serial}` 統一 |
| **Must** | FR-002 | TOML内カメラ名の `cam{serial}` 統一 |
| **Must** | FR-003 | エクスポート完了ポップアップ |

### MVP範囲

FR-001〜FR-003すべてがMVP。

---

## 7. スコープ外

- Save（キャプチャ画像保存）完了時のポップアップ追加
- エクスポート失敗時のポップアップ追加
