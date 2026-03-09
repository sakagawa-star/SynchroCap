# investigation.md: feat-009 Auto Capture (Stability Trigger)

## イテレーション1 (2026-03-09)

### 1.1 不具合の特定

- **対応する要求ID**: FR-005（静止画保存）
- **対応する設計セクション**: 4.5
- **現在の動作**: Save Images チェックボックスを事前にONにしておき、キャプチャ発生時に自動で保存する方式。ユーザーから「保存の手順が分からない・使いづらい」とフィードバックあり
- **期待する動作**: キャプチャ後に保存操作を行う方式。全キャプチャの生フレームを一括保存する

### 1.2 原因分析

- **原因箇所**: FR-005 の要求定義（ヒアリング不足）
- **原因の説明**: 「デバッグ用」として事前チェックボックス方式を採用したが、実際のユースケースではキャプチャ後に保存判断したいというニーズがあった
- **根本原因**: 要求仕様作成時のヒアリング漏れ

### 1.3 修正内容

要求仕様書（FR-005）と機能設計書（セクション4.5）を以下の方針で改訂する:

- **Save Images チェックボックスを廃止** → 「Save」ボタンに置き換え
- **CaptureData に生フレーム（raw_bgr）を保持** → 保存時にオーバーレイなしの画像を書き出すため
- **保存タイミングを変更**: キャプチャ時の自動保存 → ボタン押下時に全キャプチャを一括保存
- **保存パスは現行維持**: `captures/YYYYMMDD-HHMMSS/intrinsics/cam{serial}/capture_{番号:03d}.png`
- **保存する画像**: オーバーレイ付き → 生フレーム（オーバーレイなし）に変更

#### 変更対象ファイル

| ファイル | 変更内容 |
|---------|---------|
| `docs/issues/feat-009-manual-capture-calibration/requirements.md` | FR-005 改訂 |
| `docs/issues/feat-009-manual-capture-calibration/design.md` | セクション4.5 改訂、CaptureData にraw_bgr追加 |
| `src/synchroCap/ui_calibration.py` | Save Images チェックボックス → Save ボタン、CaptureData にraw_bgr追加、_save_capture_image / _ensure_session_dir → _on_save_clicked |

#### 変更しないファイル

| ファイル | 理由 |
|---------|------|
| `src/synchroCap/stability_trigger.py` | 安定検出ロジックに変更なし |
| `tests/test_stability_trigger.py` | 安定検出テストに変更なし |

### 1.4 影響範囲

- **他の機能への影響**: なし（FR-005のUI・保存ロジックのみ）
- **リグレッションリスク**: CaptureData にフィールド追加するため、既存のキャプチャ処理（_execute_capture）の変更が必要。FR-001〜004, FR-006 への影響は軽微

### 1.5 確認方法

- **自動テスト**: stability_trigger.py に変更なしのため追加テスト不要
- **手動テスト**:
  1. 複数回キャプチャを実行する
  2. 「Save」ボタンを押して全キャプチャが保存されることを確認する
  3. 保存先パスが `captures/YYYYMMDD-HHMMSS/intrinsics/cam{serial}/capture_001.png` であることを確認する
  4. 保存される画像がオーバーレイなし（生フレーム）であることを確認する
