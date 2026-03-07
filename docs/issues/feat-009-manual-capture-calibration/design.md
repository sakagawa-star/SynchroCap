# 機能設計書: Camera Calibration - Auto Capture (Stability Trigger)

対象: feat-009
作成日: 2026-03-07 (再作成)
基準文書: `docs/DESIGN_STANDARD.md`
要求仕様書: `docs/issues/feat-009-manual-capture-calibration/requirements.md`

---

## 1. 対応要求マッピング

| 要求ID | 要求名 | 設計セクション |
|--------|--------|---------------|
| FR-001 | 安定検出トリガーによる自動キャプチャ | 4.1 |
| FR-002 | クールダウン制御 | 4.2 |
| FR-003 | キャプチャリスト管理 | 4.3 |
| FR-004 | キャプチャ時フィードバック | 4.4 |
| FR-005 | 静止画保存（デバッグ用） | 4.5 |
| FR-006 | カメラ切替・タブ離脱時のキャプチャクリア | 4.6 |

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
| `src/synchroCap/stability_trigger.py` | 安定検出トリガーエンジン（新規） | **新規作成** |
| `src/synchroCap/ui_calibration.py` | Tab5 CalibrationWidget（キャプチャUI追加） | **変更** |
| `src/synchroCap/board_detector.py` | ボード検出エンジン（変更なし） | 変更なし |
| `src/synchroCap/mainwindow.py` | タブ管理（変更なし） | 変更なし |

### 2.3 モジュール間の依存関係

```
mainwindow.py (既存・変更なし)
  +-- ui_calibration.py (変更)
        +-- stability_trigger.py (新規)
        +-- board_detector.py (既存・変更なし)
        +-- imagingcontrol4 (ic4)
        +-- cv2
        +-- numpy
        +-- channel_registry.py
        +-- device_resolver.py
```

循環依存は存在しない。

### 2.4 ディレクトリ構成

```
src/synchroCap/
+-- stability_trigger.py                # 新規
+-- ui_calibration.py                   # 変更
+-- board_detector.py                   # 変更なし
+-- mainwindow.py                       # 変更なし
+-- (その他既存ファイル)                 # 変更なし
```

---

## 3. 技術スタック

| 項目 | バージョン |
|------|-----------|
| Python | 3.10 |

| ライブラリ | バージョン | 用途 | 選定理由 |
|-----------|-----------|------|---------|
| imagingcontrol4 | >=1.2.0 | カメラ制御 | SynchroCap既存 |
| PySide6 | ==6.8.3 | GUI | SynchroCap既存 |
| opencv-contrib-python | >=4.9.0 | ボード検出（既存）、静止画保存 | feat-008で導入済み |
| numpy | >=2.0.0 | 画像配列操作 | 既存 |

新規ライブラリの追加なし。

---

## 4. 各機能の詳細設計

### 4.1 安定検出トリガー（FR-001）

#### データフロー

- 入力: 毎フレームの `DetectionResult`（board_detector.pyから）
- 出力: キャプチャ実行の判定（`StabilityState` の返却）

#### StabilityTrigger クラス設計

安定判定ロジックを `stability_trigger.py` に分離する。UIに依存しない純粋なロジッククラスとする。

