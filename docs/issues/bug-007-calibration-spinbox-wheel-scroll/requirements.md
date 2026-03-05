# 要求仕様書: Calibration SpinBox ホイールスクロール誤操作防止

対象: bug-007
作成日: 2026-03-05
基準文書: `docs/REQUIREMENTS_STANDARD.md`

---

## 1. プロジェクト概要

### 1.1 何を作るか

Calibrationタブ（Tab5）の Board Settings パネル内の SpinBox / DoubleSpinBox に対し、マウスホイールによる意図しない値変更を防止する。

### 1.2 なぜ作るか

現状、Board Settings のSpinBox がフォーカスを持っていない状態でも、マウスホイール操作で値が変わってしまう。ユーザーがライブビューをスクロールしようとした際に、意図せずボード設定が変更され、ボード検出が正しく動作しなくなる。Camera Settings（Tab2）では `FocusWheelDoubleSpinBox` で同様の問題を解決済みであり、Calibrationタブも同じ対策を適用する。

### 1.3 誰が使うか

SynchroCapでキャリブレーションを行うオペレーター。

### 1.4 どこで使うか

SynchroCapと同一のPC環境（Ubuntu Linux、micromamba SynchroCap環境）。

---

## 2. 用語定義

| 用語 | 定義 |
|------|------|
| Board Settings | Calibrationタブ左パネル内のボード設定パネル。ボードタイプ・列数・行数・チェッカーサイズ・マーカーサイズを設定する |
| FocusWheelSpinBox | フォーカスを持っている場合のみホイール操作を受け付けるSpinBoxの派生クラス |

---

## 3. 機能要求一覧

### FR-001: SpinBox のホイールスクロール無効化

- **概要**: Board Settings 内の全 SpinBox / DoubleSpinBox で、フォーカスを持っていない状態でのマウスホイール操作を無視する
- **入力**: マウスホイール操作
- **出力**: フォーカスがない場合は値が変化しない。フォーカスがある場合は通常通り値が変化する
- **対象ウィジェット**（4つ）:
  - Columns（QSpinBox）
  - Rows（QSpinBox）
  - Square size（QDoubleSpinBox）
  - Marker size（QDoubleSpinBox）
- **受け入れ基準**:
  - フォーカスなしの状態でホイール操作しても値が変化しない
  - SpinBox をクリックしてフォーカスを取得した後は、ホイール操作で値が変化する
  - キーボード入力による値変更は従来通り動作する
- **異常系**: なし（UI動作の変更のみ）

---

## 4. 非機能要求

- Camera Settings（Tab2）の `FocusWheelDoubleSpinBox` と同じ挙動を提供する
- 既存の Board Settings の機能（設定変更時の BoardDetector 再初期化）に影響を与えない

---

## 5. 制約条件

- Camera Settings（Tab2）の既存実装 `FocusWheelDoubleSpinBox` パターンに従う
- QSpinBox 用の派生クラスも必要（Camera Settings には QDoubleSpinBox 版のみ存在）

---

## 6. 優先順位

| 要求ID | MoSCoW | 備考 |
|--------|--------|------|
| FR-001 | Must | 全SpinBox/DoubleSpinBoxが対象 |
