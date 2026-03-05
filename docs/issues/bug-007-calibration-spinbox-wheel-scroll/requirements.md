# 要求仕様書: Calibration Board Settings 誤操作防止

対象: bug-007
作成日: 2026-03-05
基準文書: `docs/REQUIREMENTS_STANDARD.md`

---

## 1. プロジェクト概要

### 1.1 何を作るか

Calibrationタブ（Tab5）の Board Settings パネルのUI操作方式を変更する。現在の直接編集可能なSpinBox方式から、Camera Settings（Tab2）と同じ「読み取り専用の値表示 + クリックでダイアログ変更」方式に変更する。

### 1.2 なぜ作るか

現状、Board Settings のSpinBox/DoubleSpinBoxはマウスオーバー+ホイール操作で値が変わってしまう。ユーザーがライブビューをスクロールしようとした際に、意図せずボード設定が変更され、ボード検出が正しく動作しなくなる。Camera Settings（Tab2）では「設定変更はダイアログ経由のみ」という設計思想で誤操作を防止しており、Calibrationタブも同じ設計思想に従う。

### 1.3 誰が使うか

SynchroCapでキャリブレーションを行うオペレーター。

### 1.4 どこで使うか

SynchroCapと同一のPC環境（Ubuntu Linux、micromamba SynchroCap環境）。

---

## 2. 用語定義

| 用語 | 定義 |
|------|------|
| Board Settings | Calibrationタブ左パネル内のボード設定パネル。ボードタイプ・列数・行数・チェッカーサイズ・マーカーサイズを設定する |
| ダイアログ方式 | 設定値をクリックするとQDialogが開き、OK/Cancelボタンで確定・キャンセルする操作方式。Camera Settings（Tab2）で採用されている |

---

## 3. 機能要求一覧

### FR-001: Board Settings の値表示を読み取り専用にする

- **概要**: Board Settings 内の設定項目を、直接編集可能なSpinBox/ComboBoxから、読み取り専用の値表示に変更する
- **入力**: なし（UI構築時）
- **出力**: 各設定項目の現在値がラベルまたは読み取り専用ウィジェットで表示される
- **対象項目**（5つ）:
  - Type（現在: QComboBox → 変更後: 現在値をQLabelで表示）
  - Columns（現在: QSpinBox → 変更後: 現在値をQLabelで表示）
  - Rows（現在: QSpinBox → 変更後: 現在値をQLabelで表示）
  - Square size（現在: QDoubleSpinBox → 変更後: 現在値をQLabelで表示）
  - Marker size（現在: QDoubleSpinBox → 変更後: 現在値をQLabelで表示）
- **受け入れ基準**:
  - 各設定項目の現在値が読み取れる
  - マウスホイール操作で値が変化しない
  - 値の表示フォーマット:
    - Type: `ChArUco` または `Checkerboard`
    - Columns / Rows: 整数（例: `5`、`7`）
    - Square size / Marker size: 小数1桁 + 単位（例: `30.0 mm`、`22.0 mm`）
- **異常系**: なし

### FR-002: クリックでダイアログを開き設定変更する

- **概要**: Board Settings 内の各設定項目の値表示部分をクリックすると、設定変更用のQDialogが開く
- **入力**: 値表示部分のクリック
- **出力**: QDialogが表示され、OK で値が反映、Cancel で変更がキャンセルされる
- **対象項目と入力ウィジェット**（5つ）:
  - Type: QComboBox（ChArUco / Checkerboard）
  - Columns: QSpinBox（範囲: 3〜20）
  - Rows: QSpinBox（範囲: 3〜20）
  - Square size: QDoubleSpinBox（範囲: 1.0〜200.0mm、ステップ: 0.5）
  - Marker size: QDoubleSpinBox（範囲: 1.0〜200.0mm、ステップ: 0.5、ChArUco選択時のみ有効）
- **受け入れ基準**:
  - ダイアログにOK/Cancelボタンがある
  - ダイアログを開いた時点で、現在の値がウィジェットに設定されている
  - OKを押すと値が反映され、BoardDetector が再初期化される
  - Cancelを押すと値は変更されない
  - marker_mm >= square_mm の場合の制約ロジック（既存の `_on_board_config_changed` と同一）が維持される
  - Marker size は board_type が `checkerboard` の場合はクリック不可（グレーアウト表示）
- **異常系**: なし

---

## 4. 非機能要求

- Camera Settings（Tab2）のダイアログ方式と同じ操作感を提供する
- 既存の BoardDetector 再初期化ロジックに影響を与えない

---

## 5. 制約条件

- ダイアログのボタン構成は QDialogButtonBox（OK / Cancel）を使用する（Camera Settings と統一）
- 既存のデフォルト値（cols=5, rows=7, square=30.0mm, marker=22.0mm, type=ChArUco）を維持する

---

## 6. 優先順位

| 要求ID | MoSCoW | 備考 |
|--------|--------|------|
| FR-001 | Must | 誤操作防止の根本対策 |
| FR-002 | Must | 設定変更手段の提供 |