```python
# stability_trigger.py

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum, auto


class Phase(Enum):
    """安定判定の内部フェーズ"""
    MONITORING = auto()   # 監視中（連続成功を追跡）
    COOLDOWN = auto()     # クールダウン中


@dataclass
class StabilityState:
    """安定判定の状態を表すデータクラス。毎フレームupdate()から返される。"""
    triggered: bool               # True: キャプチャを実行すべき
    phase: Phase                  # 現在のフェーズ
    stability_progress: float     # 安定判定の進行度（0.0〜1.0）。MONITORING時のみ有効
    stability_elapsed: float      # 連続成功経過時間（秒）。MONITORING時のみ有効
    cooldown_remaining: float     # クールダウン残り時間（秒）。COOLDOWN時のみ有効


class StabilityTrigger:
    """安定検出トリガーエンジン。

    毎フレーム update(detected) を呼び、返された StabilityState.triggered が
    True の場合にキャプチャを実行する。
    """

    STABILITY_THRESHOLD: float = 2.0   # 安定判定時間（秒）
    COOLDOWN_DURATION: float = 3.0     # クールダウン時間（秒）

    def __init__(self) -> None:
        self._phase: Phase = Phase.MONITORING
        self._stable_since: float | None = None    # 連続成功開始時刻
        self._cooldown_start: float | None = None  # クールダウン開始時刻

    def update(self, detected: bool) -> StabilityState:
        """毎フレーム呼び出す。検出結果に基づいて状態を更新し、現在の状態を返す。

        Args:
            detected: ボード検出が成功したかどうか

        Returns:
            StabilityState: 現在の安定判定状態
        """
        now = time.monotonic()

        if self._phase == Phase.COOLDOWN:
            return self._update_cooldown(now)

        # Phase.MONITORING
        return self._update_monitoring(now, detected)

    def reset(self) -> None:
        """状態を完全にリセットする。カメラ切替時やタブ離脱時に呼ぶ。"""
        self._phase = Phase.MONITORING
        self._stable_since = None
        self._cooldown_start = None

    def _update_monitoring(self, now: float, detected: bool) -> StabilityState:
        if not detected:
            self._stable_since = None
            return StabilityState(
                triggered=False,
                phase=Phase.MONITORING,
                stability_progress=0.0,
                stability_elapsed=0.0,
                cooldown_remaining=0.0,
            )

        # 検出成功
        if self._stable_since is None:
            self._stable_since = now

        elapsed = now - self._stable_since
        progress = min(elapsed / self.STABILITY_THRESHOLD, 1.0)

        if elapsed >= self.STABILITY_THRESHOLD:
            # 安定判定成立 → キャプチャトリガー → クールダウンに遷移
            self._phase = Phase.COOLDOWN
            self._cooldown_start = now
            self._stable_since = None
            return StabilityState(
                triggered=True,
                phase=Phase.COOLDOWN,
                stability_progress=1.0,
                stability_elapsed=elapsed,
                cooldown_remaining=self.COOLDOWN_DURATION,
            )

        return StabilityState(
            triggered=False,
            phase=Phase.MONITORING,
            stability_progress=progress,
            stability_elapsed=elapsed,
            cooldown_remaining=0.0,
        )

    def _update_cooldown(self, now: float) -> StabilityState:
        elapsed = now - self._cooldown_start
        remaining = self.COOLDOWN_DURATION - elapsed

        if remaining <= 0:
            # クールダウン終了 → MONITORING に復帰
            self._phase = Phase.MONITORING
            self._stable_since = None
            self._cooldown_start = None
            return StabilityState(
                triggered=False,
                phase=Phase.MONITORING,
                stability_progress=0.0,
                stability_elapsed=0.0,
                cooldown_remaining=0.0,
            )

        return StabilityState(
            triggered=False,
            phase=Phase.COOLDOWN,
            stability_progress=0.0,
            stability_elapsed=0.0,
            cooldown_remaining=remaining,
        )
```

**設計判断**: stability_trigger.py の分離
- 採用: 安定判定ロジックを独立モジュールに分離（テスタビリティ、UI非依存の純粋ロジック。単体テストで `time.monotonic()` をモックしてテスト可能）
- 却下: `ui_calibration.py` に直接記述（UIコードと判定ロジックの混在を避ける）
- 却下: `board_detector.py` に追加（ボード検出と安定判定は責務が異なる）

**設計判断**: 経過時間ベース vs フレーム数ベース
- 採用: `time.monotonic()` による経過時間ベース（FPSの変動に左右されない。QTimerの間隔変更やフレーム落ちの影響を受けない）
- 却下: 連続成功フレーム数ベース（QTimerの間隔が33msの前提に依存する。カメラFPS変更時に閾値の再計算が必要）

#### ui_calibration.py でのキャプチャ実行

`_process_latest_frame()` を変更する。現在のコード（`ui_calibration.py:313-326`）:

```python
# 現在のコード
def _process_latest_frame(self) -> None:
    frame = self._latest_frame
    if frame is None:
        return
    self._latest_frame = None
    bgr = frame
    result = self._detector.detect(bgr)
    if result.success:
        bgr = self._detector.draw_overlay(bgr, result)
    self._update_detection_status(result)
    self._display_frame(bgr)
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

    # draw_overlay() はコピーを返す（board_detector.py:227）。
    # bgr（raw）と overlay_bgr を分離することで、_execute_capture() に両方を渡せる。
    if result.success:
        overlay_bgr = self._detector.draw_overlay(bgr, result)
    else:
        overlay_bgr = bgr

    # 安定判定の更新
    state = self._stability_trigger.update(result.success)

    if state.triggered and result.success:
        self._execute_capture(result, bgr, overlay_bgr)

    # ステータス表示の更新（既存の _update_detection_status() を置き換え）
    self._update_status_display(result, state)
    self._display_frame(overlay_bgr)
```

