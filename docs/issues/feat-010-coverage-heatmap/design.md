# 機能設計書: Camera Calibration - Coverage Heatmap

対象: feat-010
作成日: 2026-03-10
基準文書: `docs/DESIGN_STANDARD.md`
要求仕様書: `docs/issues/feat-010-coverage-heatmap/requirements.md`

---

## 1. 対応要求マッピング

| 要求ID | 要求名 | 設計セクション |
|--------|--------|---------------|
| FR-001 | ヒートマップ生成 | 4.1 |
| FR-002 | ライブビューへの自動オーバーレイ表示 | 4.2 |
| FR-003 | ヒートマップキャッシュの更新タイミング | 4.3 |

---

## 2. システム構成

### 2.1 モジュール構成図

```
+-----------------------------------------------------------------+
|                        MainWindow (既存)                         |
|  +-----------------------------------------------------------+  |
|  |                      QTabWidget                            |  |
|  |  +--------+--------+--------+--------+-----------------+  |  |
|  |  | Tab1   | Tab2   | Tab3   | Tab4   | Tab5            |  |  |
|  |  |Channel | Camera | Multi  |Settings| Calibration     |  |  |
|  |  |Manager |Settings| View   | Viewer | Widget (変更)   |  |  |
|  |  +--------+--------+--------+--------+-----------------+  |  |
|  +-----------------------------------------------------------+  |
+-----------------------------------------------------------------+
```

### 2.2 関連ファイル

| ファイル | 役割 | 変更種別 |
|---------|------|---------|
| `src/synchroCap/coverage_heatmap.py` | ヒートマップ生成エンジン（新規） | **新規作成** |
| `src/synchroCap/ui_calibration.py` | Tab5 CalibrationWidget（ヒートマップオーバーレイ追加） | **変更** |
| `src/synchroCap/board_detector.py` | ボード検出エンジン（変更なし） | 変更なし |
| `src/synchroCap/stability_trigger.py` | 安定検出トリガー（変更なし） | 変更なし |
| `src/synchroCap/mainwindow.py` | タブ管理（変更なし） | 変更なし |

### 2.3 モジュール間の依存関係

```
mainwindow.py (既存・変更なし)
  +-- ui_calibration.py (変更)
        +-- coverage_heatmap.py (新規)
        +-- stability_trigger.py (既存・変更なし)
        +-- board_detector.py (既存・変更なし)
        +-- imagingcontrol4 (ic4)
        +-- cv2
        +-- numpy
        +-- channel_registry.py
        +-- device_resolver.py
```

循環依存は存在しない。`coverage_heatmap.py` は `numpy` と `cv2` のみに依存する。

### 2.4 ディレクトリ構成

```
src/synchroCap/
+-- coverage_heatmap.py                # 新規
+-- ui_calibration.py                  # 変更
+-- stability_trigger.py               # 変更なし
+-- board_detector.py                  # 変更なし
+-- mainwindow.py                      # 変更なし
+-- (その他既存ファイル)                # 変更なし
```

---

## 3. 技術スタック

| 項目 | バージョン |
|------|-----------|
| Python | 3.10 |

| ライブラリ | バージョン | 用途 | 選定理由 |
|-----------|-----------|------|---------|
| numpy | ==2.2.6 | ガウシアン累積マップ生成 | 既存（バージョンは TECH_STACK.md に従う） |
| opencv-contrib-python | >=4.9.0 | applyColorMap, addWeighted, GaussianBlur | 既存 |
| PySide6 | ==6.8.3 | GUI | 既存 |

新規ライブラリの追加なし。

---

## 4. 各機能の詳細設計

### 4.1 ヒートマップ生成（FR-001）

#### データフロー

- 入力:
  - `points: numpy.ndarray` — 全キャプチャの image_points を結合した配列。shape=(M,2), float32（M = 全コーナー数の合計）。CaptureData.image_points は shape=(N,1,2) であるため、`reshape(-1, 2)` で (N,2) に変換してから `numpy.concatenate()` で結合する
  - `image_size: tuple[int, int]` — (width, height)
- 中間データ:
  - 点マップ: shape=(height, width), float32 — 各コーナー位置に1.0を配置
  - ガウシアンブラー適用後: shape=(height, width), float32 — 各コーナーの影響範囲が面として広がる
  - 正規化済み: shape=(height, width), uint8（0〜255）
