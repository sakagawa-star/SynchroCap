# 機能設計書: Camera Calibration - Live View with Board Detection

対象: feat-008
作成日: 2026-03-04
基準文書: `docs/DESIGN_STANDARD.md`
要求仕様書: `docs/issues/feat-008-camera-calibration/requirements.md`

---

## 1. 対応要求マッピング

| 要求ID | 要求名 | 設計セクション |
|--------|--------|---------------|
| FR-001 | Calibrationタブ追加 | 4.1, 5.1 |
| FR-002 | カメラ選択 | 4.2 |
| FR-003 | ライブビュー表示 | 4.3, 5.1 |
| FR-004 | ChArUcoボード検出オーバーレイ | 4.4 |
| FR-005 | チェッカーボード検出オーバーレイ | 4.4 |
| FR-006 | ボード設定パネル | 4.5 |

---

## 2. システム構成

### 2.1 モジュール構成図

```
┌──────────────────────────────────────────────────────────────────────┐
│                        MainWindow (既存)                              │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                      QTabWidget                                │  │
│  │  ┌──────────┬──────────┬──────────┬──────────┬──────────────┐  │  │
│  │  │ Tab1     │ Tab2     │ Tab3     │ Tab4     │ Tab5         │  │  │
│  │  │ Channel  │ Camera   │ Multi    │ Settings │ Calibration  │  │  │
│  │  │ Manager  │ Settings │ View     │ Viewer   │ Widget(新規) │  │  │
│  │  └──────────┴──────────┴──────────┴──────────┴──────────────┘  │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 関連ファイル

| ファイル | 役割 | 変更種別 |
|---------|------|---------|
| `src/synchroCap/ui_calibration.py` | Tab5 CalibrationWidget（新規） | **新規作成** |
| `src/synchroCap/board_detector.py` | ボード検出エンジン（新規） | **新規作成** |
| `src/synchroCap/mainwindow.py` | タブ追加・切り替え制御 | **軽微変更** |
| `docs/TECH_STACK.md` | opencv-contrib-python追加 | **軽微変更** |

### 2.3 モジュール間の依存関係

```
mainwindow.py (既存)
  └── ui_calibration.py (新規)
        ├── board_detector.py (新規)
        ├── imagingcontrol4 (ic4)       # 既存
        ├── cv2 (opencv-contrib-python) # BayerGR8→BGR変換
        ├── numpy                       # 画像配列
        ├── channel_registry.py         # 既存
        └── device_resolver.py          # 既存

board_detector.py (新規)
  ├── cv2 (opencv-contrib-python)      # ArUco/ChArUco検出
  └── numpy                            # 座標配列
```

循環依存は存在しない。

### 2.4 ディレクトリ構成

```
src/synchroCap/
├── main.py                          # 既存（変更なし）
├── mainwindow.py                    # 既存（軽微変更: タブ追加）
├── ui_calibration.py                # ★新規
├── board_detector.py                # ★新規
├── ui_channel_manager.py            # 既存（変更なし）
├── ui_camera_settings.py            # 既存（変更なし）
├── ui_multi_view.py                 # 既存（変更なし）
├── ui_camera_settings_viewer.py     # 既存（変更なし）
├── channel_registry.py              # 既存（変更なし）
└── device_resolver.py               # 既存（変更なし）
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
| opencv-contrib-python | >=4.9.0 | ArUco/ChArUco検出（CharucoDetector API）、BayerGR8→BGR変換 | ArUcoモジュールがcontrib版にのみ含まれる。4.7+で`CharucoDetector`導入、4.9以降で安定 |
| numpy | >=2.0.0 | 画像配列操作 | cv2の依存として必須 |

**設計判断**: opencv-python vs opencv-contrib-python
- 採用: `opencv-contrib-python`（`cv2.aruco` モジュールがcontrib版にのみ含まれる）
- 却下: `opencv-python`のみ（ArUco/ChArUco検出ができない）

---

## 4. 各機能の詳細設計

### 4.1 Calibrationタブ追加（FR-001）

#### データフロー

- 入力: SynchroCap起動時の `MainWindow.__init__()`
- 出力: QTabWidgetにTab5（index=4）として `CalibrationWidget` が追加される

#### 処理ロジック

**mainwindow.py への追加（既存タブ追加パターンに準拠）:**