**変更ポイント**:
- `bgr` 変数の再代入（`bgr = self._detector.draw_overlay(bgr, result)`）をやめ、`overlay_bgr` として別変数に受ける
- `_update_detection_status()` を `_update_status_display()` に置き換える（StabilityStateも受け取る）
- `_update_detection_status()` メソッドは削除する

#### キャプチャデータの保持

```python
@dataclass
class CaptureData:
    """1回のキャプチャで取得したデータ"""
    image_points: numpy.ndarray   # shape=(N,1,2), float32
    object_points: numpy.ndarray  # shape=(N,1,3), float32
    charuco_ids: numpy.ndarray | None  # shape=(N,1), int32 (ChArUco only)
    num_corners: int
```

`CaptureData` は `ui_calibration.py` のモジュールレベルで定義する（`CalibrationWidget` の外側、import 群の後）。

メンバー変数（`CalibrationWidget.__init__()` に追加）:
- `self._captures: list[CaptureData]` — キャプチャリスト。初期値: `[]`
- `self._capture_image_size: tuple[int, int] | None` — 最初のキャプチャの画像サイズ (width, height)。初期値: `None`
- `self._capture_counter: int` — セッション内の累積キャプチャカウンタ（0始まり）。キャプチャ実行時にインクリメントされる。キャプチャ削除では減らない。クリア時のみ0にリセットされる。静止画保存のファイル番号に使用する。初期値: `0`

#### キャプチャ実行処理

```python
def _execute_capture(
    self,
    result: DetectionResult,
    raw_bgr: numpy.ndarray,
    overlay_bgr: numpy.ndarray,
) -> None:
    """安定判定成立時のキャプチャ実行処理。

    Args:
        result: 直近の検出結果（success==Trueが保証されている）
        raw_bgr: オーバーレイなしのBGRフレーム（image_size取得用）
        overlay_bgr: オーバーレイ描画済みのBGRフレーム（静止画保存用）
    """
    h, w = raw_bgr.shape[:2]
    current_size = (w, h)

    # image_size 検証
    if self._capture_image_size is None:
        self._capture_image_size = current_size
    elif self._capture_image_size != current_size:
        self._status_label.setText("Image size mismatch")
        logger.warning("Image size mismatch: expected %s, got %s",
                       self._capture_image_size, current_size)
        return

    capture = CaptureData(
        image_points=result.image_points.copy(),
        object_points=result.object_points.copy(),
        charuco_ids=result.charuco_ids.copy() if result.charuco_ids is not None else None,
        num_corners=result.num_corners,
    )
    self._captures.append(capture)
    self._capture_counter += 1
    n = len(self._captures)

    self._update_capture_list_ui()
    self._update_button_states()
    self._flash_live_view()

    # 静止画保存（FR-005）
    # ファイル番号は累積カウンタを使用する（削除による番号重複・上書きを防止）
    if self._save_images_check.isChecked():
        self._save_capture_image(overlay_bgr, self._capture_counter)

    self._status_label.setText(f"Captured #{n} ({capture.num_corners} corners)")
    logger.info("Capture #%d: %d corners", n, capture.num_corners)
```

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| image_size不一致 | タプル比較 | キャプチャ拒否、ステータス表示 | WARNING: `Image size mismatch` |

#### 境界条件

- ボード検出失敗が断続的に混在: 1フレームでも失敗すれば連続成功時刻がリセットされる
- アプリ起動直後の最初のフレーム: `_stable_since` が `None` なので安定判定は開始しない

### 4.2 クールダウン制御（FR-002）

`StabilityTrigger` クラスに内蔵（4.1のコード参照）。

#### 処理ロジック

1. `_update_monitoring()` で `elapsed >= STABILITY_THRESHOLD` → `Phase.COOLDOWN` に遷移、`_cooldown_start = now`
2. `_update_cooldown()` で `remaining <= 0` → `Phase.MONITORING` に復帰、`_stable_since = None`

#### 境界条件