- 出力:
  - ヒートマップ画像: shape=(height, width, 3), uint8, BGR

#### CoverageHeatmap クラス設計

ヒートマップ生成ロジックを `coverage_heatmap.py` に分離する。UIに依存しない純粋な計算クラスとする。

```python
# coverage_heatmap.py

from __future__ import annotations

import cv2
import numpy


class CoverageHeatmap:
    """カバレッジヒートマップ生成エンジン。

    キャプチャ済みコーナー座標から画像全体のカバレッジを
    ヒートマップ画像として生成する。各コーナー点にガウシアン
    カーネルで影響範囲を持たせ、ボードがカバーした領域を
    面として可視化する。
    """

    SIGMA_RATIO: float = 0.05  # σ = 画像幅 × SIGMA_RATIO

    def __init__(self, image_size: tuple[int, int]) -> None:
        """初期化。

        Args:
            image_size: 画像サイズ (width, height)
        """
        self._width, self._height = image_size
        self._sigma = max(1.0, self._width * self.SIGMA_RATIO)

    def generate(self, points: numpy.ndarray) -> numpy.ndarray:
        """ヒートマップ画像を生成する。

        Args:
            points: 全コーナー座標。shape=(M,2), float32。
                    M=0 の場合は黒画像を返す。

        Returns:
            ヒートマップ画像。shape=(height, width, 3), uint8, BGR。
        """
        if len(points) == 0:
            return numpy.zeros((self._height, self._width, 3), dtype=numpy.uint8)

        # 点マップ: 各コーナー位置に1.0を配置
        point_map = numpy.zeros((self._height, self._width), dtype=numpy.float32)
        xs = numpy.clip(points[:, 0].astype(int), 0, self._width - 1)
        ys = numpy.clip(points[:, 1].astype(int), 0, self._height - 1)
        numpy.add.at(point_map, (ys, xs), 1.0)

        # ガウシアンブラーで影響範囲を広げる
        # ksize=0 でσからカーネルサイズを自動計算
        blurred = cv2.GaussianBlur(point_map, (0, 0), self._sigma)

        # 正規化（最大値 → 255）
        max_val = blurred.max()
        if max_val > 0:
            normalized = (blurred / max_val * 255).astype(numpy.uint8)
        else:
            normalized = numpy.zeros_like(blurred, dtype=numpy.uint8)

        # カラーマップ適用
        colored = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)

        # 値0のピクセルは黒にする（カバレッジなし = 黒）
        colored[normalized == 0] = [0, 0, 0]

        return colored
```

**設計判断**: coverage_heatmap.py の分離
- 採用: ヒートマップ生成ロジックを独立モジュールに分離（テスタビリティ、UI非依存の純粋ロジック。stability_trigger.py と同じ設計パターン）
- 却下: `ui_calibration.py` に直接記述（UIコードと計算ロジックの混在を避ける）

**設計判断**: ガウシアンカーネルによる面表示（イテレーション2で変更）
- 採用: 各コーナー点にガウシアンカーネル（σ=画像幅×5%）で影響範囲を持たせる。`cv2.GaussianBlur()` で点マップを畳み込むことで、コーナー間の隙間が埋まりボードがカバーした領域が面として表示される
- 却下: `numpy.histogram2d()` によるグリッド分割方式（イテレーション1-2で、コーナーの離散的な点しか表示されずボードの領域が認識できないとのフィードバック）
- 却下: 凸包塗りつぶし方式（ボードの凸包で領域を塗りつぶす方式。キャリブレーションの目的は画像全域にコーナーを分布させることであり、凸包の塗りつぶしはその目的と直接対応しない）

**設計判断**: σの値
- 採用: 画像幅の5%（HD 1920px → σ=96px。ボードのコーナー間距離を十分にカバーしつつ、画像全体がぼけすぎない）
- 却下: 固定ピクセル値（画像解像度が変わると適切でなくなる）

**設計判断**: カラーマップの選定
- 採用: `COLORMAP_TURBO`（JETより知覚均一性が高く、段階の違いが視認しやすい）
- 却下: `COLORMAP_JET`（イテレーション1で色の意味が分からないとのフィードバック）