1. `CalibrationWidget` をインスタンス化（`registry`, `resolver`, `parent` を渡す）
2. `self.tabs.addTab()` でTab5（index=4）として追加
3. `onTabChanged()` にCalibrationタブへの遷移処理を追加
4. `set_tabs_locked()` にCalibrationタブの無効化を追加

```python
# mainwindow.py への追加（意図伝達用コード例）
from ui_calibration import CalibrationWidget

# createUI() 内、camera_settings_viewer_widget の後（tabs.currentChanged.connect の前）に追加
self.calibration_widget = CalibrationWidget(
    registry=self.channel_registry,
    resolver=self.device_resolver,
    parent=self,
)
self.tabs.addTab(self.calibration_widget, "Calibration")
```

**タブ切り替え制御（onTabChanged への追加）:**

既存の `onTabChanged()` の `elif ... camera_settings_viewer_widget:` ブロックの後に、Calibrationタブへの遷移分岐を追加する。また、既存の全分岐に `self.calibration_widget.stop_live_view()` を追加する。さらに、Tab1（Channel Manager）への遷移時にもCalibrationのライブビューを停止するため、先頭に `else` 節を追加する。

変更後の `onTabChanged()` 全体:

```python
def onTabChanged(self, index: int):
    if self._tabs_locked:
        multi_index = self.tabs.indexOf(self.multi_view_widget)
        if multi_index != -1 and index != multi_index:
            print("[tab-lock] blocked tab switch during recording")
            self._schedule_tab_lock_return(multi_index)
            return
    if self.tabs.widget(index) is self.camera_settings_widget:
        print("[tab-switch] to Tab2: stopping MultiView")
        try:
            self.multi_view_widget.stop_all()
        except Exception:
            pass
        self.calibration_widget.stop_live_view()       # ★追加
        QTimer.singleShot(0, self.camera_settings_widget.refresh_channels)
    elif self.tabs.widget(index) is self.multi_view_widget:
        print("[tab-switch] to Tab3: stopping CameraSettings preview")
        try:
            self.camera_settings_widget.stop_preview_only()
        except Exception:
            pass
        self.calibration_widget.stop_live_view()       # ★追加
        QTimer.singleShot(0, self.multi_view_widget.refresh_and_resume)
    elif self.tabs.widget(index) is self.camera_settings_viewer_widget:
        print("[tab-switch] to Tab4: stopping other tabs")
        try:
            self.multi_view_widget.stop_all()
        except Exception:
            pass
        try:
            self.camera_settings_widget.stop_preview_only()
        except Exception:
            pass
        self.calibration_widget.stop_live_view()       # ★追加
        QTimer.singleShot(0, self.camera_settings_viewer_widget.refresh)
    elif self.tabs.widget(index) is self.calibration_widget:  # ★新規ブロック
        print("[tab-switch] to Tab5: stopping other tabs")
        try:
            self.multi_view_widget.stop_all()
        except Exception:
            pass
        try:
            self.camera_settings_widget.stop_preview_only()
        except Exception:
            pass
        QTimer.singleShot(0, self.calibration_widget.on_tab_activated)
    else:  # Tab1（Channel Manager）など、既存に分岐がないタブ  ★追加
        self.calibration_widget.stop_live_view()
```

**タブロック拡張（set_tabs_locked への追加）:**

既存の `tab4_index` 処理の後に追加:

```python
tab_calib_index = self.tabs.indexOf(self.calibration_widget)
if tab_calib_index != -1:
    self.tabs.setTabEnabled(tab_calib_index, not locked)
```

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| CalibrationWidgetのインスタンス化失敗 | 例外キャッチ | タブを追加せずSynchroCapの他機能は通常通り動作 | ERROR: `Failed to create CalibrationWidget: {e}` |

### 4.2 カメラ選択（FR-002）

#### データフロー

- 入力: `ChannelRegistry.list_channels()` → `list[ChannelEntry]`
- 中間: `device_resolver.find_device_for_entry(entry)` → `ic4.DeviceInfo | None`
- 出力: 選択されたカメラの `ic4.Grabber` インスタンス（接続済み）

#### 処理ロジック