- キャプチャ直後にボードを外す（検出失敗）: クールダウン状態には影響しない。クールダウンは時間ベースで完了する
- クールダウン中にタブ離脱: `reset()` が呼ばれて全状態がリセットされる

### 4.3 キャプチャリスト管理（FR-003）

#### UI構成

左パネルの Board Settings の下に「Captures」QGroupBox を追加する。

```python
# Captures section
captures_group = QGroupBox("Captures")
captures_layout = QVBoxLayout(captures_group)

self._captures_list = QListWidget()
captures_layout.addWidget(self._captures_list)

captures_btn_layout = QHBoxLayout()
self._delete_button = QPushButton("Delete")
self._delete_button.setEnabled(False)
self._delete_button.clicked.connect(self._on_delete_clicked)
captures_btn_layout.addWidget(self._delete_button)

self._clear_all_button = QPushButton("Clear All")
self._clear_all_button.setEnabled(False)
self._clear_all_button.clicked.connect(self._on_clear_all_clicked)
captures_btn_layout.addWidget(self._clear_all_button)
captures_layout.addLayout(captures_btn_layout)
```

`_captures_list` の `currentRowChanged` シグナルを `_update_button_states` に接続して、選択変更時にDeleteボタンの有効/無効を更新する。

#### Delete処理

```python
def _on_delete_clicked(self) -> None:
    row = self._captures_list.currentRow()
    if row < 0 or row >= len(self._captures):
        return
    self._captures.pop(row)
    if not self._captures:
        self._capture_image_size = None
        self._capture_counter = 0
        self._session_dir = None
    self._update_capture_list_ui()
    self._update_button_states()
    logger.info("Deleted capture #%d", row + 1)
```

#### Clear All処理

```python
def _on_clear_all_clicked(self) -> None:
    self._captures.clear()
    self._capture_image_size = None
    self._capture_counter = 0
    self._session_dir = None  # 次のキャプチャで新しいセッションディレクトリを作成
    self._update_capture_list_ui()
    self._update_button_states()
    logger.info("Cleared all captures")
```

#### リスト更新

```python
def _update_capture_list_ui(self) -> None:
    self._captures_list.clear()
    for i, cap in enumerate(self._captures):
        self._captures_list.addItem(f"#{i+1:02d}: {cap.num_corners} corners")
```

#### ボタン状態更新

```python
def _update_button_states(self) -> None:
    has_captures = len(self._captures) > 0
    has_selection = self._captures_list.currentRow() >= 0

    self._delete_button.setEnabled(has_captures and has_selection)
    self._clear_all_button.setEnabled(has_captures)
```

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| 無効なインデックスでDelete | `row < 0` チェック | 何もしない | なし |

#### 境界条件

- キャプチャ0件: Delete, Clear All ボタン全て無効
- キャプチャ1件以上: Clear All 有効、Delete は選択時のみ有効

### 4.4 キャプチャ時フィードバック（FR-004）

#### ステータス表示の更新

```python
def _update_status_display(self, result: DetectionResult, state: StabilityState) -> None:
    """検出結果と安定判定状態に基づいてステータスラベルを更新する。

    triggered==True の場合は _execute_capture() 内でステータスが上書きされるため、
    ここでは triggered==False の場合のみ更新する。
    """
    if state.triggered:
        return  # _execute_capture() がステータスを設定する

    if state.phase == Phase.COOLDOWN:
        self._status_label.setText(f"Cooldown: {state.cooldown_remaining:.1f}s")
        return

    # Phase.MONITORING
    if result.success:
        total = self._detector.max_corners
        if state.stability_elapsed > 0:
            self._status_label.setText(
                f"Detected: {result.num_corners}/{total} | "
                f"Stability: {state.stability_elapsed:.1f}s / "
                f"{StabilityTrigger.STABILITY_THRESHOLD:.1f}s"
            )
        else:
            self._status_label.setText(
                f"Detected: {result.num_corners}/{total} corners"
            )
    elif result.failure_reason:
        self._status_label.setText(result.failure_reason)
    else:
        self._status_label.setText("No board detected")
```

#### フラッシュ演出

キャプチャ成功時にライブビューの枠線を緑色にフラッシュする。

**QLabel に直接 border を設定してはならない**（`_display_frame()` の `pixmap.scaled(label.size())` とのフィードバックループでウィンドウが無限拡大する既知の問題）。QFrame で QLabel を包み、QFrame の border を操作する。

##### UIレイアウトの変更

