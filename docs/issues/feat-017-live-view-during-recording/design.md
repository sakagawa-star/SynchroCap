# feat-017: Live View During Recording 機能設計書

## 1. 対応要求マッピング

| 要求ID | 設計セクション |
|--------|---------------|
| FR-001 | 4.1 RecordingSlot に display 追加, 4.2 _setup_recording() 変更 |
| FR-002 | 4.3 録画終了時のプレビュー再開 |
| FR-003 | 4.4 既存録画フローへの影響なし確認 |

## 2. システム構成

### 変更対象ファイル

| ファイル | 変更内容 |
|----------|----------|
| `src/synchroCap/recording_controller.py` | `RecordingSlot` に `display` フィールド追加、`_setup_recording()` で `display` を `stream_setup()` に渡す |
| `src/synchroCap/ui_multi_view.py` | `RecordingSlot` 構築時に `display` を渡す |

### 変更不要ファイル

| ファイル | 理由 |
|----------|------|
| `src/synchroCap/mainwindow.py` | Tab3 の内部変更であり、タブ管理に影響しない |
| 録画ワーカー (`_worker_mp4`, `_worker_raw`) | フレーム取得は QueueSink 経由であり、Display 追加はワーカーロジックに無関係 |

## 3. 技術スタック

変更なし。IC4 SDK の既存 API（`stream_setup(sink, display, setup_option)`）を使用。

## 4. 各機能の詳細設計

### 4.1 RecordingSlot に display フィールド追加（FR-001）

#### データフロー

- **入力**: `ui_multi_view.py` の slot 辞書内の `display` オブジェクト（`ic4.Display` または `None`）
- **出力**: `RecordingSlot.display` フィールドとして保持

#### 処理ロジック

`recording_controller.py` の `RecordingSlot` データクラスに `display` フィールドを追加:

```python
@dataclass
class RecordingSlot:
    serial: str
    grabber: ic4.Grabber
    display: Optional[Any] = None  # ic4.Display (プレビュー用)
    recording_sink: Optional[ic4.QueueSink] = None
    # ... 既存フィールドは変更なし
```

`display` の型は `Optional[Any]` とする。理由: `ic4.Display` は `ic4.pyside6.DisplayWidget.as_display()` で返される内部型であり、型ヒントとして直接参照するとインポートが複雑になるため。

#### prepare() メソッドでの display 取得

`prepare()` メソッド内の `RecordingSlot` 構築箇所で、slot 辞書から `display` を取り出す:

```python
recording_slot = RecordingSlot(
    serial=str(serial),
    grabber=grabber,
    display=slot.get("display"),  # 追加
    trigger_interval_fps=float(trigger_interval_fps),
)
```

`slot.get("display")` は `ui_multi_view.py` の slot 辞書から取得。`as_display()` が失敗した場合は `None` が入っている（既存コード ui_multi_view.py:161-165）。

### 4.2 _setup_recording() で display を stream_setup() に渡す（FR-001）

#### 処理ロジック

現在の実装（変更前、recording_controller.py:525-529）:
```python
slot.grabber.stream_setup(
    slot.recording_sink,
    setup_option=ic4.StreamSetupOption.DEFER_ACQUISITION_START,
)
```

変更後:
```python
slot.grabber.stream_setup(
    slot.recording_sink,
    display=slot.display,
    setup_option=ic4.StreamSetupOption.DEFER_ACQUISITION_START,
)
```

`slot.display` が `None` の場合、IC4 SDK は display なしで動作する（既存の挙動と同一）。

#### stream_setup() のシグネチャ確認

IC4 SDK の `Grabber.stream_setup()` のシグネチャを `inspect.signature()` で確認済み:

```python
stream_setup(
    self,
    sink: Optional[Sink] = None,          # POSITIONAL_OR_KEYWORD, default=None
    display: Optional[Display] = None,    # POSITIONAL_OR_KEYWORD, default=None
    setup_option: StreamSetupOption = ACQUISITION_START,  # POSITIONAL_OR_KEYWORD
) -> None
```

- 全引数が `POSITIONAL_OR_KEYWORD` であり、位置引数・キーワード引数どちらでも渡せる
- `display` のデフォルトは `None` であり、`display=None` を渡しても省略しても同一の挙動
- 本設計では `display=slot.display` をキーワード引数として渡す。理由: 第1引数 `sink` と第3引数 `setup_option` の間に挟むため、キーワード指定のほうが可読性が高く、引数順序の誤りを防げる

#### stream_stop() 後の display 再利用の確認

`stream_stop()` 後に同じ display オブジェクトを次の `stream_setup()` で再接続できることは、既存コードで実証済み:

- `ui_multi_view.py:305` の `_slot_start()` で `_slot_stop()` を呼び出し（内部で `stream_stop()` を実行）、直後に同じ `display` で `stream_setup(sink, display)` を再実行している（行333）
- `resume_selected()` でも全スロットに対して `_slot_stop()` → `_slot_start()` を実行しており、display は再利用される