1. `on_tab_activated()` が呼ばれた時にカメラ一覧を更新する
2. `ChannelRegistry.list_channels()` で登録済みチャンネルを取得
3. 各チャンネルについて `device_resolver.find_device_for_entry()` でデバイス解決
4. 結果をQListWidgetに表示:
   - 接続中: `Ch-{id} ({serial})`（クリック可能）
   - 未接続: `Ch-{id} ({serial}) [offline]`（グレーアウト、`Qt.ItemFlag` でクリック不可に設定）
5. ユーザーがクリックしたカメラについて:
   a. 既存のGrabberがあれば `stop_live_view()` で停止
   b. 新しいGrabberを作成: `ic4.Grabber()` → `device_open(device_info)`
   c. ライブビュー開始（FR-003）

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| デバイス未検出 | `find_device_for_entry()` が `None` を返す | QListWidgetでグレーアウト表示 | INFO: `Camera {serial}: offline` |
| Grabber open失敗 | `ic4.IC4Exception` | ステータス表示にエラーメッセージ。ライブビューは開始しない | ERROR: `Failed to open {serial}: {e}` |
| 前カメラのstream_stop失敗 | `ic4.IC4Exception` | 例外を握りつぶし、新カメラの接続を続行 | WARNING: `stream_stop failed: {e}` |

#### 境界条件

- カメラ0台（全て未接続）: リストは表示されるが全てグレーアウト
- 未登録（ChannelRegistryが空）: リストが空。ステータスに `No channels registered` と表示

### 4.3 ライブビュー表示（FR-003）

#### データフロー

```
ic4.QueueSink → ic4.ImageBuffer → numpy.ndarray (BayerGR8, H×W, uint8)
  → cv2.cvtColor(COLOR_BayerGR2BGR) → numpy.ndarray (BGR, H×W×3, uint8)
  → BoardDetector.detect() + draw_overlay()
  → cv2.cvtColor(COLOR_BGR2RGB) → numpy.ndarray (RGB, H×W×3, uint8)
  → QImage(data, W, H, stride, Format_RGB888)
  → QPixmap.fromImage() → QLabel.setPixmap()
```

#### 処理ロジック

SynchroCapの既存パターン（`QueueSinkListener` コールバック）を採用する。ただし `DisplayWidget` は使用せず、自前でBayerGR8→BGR変換とオーバーレイ描画を行う。

**QueueSinkListenerの実装:**

```python
class _CalibSinkListener(ic4.QueueSinkListener):
    def __init__(self, on_frame_callback):
        self._on_frame = on_frame_callback

    def sink_connected(self, sink, image_type, min_buffers_required):
        sink.alloc_and_queue_buffers(min_buffers_required + 2)
        return True

    def sink_disconnected(self, sink):
        pass

    def frames_queued(self, sink):
        buf = sink.pop_output_buffer()
        if buf is not None:
            arr = buf.numpy_copy()  # BayerGR8, shape=(H, W), dtype=uint8
            self._on_frame(arr)
```

**フレーム処理フロー:**

フレームスキップ方式を採用する。`frames_queued()` は30FPSで呼ばれるが、最新フレームのみ保持し、QTimerで定期的に処理する。

```python
self._latest_frame = None          # numpy.ndarray | None
self._frame_timer = QTimer(self)
self._frame_timer.setInterval(33)  # 約30FPS
self._frame_timer.timeout.connect(self._process_latest_frame)

def _on_frame_received(self, frame: numpy.ndarray):
    """QueueSinkListenerのframes_queued()から（IC4内部スレッドで）呼ばれる。
    最新フレームを保存するだけ。
    スレッドセーフティ: Pythonの参照代入はGILにより実質アトミック。
    既存のui_camera_settings.pyと同じパターン。threading.Lockは不要。"""
    self._latest_frame = frame

def _process_latest_frame(self):
    """QTimerから呼ばれる。最新フレームを処理・表示する"""
    frame = self._latest_frame
    if frame is None:
        return
    self._latest_frame = None

    bgr = cv2.cvtColor(frame, cv2.COLOR_BayerGR2BGR)
    result = self._detector.detect(bgr)
    if result.success:
        bgr = self._detector.draw_overlay(bgr, result)
    self._update_detection_status(result)
    self._display_frame(bgr)
```

**ストリーム開始:**