`_create_ui()` 内で、`_live_view_label` を QFrame で包む:

```python
# 変更前（ui_calibration.py:200-203）:
# self._live_view_label = QLabel("カメラを選択してください")
# self._live_view_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
# self._live_view_label.setStyleSheet("background-color: #1a1a1a; color: #888;")
# right_layout.addWidget(self._live_view_label, stretch=1)

# 変更後:
self._live_view_frame = QFrame()
self._live_view_frame.setFrameShape(QFrame.Shape.NoFrame)
self._live_view_frame.setStyleSheet("background-color: #1a1a1a;")
frame_inner_layout = QVBoxLayout(self._live_view_frame)
frame_inner_layout.setContentsMargins(0, 0, 0, 0)

self._live_view_label = QLabel("カメラを選択してください")
self._live_view_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
self._live_view_label.setStyleSheet("background-color: #1a1a1a; color: #888;")
# setPixmap() で sizeHint が pixmap サイズに変わり、レイアウトがそれに追従して
# QFrame が拡大 → label.size() が拡大 → scaled pixmap が拡大 → 無限ループとなる
# 既知の問題を防止するため、sizeHint を無視するポリシーを設定する
self._live_view_label.setSizePolicy(
    QSizePolicy.Policy.Ignored,
    QSizePolicy.Policy.Ignored,
)
frame_inner_layout.addWidget(self._live_view_label)

right_layout.addWidget(self._live_view_frame, stretch=1)
```

##### フラッシュの実装

```python
_FLASH_DURATION_MS: int = 300
_FLASH_BORDER: str = "border: 3px solid #00cc00;"
_NORMAL_BORDER: str = ""

def _flash_live_view(self) -> None:
    """ライブビューの枠線を一瞬緑色にフラッシュする。QFrame の border を操作する。"""
    self._live_view_frame.setStyleSheet(
        f"background-color: #1a1a1a; {self._FLASH_BORDER}"
    )
    QTimer.singleShot(self._FLASH_DURATION_MS, self._reset_live_view_style)

def _reset_live_view_style(self) -> None:
    """フラッシュを元に戻す。"""
    self._live_view_frame.setStyleSheet("background-color: #1a1a1a;")
```

**設計判断**: フラッシュ方式
- 採用: QFrame wrapper の border を操作 + `QTimer.singleShot()` で復元（QLabel borderの既知の問題を回避しつつシンプル）
- 却下: QLabel の `setStyleSheet()` で直接 border を設定（フィードバックループでウィンドウが無限拡大する既知の問題あり）
- 却下: QPropertyAnimation（オーバーエンジニアリング）

##### stop_live_view() での対応

`stop_live_view()` で `_live_view_frame` のスタイルもリセットする:

```python
# stop_live_view() に追加:
self._live_view_frame.setStyleSheet("background-color: #1a1a1a;")
```

### 4.5 静止画保存（FR-005）

#### UI構成

左パネルの Captures GroupBox 内にチェックボックスを追加する。

```python
self._save_images_check = QCheckBox("Save Images")
self._save_images_check.setChecked(False)  # デフォルトOFF
captures_layout.addWidget(self._save_images_check)
```

#### 保存パス管理

キャプチャセッションごとにタイムスタンプディレクトリを作成する。

メンバー変数:
- `self._session_dir: Path | None` — 現在のセッションの保存ディレクトリ。最初のキャプチャ時に作成される。初期値: `None`

```python
from datetime import datetime
from pathlib import Path

def _ensure_session_dir(self) -> Path | None:
    """セッションディレクトリを作成して返す。既に作成済みならそのまま返す。

    Returns:
        Path: セッションディレクトリのパス
        None: 作成に失敗した場合
    """
    if self._session_dir is not None:
        return self._session_dir

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    cam_dir = Path("captures") / timestamp / "intrinsics" / f"cam{self._current_serial}"
    try:
        cam_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("Failed to create session dir %s: %s", cam_dir, e)
        self._status_label.setText(f"Save failed: {e}")
        return None

    self._session_dir = cam_dir
    logger.info("Session dir created: %s", cam_dir)
    return cam_dir
```

#### 静止画保存処理