したがって、録画開始時の `stream_stop()` → `stream_setup(recording_sink, display=slot.display)` の流れでも display は正常に再接続される。

#### エラーハンドリング

- `stream_setup()` の既存 try/except（recording_controller.py:531-533）がそのまま有効。display 引数の追加で新たな例外型は発生しない
- `display` が `None` でも `stream_setup()` は正常動作（デフォルト値が `None` であるため既存の挙動と同一）
- 一部スロットのみ `display` が `None` の場合（`as_display()` が失敗したスロット）、そのスロットは display なしで録画される（他スロットには影響しない）

### 4.3 録画終了時のプレビュー再開（FR-002）

#### 現在の動作

録画終了時、`_on_recording_finished()` → `resume_selected()` が呼ばれ、全スロットで:
1. `_slot_stop()` — 既存ストリーム停止
2. `_slot_start()` — `grabber.device_open()` + `grabber.stream_setup(sink, display)` で再接続

#### 変更の必要性

**変更不要**。

理由: 録画終了後、`recording_controller.py` の `_cleanup()` メソッドで各スロットの `stream_stop()` が呼ばれる。その後 `ui_multi_view.py` の `resume_selected()` → `_slot_start()` が実行され、プレビュー用の sink + display で `stream_setup()` が再実行される。この既存フローは変更なしで正常動作する。

### 4.4 既存録画フローへの影響なし確認（FR-003）

#### フレーム取得への影響

録画ワーカー（`_worker_mp4`, `_worker_raw`）は `recording_sink.try_pop_output_buffer()` でフレームを取得する。`stream_setup()` に display を追加しても、sink へのフレーム供給は変わらない（IC4 SDK が sink と display に独立してフレームを配信する）。

#### Action Scheduler への影響

`DEFER_ACQUISITION_START` オプションの動作は display の有無に依存しない。`acquisition_start()` は Action Scheduler の設定後に呼ばれ、この順序は変更されない。

#### CSV タイムスタンプ記録への影響

CSV 記録は `_worker_mp4` / `_worker_raw` 内で `buf.header.device_timestamp_ns` から取得する。display の追加はバッファヘッダーに影響しない。

## 5. ファイル・ディレクトリ設計

変更なし。

## 6. インターフェース定義

### RecordingSlot（変更後）

```python
@dataclass
class RecordingSlot:
    serial: str
    grabber: ic4.Grabber
    display: Optional[Any] = None          # 追加: ic4.Display (プレビュー用)
    recording_sink: Optional[ic4.QueueSink] = None
    recording_listener: Optional[ic4.QueueSinkListener] = None
    ffmpeg_proc: Optional[subprocess.Popen] = None
    output_path: Optional[Path] = None
    frame_count: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    trigger_interval_fps: float = 50.0
    delta_ns: int = 0
    csv_path: Optional[Path] = None
    csv_file: Optional[TextIO] = None
    csv_writer: Optional[Any] = None
    csv_buffer: List[List] = field(default_factory=list)
    raw_file: Optional[BinaryIO] = None
    raw_file_start_frame: int = 0
    raw_files_created: List[str] = field(default_factory=list)
```

### prepare() の slot 辞書要件（変更後）

slot 辞書に以下のキーが必要（追加分）:

| キー | 型 | 必須 | 説明 |
|------|------|------|------|
| `display` | `ic4.Display` or `None` | 任意 | DisplayWidget から取得。なければ `None`（既存動作） |

既存のキー（`grabber`, `trigger_interval_fps`）は変更なし。

## 7. ログ・デバッグ設計

変更なし。既存のログ出力がそのまま有効。

## 8. テスト

本案件はハードウェア（カメラ + IC4 SDK）に依存するため、自動テストは作成しない。手動テストで以下を確認する:

1. 録画中にライブビューが表示されること
2. 録画ファイル（MP4/Raw）が正常に出力されること
3. 録画開始・停止時に映像が一時的に途切れ、その後復帰すること
4. アプリがクラッシュしないこと

## 9. 設計判断

### 採用案: stream_setup() に display を渡す

IC4 SDK の既存 API を使い、`stream_setup(sink, display, setup_option)` の display 引数に既存の Display オブジェクトを渡す。変更は2ファイル・3行のみ。

### 却下案: 録画スレッド内でフレームを手動描画

録画ワーカーで取得したフレームを手動で QImage に変換し、QLabel に表示する方式。実装が複雑で、Bayer 変換を自前で行う必要がある。IC4 SDK の DisplayWidget が既にこの機能を提供しているため不要。

### 却下案: 2つの Sink を並列接続

プレビュー用 Sink と録画用 Sink を同時に接続する方式。IC4 SDK の `stream_setup()` は単一の Sink しか受け付けないため不可能。