```python
def _start_live_view(self, device_info: ic4.DeviceInfo):
    self._grabber = ic4.Grabber()
    self._grabber.event_add_device_lost(self._on_device_lost)
    self._grabber.device_open(device_info)
    listener = _CalibSinkListener(self._on_frame_received)
    self._sink = ic4.QueueSink(listener)
    self._grabber.stream_setup(self._sink)
    self._frame_timer.start()
```

**ストリーム停止（公開メソッド、mainwindowのタブ切り替えから呼ばれる）:**

```python
def stop_live_view(self):
    self._frame_timer.stop()
    if self._grabber is not None:
        try:
            self._grabber.stream_stop()
        except ic4.IC4Exception:
            pass
        try:
            self._grabber.device_close()
        except ic4.IC4Exception:
            pass
        self._grabber = None
    self._latest_frame = None
```

**フレーム表示:**

```python
def _display_frame(self, bgr: numpy.ndarray):
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    bytes_per_line = ch * w
    qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
    pixmap = QPixmap.fromImage(qimg)
    scaled = pixmap.scaled(
        self._live_view_label.size(),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    self._live_view_label.setPixmap(scaled)
```

**設計判断**: DisplayWidget vs 自前描画
- 採用: 自前でBayerGR8→BGR変換→QLabel描画（検出オーバーレイを重ねるためにBGR画像へのアクセスが必要）
- 却下: DisplayWidget使用（変換後の画像にアクセスできないため、オーバーレイ描画ができない）

**設計判断**: QThread vs QTimer + フレームスキップ
- 採用: QTimer + 最新フレーム保持（実装がシンプル。SynchroCapのQTimerパターンに準拠。検出処理は1フレームあたり10〜50msで、30FPS表示には十分）
- 却下: QThread + Queue（GILの制約でCPUバウンド処理のマルチスレッド効果が薄い。スレッド間通信の複雑さが増す）

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| stream_setup失敗 | `ic4.IC4Exception` | ステータスにエラー表示 | ERROR: `stream_setup failed: {e}` |
| BayerGR8変換失敗 | `cv2.error` | 該当フレームをスキップ | WARNING: `Bayer conversion failed` |
| QImage作成失敗 | `qimg.isNull()` チェック | 該当フレームをスキップ | WARNING: `QImage creation failed` |

#### 境界条件

- カメラが途中で切断: `Grabber.event_add_device_lost()` コールバックで検出する。コールバックは非GUIスレッドから呼ばれるため、`QTimer.singleShot(0, self._on_device_lost)` でGUIスレッドに処理を委譲する（カスタムQEventのType値衝突を避けるため、既存の `mainwindow.py` の `QApplication.postEvent` 方式ではなくQTimerを使用する）。`_on_device_lost()` では `stop_live_view()` を呼び出し、ステータスに `Camera disconnected` と表示する

### 4.4 ボード検出（FR-004, FR-005）

#### データフロー

- 入力: `numpy.ndarray` (BGR, H×W×3, dtype=uint8)
- 出力: `DetectionResult` データクラス

```python
@dataclass
class DetectionResult:
    success: bool                              # 検出成功/失敗
    image_points: numpy.ndarray | None         # shape=(N,1,2), dtype=float32
    object_points: numpy.ndarray | None        # shape=(N,1,3), dtype=float32
    charuco_ids: numpy.ndarray | None          # shape=(N,1), dtype=int32（ChArUco時のみ、checkerboard時はNone）
    num_corners: int                           # 検出コーナー数
    failure_reason: str                        # 失敗時の理由（成功時は空文字列）
```

#### 処理ロジック（ChArUcoモード）

OpenCV 4.7+の新API（`cv2.aruco.CharucoDetector`）を使用する。旧API（`interpolateCornersCharuco`）は非推奨のため使用しない。

1. BGR→グレースケール変換: `gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)`
2. `CharucoDetector.detectBoard()` でマーカー検出とChArUcoコーナー補間を一括実行:
   ```python
   # BoardDetector.__init__() で事前に作成・保持する
   dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
   board = cv2.aruco.CharucoBoard(
       (cols, rows), square_size_m, marker_size_m, dictionary
   )
   detector_params = cv2.aruco.CharucoParameters()
   charuco_detector = cv2.aruco.CharucoDetector(board, detector_params)

   # detect() で毎フレーム呼び出す
   charuco_corners, charuco_ids, marker_corners, marker_ids = charuco_detector.detectBoard(gray)
   ```