```python
def _save_capture_image(self, overlay_bgr: numpy.ndarray, capture_number: int) -> None:
    """キャプチャ画像をPNGファイルとして保存する。

    Args:
        overlay_bgr: オーバーレイ描画済みのBGRフレーム
        capture_number: キャプチャ番号（1始まり）
    """
    cam_dir = self._ensure_session_dir()
    if cam_dir is None:
        return

    filename = f"capture_{capture_number:03d}.png"
    filepath = cam_dir / filename
    try:
        cv2.imwrite(str(filepath), overlay_bgr)
        logger.info("Saved capture image: %s", filepath)
    except Exception as e:
        logger.error("Failed to save capture image %s: %s", filepath, e)
        self._status_label.setText(f"Save failed: {e}")
```

**設計判断**: 保存する画像
- 採用: オーバーレイ描画済みフレーム（デバッグ用途なので検出結果が可視化されている方が有用）
- 却下: 生フレーム（検出結果が見えないとデバッグに不便）

**設計判断**: 保存タイミング
- 採用: メインスレッドで同期保存（HD解像度のPNG保存は50ms以下。QTimerの33ms間隔に対して1フレーム遅延する可能性があるが、キャプチャは数秒に1回なので問題ない）
- 却下: バックグラウンドスレッドで非同期保存（数秒に1回の保存にスレッド管理のコストは見合わない）

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| ディレクトリ作成失敗 | OSError catch | ステータスに表示、保存スキップ（キャプチャは保持） | ERROR |
| imwrite 失敗 | Exception catch | ステータスに表示、保存スキップ（キャプチャは保持） | ERROR |

### 4.6 カメラ切替・タブ離脱時のキャプチャクリア（FR-006）

#### 処理ロジック

既存の `stop_live_view()` にキャプチャクリアと安定判定リセットを追加する。

```python
def stop_live_view(self) -> None:
    """Stop live view and release Grabber. Safe to call in any state."""
    self._frame_timer.stop()
    if self._grabber is not None:
        try:
            self._grabber.stream_stop()
        except ic4.IC4Exception as e:
            logger.warning("stream_stop failed: %s", e)
        try:
            self._grabber.device_close()
        except ic4.IC4Exception as e:
            logger.warning("device_close failed: %s", e)
        self._grabber = None
    self._sink = None
    self._latest_frame = None
    self._current_serial = ""
    self._live_view_label.clear()
    self._live_view_label.setText("カメラを選択してください")
    self._live_view_frame.setStyleSheet("background-color: #1a1a1a;")  # 追加: フラッシュリセット
    self._status_label.setText("Ready")
    # キャプチャクリア（追加）
    self._captures.clear()
    self._capture_image_size = None
    self._capture_counter = 0
    self._session_dir = None
    self._stability_trigger.reset()
    self._update_capture_list_ui()
    self._update_button_states()
```

**設計判断**: stop_live_view() でキャプチャクリアする
- 採用: `stop_live_view()` にクリア処理を追加（タブ離脱、カメラ切り替え、カメラ切断の全ケースで確実にクリアされる。`mainwindow.py:248` の `onTabChanged()` → `_stop_calibration_if_active()` → `stop_live_view()` と、`ui_calibration.py:253` の `_on_camera_clicked()` → `stop_live_view()` の両方の経路をカバーする）
- 却下: `_on_camera_clicked()` のみでクリア（タブ離脱やカメラ切断時にクリアされない恐れがある）

---

## 5. 状態遷移

### 5.1 CalibrationWidgetの状態遷移

feat-008の状態を維持（Idle, Connecting, LiveView）。

```
[Idle] --(カメラクリック)--> [Connecting]
[Connecting] --(接続成功)--> [LiveView]
[Connecting] --(接続失敗)--> [Idle]
[Connecting] --(タブ離脱)--> [Idle]
[LiveView] --(別カメラクリック)--> [Connecting]  ※キャプチャクリア
[LiveView] --(タブ離脱)--> [Idle]                ※キャプチャクリア
[LiveView] --(カメラ切断)--> [Idle]              ※キャプチャクリア
```

### 5.2 安定判定の内部状態（LiveView内）

```
[MONITORING] --(安定判定成立)--> [COOLDOWN]   ※キャプチャ実行
[MONITORING] --(検出失敗)----> [MONITORING]  ※連続成功時刻リセット
[COOLDOWN]   --(時間経過)----> [MONITORING]  ※連続成功時刻リセット
```