**設計判断**: 値0のピクセルの扱い
- 採用: 黒（0,0,0）にする（カラーマップは値0を青色で描画するが、「カバレッジなし」と「カバレッジ最小」が区別できない。黒にすることで「未カバー領域 = 次にボードを置くべき場所」が明確になる）
- 却下: カラーマップそのまま（青=カバレッジなし/ありが区別できない）

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| points が空配列 | `len(points) == 0` | 黒画像を返す | なし（正常系として扱う）|

#### 境界条件

- キャプチャ1件でコーナーが1つの場合: そのコーナー周囲にガウシアンが広がり、σ範囲が色付きになる
- 全コーナーが同一位置に集中する場合: その位置周囲のみが赤（255）、ガウシアンの裾野外は黒になる
- image_size が極端に小さい場合（例: 幅20px未満）: σが1.0にクランプされ、狭い範囲にガウシアンが集中する

### 4.2 ライブビューへの自動オーバーレイ表示（FR-002）

#### データフロー

```
フレーム受信
    ↓
bgr (raw frame)
    ↓
result = detector.detect(bgr)
    ↓
overlay_bgr = draw_overlay(bgr, result)  ← ボード検出オーバーレイ（既存）
    ↓
if heatmap_cache is not None:
    overlay_bgr = cv2.addWeighted(overlay_bgr, 0.7, heatmap_cache, 0.3, 0)
    ↓
display_frame(overlay_bgr)
```

#### _process_latest_frame() の変更

現在の `_process_latest_frame()`:

```python
def _process_latest_frame(self) -> None:
    frame = self._latest_frame
    if frame is None:
        return
    self._latest_frame = None
    bgr = frame
    result = self._detector.detect(bgr)
    if result.success:
        overlay_bgr = self._detector.draw_overlay(bgr, result)
    else:
        overlay_bgr = bgr
    state = self._stability_trigger.update(result.success)
    if state.triggered and result.success:
        self._execute_capture(result, bgr)
    self._update_status_display(result, state)
    self._display_frame(overlay_bgr)
```

変更後:

```python
def _process_latest_frame(self) -> None:
    frame = self._latest_frame
    if frame is None:
        return
    self._latest_frame = None
    bgr = frame
    result = self._detector.detect(bgr)
    if result.success:
        overlay_bgr = self._detector.draw_overlay(bgr, result)
    else:
        overlay_bgr = bgr
    state = self._stability_trigger.update(result.success)
    if state.triggered and result.success:
        self._execute_capture(result, bgr)
    self._update_status_display(result, state)

    # ヒートマップオーバーレイ（追加）— キャプチャ1件以上で自動表示
    if self._heatmap_cache is not None:
        overlay_bgr = cv2.addWeighted(overlay_bgr, 0.7, self._heatmap_cache, 0.3, 0)

    self._display_frame(overlay_bgr)
```

**変更ポイント**:
- `self._display_frame(overlay_bgr)` の直前にヒートマップオーバーレイ合成を挿入
- `overlay_bgr` に再代入するため、ボード検出オーバーレイとヒートマップオーバーレイが重畳される
- トグルボタンは不要。`_heatmap_cache is not None` のみで判定する（キャプチャ1件以上で自動表示）

#### アルファブレンドのパラメータ

```python
cv2.addWeighted(overlay_bgr, 0.7, self._heatmap_cache, 0.3, 0)
```

- `overlay_bgr` のウェイト: 0.7（ライブビュー + ボード検出オーバーレイ）
- `heatmap_cache` のウェイト: 0.3（ヒートマップ）
- gamma: 0

**設計判断**: アルファ値の選定
- 採用: ライブビュー0.7、ヒートマップ0.3（ライブビューの視認性を優先しつつ、ヒートマップが十分に見える）
- 却下: 0.5 / 0.5（ライブビューが暗くなりすぎ、ボード検出が見づらい）
- 却下: 0.9 / 0.1（ヒートマップがほぼ見えない）

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| heatmap_cache のサイズがフレームと異なる | 発生しない。理由: (1) `_execute_capture()` で `_capture_image_size` との一致を検証済み、(2) CLAUDE.md「カメラ設定変更禁止ルール」によりCalibrationタブで解像度が変更されることはない | — | — |