3. `charuco_corners` が `None` または空の場合: `success=False, failure_reason="No board detected"`
4. コーナー数 < 6 の場合: `success=False, failure_reason="Detected only {n} corners (minimum: 6)"`
5. コーナー数 >= 6 の場合: `success=True`。object_pointsは `board.getChessboardCorners()` から対応するIDのコーナーを抽出:
   ```python
   all_obj_points = board.getChessboardCorners()  # shape=(total_corners, 3), float32
   obj_points = all_obj_points[charuco_ids.flatten()]  # shape=(N, 3), float32
   obj_points = obj_points.reshape(-1, 1, 3)           # shape=(N, 1, 3)
   ```

**設計判断**: `board.getChessboardCorners()` は `cv2.aruco.CharucoBoard` の基底クラス `cv2.aruco.Board` に定義されたメソッドで、全ChArUcoコーナーの3D座標を返す。`charuco_ids` でインデックスして検出されたコーナーの座標を取得する。後続のfeat-009で `board.matchImagePoints()` への移行を検討する。

#### 処理ロジック（チェッカーボードモード）

1. BGR→グレースケール変換
2. チェッカーボード検出:
   ```python
   pattern_size = (cols - 1, rows - 1)  # 内部コーナー数
   flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
   ret, corners = cv2.findChessboardCorners(gray, pattern_size, flags=flags)
   ```
3. 検出失敗: `success=False, failure_reason="Checkerboard not detected"`
4. 検出成功: サブピクセル精細化:
   ```python
   criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
   corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
   ```
5. object_pointsを生成:
   ```python
   objp = numpy.zeros(((cols-1)*(rows-1), 1, 3), numpy.float32)
   objp[:, 0, :2] = numpy.mgrid[0:cols-1, 0:rows-1].T.reshape(-1, 2) * square_size_m
   ```

#### オーバーレイ描画

```python
def draw_overlay(self, frame_bgr: numpy.ndarray, result: DetectionResult) -> numpy.ndarray:
    """検出結果をフレームのコピー上に描画して返す。元のフレームは変更しない"""
    output = frame_bgr.copy()
    if not result.success:
        return output

    if self._board_type == "charuco":
        cv2.aruco.drawDetectedCornersCharuco(
            output, result.image_points, result.charuco_ids, (0, 255, 0)
        )
    else:
        cv2.drawChessboardCorners(
            output, (self._cols - 1, self._rows - 1),
            result.image_points, True
        )
    return output
```

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| グレースケール変換失敗 | `cv2.error` | `success=False, failure_reason="Gray conversion failed"` を返す | WARNING: `Gray conversion failed: {e}` |
| CharucoDetector.detectBoard()例外 | `cv2.error` | `success=False, failure_reason="ChArUco detection error"` を返す | WARNING: `detectBoard failed: {e}` |
| findChessboardCorners例外 | `cv2.error` | `success=False, failure_reason="Checkerboard detection error"` を返す | WARNING: `findChessboardCorners failed: {e}` |

#### 境界条件

- 入力画像が空（shape=(0,0,3)）: `success=False, failure_reason="Empty frame"` を即座に返す
- ボードが画像の端にかかっている: ChArUcoは部分検出可能（検出コーナー数が減る）。チェッカーボードは全コーナーが映っていないと検出失敗

**設計判断**: ChArUco vs チェッカーボード（デフォルト）
- 採用: ChArUcoをデフォルト（部分遮蔽に強い）
- 却下: チェッカーボードのみ（部分遮蔽時に検出全体が失敗する）
- 両方対応とし、ChArUcoを推奨デフォルトとする

### 4.5 ボード設定パネル（FR-006）

#### データフロー

- 入力: UIウィジェットの値変更シグナル
- 出力: `BoardDetector.reconfigure()` 呼び出し

#### 処理ロジック

1. ボードタイプ変更（QComboBox `currentIndexChanged`）:
   - `"ChArUco"` 選択: マーカーサイズ入力を有効化（`setEnabled(True)`）
   - `"Checkerboard"` 選択: マーカーサイズ入力を無効化（`setEnabled(False)`）
2. 任意のパラメータ変更時:
   - 現在の全パラメータ値を取得
   - `self._detector.reconfigure(board_type, cols, rows, square_mm, marker_mm)` を呼び出し
   - 次のフレームから新しい設定で検出が行われる