| 状態 | ステータス表示 |
|------|---------------|
| MONITORING（検出失敗） | `No board detected` または failure_reason |
| MONITORING（検出成功、安定判定開始前） | `Detected: X/Y corners` |
| MONITORING（安定判定進行中） | `Detected: X/Y | Stability: 1.2s / 2.0s` |
| COOLDOWN | `Cooldown: 2.1s` |

### 5.3 各状態でのUI要素の状態

| 状態 | カメラ一覧 | Delete | Clear All | Save Images | ライブビュー |
|------|-----------|--------|-----------|-------------|-------------|
| Idle | 有効 | 無効 | 無効 | 有効 | メッセージ表示 |
| Connecting | 無効 | 無効 | 無効 | 有効 | 空 |
| LiveView | 有効 | 選択時有効 | キャプチャ1件以上で有効 | 有効 | ライブ表示 |

---

## 6. ファイル・ディレクトリ設計

### 6.1 静止画保存パス

```
captures/
+-- YYYYMMDD-HHMMSS/                  # キャプチャセッションのタイムスタンプ
    +-- intrinsics/
        +-- cam{serial}/
            +-- capture_001.png
            +-- capture_002.png
            +-- ...
```

- パスは `src/synchroCap/` からの相対パス（`Path("captures") / ...`）。起動方法が `cd src/synchroCap && python main.py` に限定されているため、カレントディレクトリが `src/synchroCap/` であることを前提とする（recording_controller.py と同一の前提）
- Multi Viewの録画保存先と同じ `captures/` ディレクトリ下に配置
- `YYYYMMDD-HHMMSS` は最初のキャプチャ実行時の `datetime.now().strftime("%Y%m%d-%H%M%S")`
- `{serial}` はカメラのシリアル番号（例: `49710307`）
- 番号は1始まり、3桁ゼロパディング（001〜999）
- PNG形式（ロスレス）
- オーバーレイ描画済みのBGRフレームを保存

### 6.2 設定ファイル

本案件で設定ファイルの入出力はない。

---

## 7. インターフェース定義

### 7.1 stability_trigger.py（新規）

```python
class Phase(Enum):
    MONITORING = auto()
    COOLDOWN = auto()


@dataclass
class StabilityState:
    triggered: bool
    phase: Phase
    stability_progress: float
    stability_elapsed: float
    cooldown_remaining: float


class StabilityTrigger:
    STABILITY_THRESHOLD: float = 2.0
    COOLDOWN_DURATION: float = 3.0

    def __init__(self) -> None: ...
    def update(self, detected: bool) -> StabilityState: ...
    def reset(self) -> None: ...
```

### 7.2 ui_calibration.py（変更分のみ）

既存の `CalibrationWidget` クラスに以下を追加する。
import に `QCheckBox`, `QFrame`, `QScrollArea`, `QSizePolicy` を追加する（`QCheckBox` は既存importになければ追加。`QFrame`, `QScrollArea`, `QSizePolicy` は新規）:

```python
from PySide6.QtWidgets import (
    # 既存の import に以下を追加:
    QCheckBox,
    QFrame,
    QScrollArea,
    QSizePolicy,
)
```

```python
class CalibrationWidget(QWidget):
    # -- 追加メンバー変数 --
    # self._captures: list[CaptureData]
    # self._capture_image_size: tuple[int, int] | None
    # self._capture_counter: int  (累積カウンタ、静止画ファイル番号用)
    # self._session_dir: Path | None
    # self._stability_trigger: StabilityTrigger

    # -- 追加UIウィジェット --
    # self._live_view_frame: QFrame (QLabel wrapper、フラッシュ用)
    # self._live_view_label: setSizePolicy(Ignored, Ignored) を追加（無限拡大防止）
    # self._captures_list: QListWidget
    # self._delete_button: QPushButton
    # self._clear_all_button: QPushButton
    # self._save_images_check: QCheckBox

    # -- 削除するメソッド --
    # _update_detection_status() → _update_status_display() に置き換えて削除

    # -- 追加メソッド --

    def _execute_capture(
        self,
        result: DetectionResult,
        raw_bgr: numpy.ndarray,
        overlay_bgr: numpy.ndarray,
    ) -> None:
        """安定判定成立時のキャプチャ実行処理"""

    def _on_delete_clicked(self) -> None:
        """Deleteボタン押下時。選択中のキャプチャを削除"""

    def _on_clear_all_clicked(self) -> None:
        """Clear Allボタン押下時。全キャプチャを削除"""

    def _update_capture_list_ui(self) -> None:
        """キャプチャリストのQListWidgetを更新"""

    def _update_button_states(self) -> None:
        """各ボタンの有効/無効状態を更新"""

    def _update_status_display(
        self,
        result: DetectionResult,
        state: StabilityState,
    ) -> None:
        """検出結果と安定判定状態に基づいてステータスを更新"""

    def _flash_live_view(self) -> None:
        """ライブビューの枠線を一瞬緑色にフラッシュ（QFrameのborderを操作）"""

    def _reset_live_view_style(self) -> None:
        """フラッシュを元に戻す"""

    def _ensure_session_dir(self) -> Path | None:
        """セッションディレクトリを作成して返す"""

    def _save_capture_image(
        self,
        overlay_bgr: numpy.ndarray,
        capture_number: int,
    ) -> None:
        """キャプチャ画像をPNGファイルとして保存"""
```