### 4.3 ヒートマップキャッシュの更新タイミング（FR-003）

#### 処理ロジック

ヒートマップキャッシュの更新を1つのメソッド `_update_heatmap_cache()` に集約する。

```python
def _update_heatmap_cache(self) -> None:
    """ヒートマップキャッシュを再計算する。キャプチャが0件の場合はNoneにクリアする。"""
    if not self._captures or self._capture_image_size is None:
        self._heatmap_cache = None
        return

    # 全キャプチャの image_points を結合
    # CaptureData.image_points: shape=(N,1,2) → reshape(-1,2) で (N,2) に変換
    all_points = numpy.concatenate(
        [cap.image_points.reshape(-1, 2) for cap in self._captures],
        axis=0,
    )

    if self._heatmap_generator is None:
        self._heatmap_generator = CoverageHeatmap(self._capture_image_size)

    self._heatmap_cache = self._heatmap_generator.generate(all_points)
```

#### 呼び出し箇所

| 呼び出し元 | タイミング | 説明 |
|-----------|----------|------|
| `_execute_capture()` | キャプチャ追加後 | `self._captures.append(capture)` の後に呼び出す |
| `_on_delete_clicked()` | キャプチャ削除後 | `self._captures.pop(row)` の後に呼び出す |
| `_on_clear_all_clicked()` | 全キャプチャクリア後 | `self._captures.clear()` の後に呼び出す |
| `stop_live_view()` | カメラ切替・タブ離脱時 | キャプチャクリア後に呼び出す |

#### _execute_capture() への追加

```python
def _execute_capture(self, result: DetectionResult, raw_bgr: numpy.ndarray) -> None:
    # ... 既存のキャプチャ追加処理 ...
    self._captures.append(capture)
    n = len(self._captures)

    self._update_heatmap_cache()   # 追加
    self._update_capture_list_ui()
    self._update_button_states()
    self._flash_live_view()
    # ...
```

#### _on_delete_clicked() への追加

```python
def _on_delete_clicked(self) -> None:
    # ... 既存の削除処理 ...
    self._captures.pop(row)
    if not self._captures:
        self._capture_image_size = None
    self._update_heatmap_cache()   # 追加
    self._update_capture_list_ui()
    self._update_button_states()
    # ...
```

#### _on_clear_all_clicked() への追加

```python
def _on_clear_all_clicked(self) -> None:
    self._captures.clear()
    self._capture_image_size = None
    self._update_heatmap_cache()   # 追加
    self._update_capture_list_ui()
    self._update_button_states()
    # ...
```

#### stop_live_view() への追加

```python
def stop_live_view(self) -> None:
    # ... 既存のクリア処理 ...
    self._captures.clear()
    self._capture_image_size = None
    self._stability_trigger.reset()
    self._heatmap_cache = None          # 追加
    self._heatmap_generator = None      # 追加
    self._update_capture_list_ui()
    self._update_button_states()
```

#### 境界条件

- キャプチャ追加直後にDelete: 正しく再計算される（キャプチャ数が変わるたびに全件から再計算）
- Clear All直後にキャプチャ追加: `_heatmap_generator` が `None` になっているため、新しい `image_size` で再作成される

---

## 5. 状態遷移

CalibrationWidget の状態遷移は feat-009 と同一（Idle, Connecting, LiveView）。本案件で新たな状態は追加しない。不正な遷移が要求された場合の振る舞いも feat-009 の設計に従う。

ヒートマップはキャプチャが1件以上存在する場合に自動表示される（`_heatmap_cache is not None` で判定。トグル操作なし）。

### 5.1 各状態でのUI要素の状態

| 状態 | カメラ一覧 | Delete | Clear All | Save | ライブビュー |
|------|-----------|--------|-----------|------|-------------|
| Idle | 有効 | 無効 | 無効 | 無効 | メッセージ表示 |
| Connecting | 無効 | 無効 | 無効 | 無効 | 空 |
| LiveView（キャプチャ0件）| 有効 | 無効 | 無効 | 無効 | ライブ表示 |
| LiveView（キャプチャ1件以上）| 有効 | 選択時有効 | 有効 | 有効 | ライブ表示 + ヒートマップ自動オーバーレイ |

---

## 6. ファイル・ディレクトリ設計

