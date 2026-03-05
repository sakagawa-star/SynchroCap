# 機能設計書: Calibration SpinBox ホイールスクロール誤操作防止

対象: bug-007
作成日: 2026-03-05
基準文書: `docs/DESIGN_STANDARD.md`
要求仕様書: `docs/issues/bug-007-calibration-spinbox-wheel-scroll/requirements.md`

---

## 1. 対応要求マッピング

| 要求ID | 要求名 | 設計セクション |
|--------|--------|---------------|
| FR-001 | SpinBoxのホイールスクロール無効化 | 4.1 |

---

## 2. システム構成

### 2.1 関連ファイル

| ファイル | 役割 | 変更種別 |
|---------|------|---------|
| `src/synchroCap/ui_calibration.py` | Board Settings の SpinBox を派生クラスに置き換え | **軽微変更** |
| `src/synchroCap/ui_camera_settings.py` | 既存の `FocusWheelDoubleSpinBox` 定義元（参考・変更なし） | 参考のみ |

### 2.2 モジュール間の依存関係

変更は `ui_calibration.py` 内で完結する。他モジュールへの影響なし。

---

## 3. 技術スタック

既存技術スタックの範囲内。追加ライブラリなし。

---

## 4. 詳細設計

### 4.1 ホイールスクロール無効化（FR-001）

#### 設計方針

Camera Settings（Tab2）の `FocusWheelDoubleSpinBox`（`ui_camera_settings.py:99-104`）と同じパターンを使用する。`wheelEvent` をオーバーライドし、フォーカスがない場合は `event.ignore()` で親ウィジェットにイベントを伝播させる。

Board Settings には QSpinBox（int）と QDoubleSpinBox（float）の両方が使われているため、2つの派生クラスを `ui_calibration.py` 内に定義する。

#### 実装

`ui_calibration.py` のモジュールスコープ（クラス定義の前）に以下の2クラスを追加する:

```python
class _FocusWheelSpinBox(QSpinBox):
    """QSpinBox that only accepts wheel events when focused."""

    def wheelEvent(self, event) -> None:
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


class _FocusWheelDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that only accepts wheel events when focused."""

    def wheelEvent(self, event) -> None:
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)
```

**設計判断**: クラスの配置場所
- 採用: `ui_calibration.py` 内にプライベートクラスとして定義（`_` プレフィックス）
- 却下案1: `ui_camera_settings.py` の `FocusWheelDoubleSpinBox` を共有モジュールに移動 → 本バグ修正のスコープを超える。リファクタリングは別案件で行う
- 却下案2: `ui_camera_settings.py` から import → `ui_camera_settings.py` には QDoubleSpinBox 版しかなく、QSpinBox 版が不足。また、モジュール間の不要な依存を作る

#### 変更箇所

`CalibrationWidget._create_ui()` 内の4つのウィジェット生成を以下のように変更する:

| 変更前 | 変更後 | 対象変数 |
|--------|--------|---------|
| `QSpinBox()` | `_FocusWheelSpinBox()` | `self._cols_spin` |
| `QSpinBox()` | `_FocusWheelSpinBox()` | `self._rows_spin` |
| `QDoubleSpinBox()` | `_FocusWheelDoubleSpinBox()` | `self._square_spin` |
| `QDoubleSpinBox()` | `_FocusWheelDoubleSpinBox()` | `self._marker_spin` |

import文の変更は不要（QSpinBox, QDoubleSpinBox は派生元として引き続き必要）。

#### エラーハンドリング

なし。wheelEvent のオーバーライドのみで、例外は発生しない。

#### 境界条件

- SpinBox にフォーカスがある状態でホイール操作: 従来通り値が変化する
- SpinBox にフォーカスがない状態でホイール操作: イベントが無視され、親ウィジェット（スクロール領域など）にイベントが伝播する

---

## 5. ログ・デバッグ設計

ログ出力の追加なし。wheelEvent のオーバーライドのみの変更のため。