### 7.3 UIレイアウト（変更後）

```
+----------+------------------+
|Camera    |  Status (QLabel) |  ← 既存と同じくライブビューの上に配置（変更なし）
|List      |------------------|
|(QList)   |   Live View      |
|----------|   (QFrame >      |  ← QFrame wrapper 追加（フラッシュ用）
|Board     |    QLabel)       |
|Settings  |                  |
|----------|                  |
|Captures  |                  |
|(QList)   |                  |
|[Delete][Clear All]          |
|[x] Save Images              |
|          |                  |
+----------+------------------+
左パネル(left_panel): 固定幅200px（変更なし）
QScrollArea: 固定幅220px（200 + スクロールバー幅の余裕）で left_panel を包む
```

左パネルの構成（上から順）:
1. Camera（QGroupBox）-- 既存
2. Board Settings（QGroupBox）-- 既存
3. Captures（QGroupBox）-- 新規

左パネルの `addStretch()` （`ui_calibration.py:186`）を削除し、上記3つのグループボックスをすべて追加する。左パネルの縦方向にコンテンツが収まりきらない場合に備え、左パネル全体をQScrollArea内に配置する。

```python
# 左パネルをスクロール可能にする
# 変更前（ui_calibration.py:188-189）:
# left_panel.setFixedWidth(200)
# splitter.addWidget(left_panel)

# 変更後:
left_panel.setFixedWidth(200)
scroll_area = QScrollArea()
scroll_area.setWidgetResizable(True)
scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
scroll_area.setWidget(left_panel)
scroll_area.setFixedWidth(220)  # 200 + スクロールバー幅の余裕
splitter.addWidget(scroll_area)
```

---

## 8. ログ・デバッグ設計

### 8.1 ログレベル使い分け

| レベル | 使い分け | 例 |
|--------|---------|-----|
| INFO | キャプチャ操作、セッションディレクトリ作成 | `Capture #5: 24 corners`, `Session dir created: ...` |
| WARNING | 軽微なエラー | `Image size mismatch` |
| ERROR | ファイル保存失敗 | `Failed to save capture image: ...` |
| DEBUG | 安定判定の経過（デフォルトでは出力されない） | — |

### 8.2 ログ出力ポイント

| モジュール | INFO | WARNING | ERROR |
|-----------|------|---------|-------|
| ui_calibration | キャプチャ追加/削除、静止画保存成功、セッションディレクトリ作成 | image_size不一致 | 静止画保存失敗 |
| stability_trigger | — | — | — |

`stability_trigger.py` はロギングを行わない。状態は `StabilityState` の返却値で呼び出し元に伝える。

---

## 9. テスト方針

### 9.1 単体テスト対象

`stability_trigger.py` の `StabilityTrigger` クラス:
- 連続成功2.0秒で `triggered=True` が返される
- 途中で検出失敗すると連続成功時刻がリセットされる
- クールダウン中は `triggered=True` が返されない
- クールダウン終了後に再び安定判定が開始される
- `reset()` で全状態がリセットされる

テストでは `time.monotonic` をモック（`unittest.mock.patch`）して時間を制御する。

### 9.2 統合テスト

GUIを含む統合テストは手動で実施する。テスト項目:
- カメラ接続後、ボードを静止させて自動キャプチャが発生すること
- クールダウン中にキャプチャが発生しないこと
- キャプチャリストの表示・削除が正常に動作すること
- Save Images ON/OFF で静止画保存の有無が切り替わること
- カメラ切替でキャプチャがクリアされること