#### ボード設定のデフォルト値

| 項目 | デフォルト値 | 型 | 値域 | ウィジェット |
|------|-------------|-----|------|-------------|
| board_type | `"charuco"` | str | `"charuco"`, `"checkerboard"` | QComboBox |
| cols | 7 | int | 3〜20 | QSpinBox |
| rows | 5 | int | 3〜20 | QSpinBox |
| square_mm | 30.0 | float | 1.0〜200.0 | QDoubleSpinBox (step: 0.5) |
| marker_mm | 22.0 | float | 1.0〜square_mm未満 | QDoubleSpinBox (step: 0.5) |

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| marker_mm >= square_mm | 値の比較 | marker_mmを `max(1.0, square_mm - 1.0)` に自動補正。square_mmが2.0未満の場合はmarker_mmを1.0に設定 | INFO: `marker_mm adjusted to {v}` |

---

## 5. 状態遷移

### 5.1 CalibrationWidgetの状態遷移

```
[Idle] ──(カメラクリック)──> [Connecting]
[Connecting] ──(接続成功)──> [LiveView]
[Connecting] ──(接続失敗)──> [Idle]
[Connecting] ──(タブ離脱)──> [Idle]
[LiveView] ──(別カメラクリック)──> [Connecting]
[LiveView] ──(タブ離脱)──> [Idle]
[LiveView] ──(カメラ切断)──> [Idle]
```

| 状態 | 説明 | UI要素の状態 |
|------|------|-------------|
| Idle | カメラ未接続 | カメラ一覧: 有効、ライブビュー: 「カメラを選択してください」メッセージ表示、ボード設定: 有効、ステータス: `Ready` |
| Connecting | カメラ接続中 | カメラ一覧: 無効（一時的）、ライブビュー: 空、ステータス: `Connecting to {serial}...` |
| LiveView | ライブビュー表示中 | カメラ一覧: 有効、ライブビュー: 映像表示＋検出オーバーレイ、ボード設定: 有効、ステータス: 検出結果表示 |

不正な遷移要求（例: Idle状態でストリーム停止）はボタンのdisable状態で防止する。`stop_live_view()` はどの状態から呼ばれても安全に動作する（Grabberが `None` の場合は何もしない）。Connecting状態でタブ離脱した場合も `stop_live_view()` が呼ばれ、`stream_stop()` → `device_close()` の各ステップで例外をキャッチして安全に解放する。

---

## 6. ファイル・ディレクトリ設計

### 6.1 入出力ファイル

本案件では新規ファイルの入出力はない（ライブビュー＋検出のみ）。

読み取り専用で使用するファイル:
- `channels.json`（`QStandardPaths.AppDataLocation` 配下） - ChannelRegistryの保存データ

### 6.2 設定ファイル

本案件では設定ファイルを使用しない。ボード設定はGUI上で毎回指定する（永続化は後続案件のセッション機能で対応）。

---

## 7. インターフェース定義

### 7.1 ui_calibration.py

```python
class CalibrationWidget(QWidget):
    """Calibrationタブのメインウィジェット"""

    def __init__(self, registry: ChannelRegistry, resolver, parent=None) -> None:
        """
        Args:
            registry: チャンネル登録管理。MainWindowから渡される
            resolver: device_resolverモジュール。MainWindowから渡される
            parent: 親ウィジェット
        """

    # ── 公開メソッド（mainwindow.py から呼ばれる）──

    def on_tab_activated(self) -> None:
        """タブ選択時に呼ばれる。カメラ一覧を更新する"""

    def stop_live_view(self) -> None:
        """ライブビューを停止し、Grabberを解放する。
        タブ離脱時にmainwindow.pyから呼ばれる。
        Grabberが存在しない場合は何もしない（安全）"""

    # ── 内部メソッド ──

    def _create_ui(self) -> None:
        """UI構築。レイアウト:
        ┌──────────┬──────────────────┐
        │カメラ一覧 │   ライブビュー     │
        │(QList)   │   (QLabel)        │
        │          │                   │
        │──────────│                   │
        │ボード設定 │                   │
        │(設定パネル)│──────────────────│
        │          │  ステータス表示     │
        └──────────┴──────────────────┘
        左パネル幅: 固定200px
        ライブビュー: 残り領域を使用
        """

    def _populate_camera_list(self) -> None:
        """ChannelRegistryからカメラ一覧を構築する。
        接続中: クリック可能。未接続: グレーアウト"""

    def _on_camera_clicked(self, item: QListWidgetItem) -> None:
        """カメラクリック時。未接続カメラの場合は何もしない"""

    def _start_live_view(self, device_info: ic4.DeviceInfo) -> None:
        """指定デバイスのライブビューを開始する。
        既存のライブビューがあれば先に停止する"""

    def _on_frame_received(self, frame: numpy.ndarray) -> None:
        """QueueSinkListenerから呼ばれる。_latest_frame に保存"""

    def _process_latest_frame(self) -> None:
        """QTimerから呼ばれる。BayerGR8→BGR変換→検出→オーバーレイ→表示"""

    def _display_frame(self, bgr: numpy.ndarray) -> None:
        """BGR画像をQLabel上に表示。アスペクト比を保ってスケーリング"""

    def _update_detection_status(self, result: DetectionResult) -> None:
        """検出結果をステータスラベルに表示。
        成功時: 'Detected: {n}/{total} corners'
        失敗時: 'No board detected' または failure_reason"""

    def _on_board_config_changed(self) -> None:
        """ボード設定パネルの値が変更された時にBoardDetectorを再初期化"""
```