本案件でファイル入出力はない。

---

## 7. インターフェース定義

### 7.1 coverage_heatmap.py（新規）

```python
class CoverageHeatmap:
    SIGMA_RATIO: float = 0.05  # σ = 画像幅 × SIGMA_RATIO

    def __init__(self, image_size: tuple[int, int]) -> None:
        """初期化。image_size は (width, height)。"""
        ...

    def generate(self, points: numpy.ndarray) -> numpy.ndarray:
        """ヒートマップ画像を生成。
        Args:
            points: shape=(M,2), float32。全コーナー座標。
        Returns:
            shape=(height, width, 3), uint8, BGR。
        """
        ...
```

### 7.2 ui_calibration.py（変更分のみ）

既存の `CalibrationWidget` クラスに以下を追加する。

`__init__` の `# Capture state` セクションの後に以下を追加:

```python
        # Heatmap state
        self._heatmap_generator: CoverageHeatmap | None = None
        self._heatmap_cache: numpy.ndarray | None = None
```

import に `CoverageHeatmap` を追加:

```python
from coverage_heatmap import CoverageHeatmap
```

```python
class CalibrationWidget(QWidget):
    # -- 追加メンバー変数 --
    # self._heatmap_generator: CoverageHeatmap | None  — 初期値: None
    # self._heatmap_cache: numpy.ndarray | None         — 初期値: None

    # -- 追加メソッド --

    def _update_heatmap_cache(self) -> None:
        """ヒートマップキャッシュを再計算する。"""

    # -- 変更メソッド --
    # _process_latest_frame(): ヒートマップオーバーレイ合成を追加
    # _execute_capture(): _update_heatmap_cache() 呼び出しを追加
    # _on_delete_clicked(): _update_heatmap_cache() 呼び出しを追加
    # _on_clear_all_clicked(): _update_heatmap_cache() 呼び出しを追加
    # stop_live_view(): heatmap キャッシュ・ジェネレータのクリアを追加
```

---

## 8. ログ・デバッグ設計

### 8.1 ログレベル使い分け

| レベル | 使い分け | 例 |
|--------|---------|-----|
| INFO | ヒートマップキャッシュ更新 | `Heatmap updated: M points, sigma=S`（注: sigma値は `_heatmap_generator._sigma` から取得。呼び出し元 ui_calibration.py からの利用に限定） |
| DEBUG | 生成時間の計測（デフォルトでは出力されない） | — |

### 8.2 ログ出力ポイント

| モジュール | INFO | WARNING | ERROR |
|-----------|------|---------|-------|
| ui_calibration | ヒートマップキャッシュ更新 | — | — |
| coverage_heatmap | — | — | — |

`coverage_heatmap.py` はロギングを行わない。計算結果は返却値で呼び出し元に伝える。

### 8.3 ログフォーマット

既存の `ui_calibration.py` のロガー設定に従う。フォーマットは `[%(asctime)s] %(levelname)s %(name)s: %(message)s`（datefmt: `%H:%M:%S`）を使用。

---

## 9. テスト方針

### 9.1 単体テスト対象

`coverage_heatmap.py` の `CoverageHeatmap` クラス:
- 空のポイント配列で黒画像が返される
- 1点でガウシアンの影響範囲が色付き面として表示される
- 遠い位置はカバレッジなし（黒）になる
- 複数点でそれぞれの周囲が色付きになる
- ガウシアンの影響でコーナー間の隙間が埋まる
- カバレッジなしのピクセルが黒になる
- 出力画像サイズが入力 image_size と一致する
- σの計算（画像幅 × SIGMA_RATIO）が正しい
- 画像端のポイント・画像外のポイントでエラーが発生しない

テストでは `numpy` でテスト用ポイント配列を作成し、生成結果の画像を検証する。

### 9.2 統合テスト

GUIを含む統合テストは手動で実施する。テスト項目:
- キャプチャ追加後、ヒートマップが自動的にオーバーレイ表示される
- ボードがカバーした領域が面として表示される
- 新しいキャプチャが追加されるとヒートマップが更新される
- キャプチャ削除時にヒートマップが更新される
- Clear Allでヒートマップが消える
- ライブビューのFPSが維持される（体感的にカクつかない）
- カメラ切替でヒートマップがクリアされる