### 7.2 board_detector.py

```python
@dataclass
class DetectionResult:
    success: bool
    image_points: numpy.ndarray | None    # shape=(N,1,2), float32
    object_points: numpy.ndarray | None   # shape=(N,1,3), float32
    charuco_ids: numpy.ndarray | None     # shape=(N,1), int32（ChArUco時のみ）
    num_corners: int
    failure_reason: str                   # 成功時は空文字列


class BoardDetector:
    """ChArUco/チェッカーボード検出器"""

    def __init__(self, board_type: str = "charuco", cols: int = 7, rows: int = 5,
                 square_mm: float = 30.0, marker_mm: float = 22.0) -> None:
        """
        Args:
            board_type: "charuco" または "checkerboard"
            cols: ボードの列数
            rows: ボードの行数
            square_mm: チェッカーの一辺の長さ（mm）
            marker_mm: ArUcoマーカーの一辺の長さ（mm）。charuco時のみ使用

        内部状態:
            self._charuco_detector: cv2.aruco.CharucoDetector（charuco時のみ）
            self._board: cv2.aruco.CharucoBoard（charuco時のみ）
        """

    def detect(self, frame_bgr: numpy.ndarray) -> DetectionResult:
        """BGRフレームからボードを検出する。
        フレームが空の場合は success=False を返す"""

    def draw_overlay(self, frame_bgr: numpy.ndarray, result: DetectionResult) -> numpy.ndarray:
        """検出結果をフレームのコピー上に描画して返す。元のフレームは変更しない。
        result.success == False の場合は何も描画せずコピーを返す"""

    def reconfigure(self, board_type: str, cols: int, rows: int,
                    square_mm: float, marker_mm: float) -> None:
        """ボード設定を変更し、内部の検出器を再初期化する"""

    @property
    def max_corners(self) -> int:
        """現在のボード設定での最大コーナー数を返す。
        charuco: (cols-1) * (rows-1)
        checkerboard: (cols-1) * (rows-1)"""
```

---

## 8. ログ・デバッグ設計

### 8.1 ログレベル使い分け

| レベル | 使い分け | 例 |
|--------|---------|-----|
| DEBUG | フレームごとの検出結果 | `Detection: 24 corners in 15ms` |
| INFO | カメラ接続/切断、ボード設定変更 | `Camera 05520125 connected`, `Board config: charuco 7x5` |
| WARNING | 部分的な失敗 | `Bayer conversion failed`, `Camera 05520126 offline` |
| ERROR | 処理続行不能なエラー | `Failed to open camera`, `stream_setup failed` |

### 8.2 ログフォーマット

```python
import logging
logging.basicConfig(
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
```

各モジュールで `logger = logging.getLogger(__name__)` を使用する。

### 8.3 ログ出力ポイント

| モジュール | INFO | DEBUG |
|-----------|------|-------|
| ui_calibration | カメラ接続/切断、ボード設定変更 | フレーム処理時間 |
| board_detector | — | 検出結果（コーナー数、処理時間） |
