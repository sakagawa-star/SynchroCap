# 要調査事項

基準文書: `requirements.md`, `feature_design.md`

---

## 未解決

（なし - 全項目解決済み）

---

## 解決済み

### INV-007: ffmpeg起動失敗時の挙動
- **状態**: 解決（ユーザー指示）
- **関連**: feature_design.md §9
- **背景**: 該当カメラをスキップするか、全体を中止するか
- **調査方法**:
  - [x] ユーザー指示
- **結果**:

  **結論: 全体を中止**

  ffmpeg起動に失敗した場合:
  1. 全カメラの録画準備を中止
  2. エラーメッセージを表示
  3. IDLE 状態に戻る

  **理由**: 同期録画の目的上、一部カメラのみの録画は意味をなさないため。

- **反映先**: feature_design.md §9 エラーハンドリング方針に追記

---

### INV-008: slot_start/slot_stopとの干渉
- **状態**: 解決（ユーザー指示）
- **関連**: feature_design.md §11.1, requirements.md §5.5
- **背景**: 録画中にユーザーがコンボボックスでチャンネル変更した場合の挙動。現設計では「録画中は変更不可」を前提
- **調査方法**:
  - [x] ユーザー指示
- **結果**:

  **結論: 録画中はチャンネル変更不可を前提とする**

  1. **今回の改修**: 録画中にチャンネル変更が行われないことを前提として実装
  2. **次回以降の改修**: GUIで録画中はコンボボックスを無効化する実装を追加予定

  **今回の実装方針**:
  - 録画中の slot_start/slot_stop 呼び出しは想定しない
  - タブロック機能（既存）により、他タブへの遷移は防止される

- **反映先**: feature_design.md §5.5, §11.1 に前提条件として明記

---

### INV-001: 録画中のプレビュー継続可否
- **状態**: 解決
- **関連**: feature_design.md §11.2
- **背景**: Display + 録画用QueueSinkを同一Grabberで併用する設計だが、プレビューが正常に継続するか不明
- **調査方法**:
  - [x] 参照実装(s10_rec4cams.py)の確認
  - [x] IC4 SDK コード解析
  - [ ] 実機テスト（未実施だが、コード解析で十分な根拠あり）
- **結果**:

  **結論: 技術的に可能。ただし実装上の制約あり。**

  1. **IC4 SDKの標準パターン**: `grabber.stream_setup(sink, display)` で両方を同時に渡すことが可能
     - 現在の `ui_multi_view.py:290` で既に使用中
     - `mainwindow.py:361` でも同様のパターン

  2. **動作原理**: Grabberからフレームが Display（描画）と QueueSink（バッファリング）の両方に並行して流れる

  3. **実装上の制約**:
     - 録画開始時に `stream_setup()` を再呼び出しする場合、先に `stream_stop()` が必要
     - `stream_stop()` 〜 `stream_setup()` の間、一時的にプレビューが途切れる
     - 代替案: 最初から DEFER_ACQUISITION_START で setup し、プレビュー用に別途 start するアーキテクチャも検討可能

  4. **推奨方針**:
     - 録画開始時に一瞬プレビューが途切れることを許容する（シンプルな実装）
     - または、録画中はプレビューを停止する（最もシンプル）

  5. **最終決定（ユーザー承認済み）**: 今回の改修では **録画中プレビュー停止** を採用。次回改修で録画プレビュー実装を検討。

- **反映先**: feature_design.md §11.2 に制約を追記

---

### INV-002: 既存sink再利用 vs 新規sink作成
- **状態**: 解決
- **関連**: feature_design.md §11.2
- **背景**: 現在の各スロットには既にプレビュー用sinkがある。録画用に別sinkを作成するか、既存を流用するか
- **調査方法**:
  - [x] ui_multi_view.py の現在のsink構成確認
  - [x] IC4 SDK の複数sink対応確認
  - [x] 参照実装の方式確認
- **結果**:

  **結論: 新規sink作成（ユーザー調査結果と一致）**

  1. **参照実装の方式** (`s10_rec4cams.py:359-369`):
     ```python
     def allocate_queue_sink(...):
         listener = _RawQueueSinkListener()
         sink = ic4.QueueSink(listener, accepted_pixel_formats=[ic4.PixelFormat.BayerGR8])
         grabber.stream_setup(sink, setup_option=ic4.StreamSetupOption.DEFER_ACQUISITION_START)
         sink.alloc_and_queue_buffers(500)
         return sink, listener
     ```
     録画セッションごとに専用sinkを作成している。

  2. **新規sink作成の理由**:
     - **分離**: 録画sink操作がプレビューsink操作に干渉しない
     - **異なるリスナー**: プレビューは即座にpop、録画はフレーム処理が必要
     - **バッファ管理**: 録画には大量のバッファ（500）が必要
     - **状態管理**: 録画sinkは独立して開始/停止可能

  3. **IC4 SDKの対応**: GenTLベースで複数sink対応（設計上サポート）

  4. **現在の構成** (`ui_multi_view.py:143-145`):
     ```python
     grabber = ic4.Grabber()
     listener = _SlotListener()
     sink = ic4.QueueSink(listener)  # プレビュー用
     ```
     各スロットに1つのプレビュー用sinkがある。

- **反映先**: feature_design.md §3.2 RecordingSlot に recording_sink を追加

---

### INV-003: stream_setup再呼び出しの可否
- **状態**: 解決
- **関連**: feature_design.md §11.2
- **背景**: プレビュー中のGrabberに対してDEFER_ACQUISITION_START付きで再setupできるか、一度stream_stopが必要か
- **調査方法**:
  - [x] IC4 SDK コード解析
  - [x] 参照実装の方式確認
- **結果**:

  **結論: stream_setup再呼び出しは可能。ただし先にstream_stop()が必要。**

  **Part A: 再呼び出しの可否**

  1. **実例** (`ui_camera_settings.py:386-392`):
     チャンネル切替時に `stream_setup()` を再呼び出ししている。

  2. **手順**:
     ```python
     if grabber.is_streaming:
         grabber.stream_stop()  # 先に停止
     # その後 stream_setup() 呼び出し可能
     ```

  **Part B: DEFER_ACQUISITION_STARTの目的**

  1. **目的**: 複数カメラ同期のため、自動的なacquisition開始を遅延する

  2. **使用シーケンス**:
     ```
     1. stream_setup(sink, DEFER_ACQUISITION_START)  # ストリーム準備、acquisition未開始
     2. ACTION_SCHEDULER_TIME 設定                   # 各カメラのトリガー時刻設定
     3. ACTION_SCHEDULER_COMMIT                      # スケジュール確定
     4. acquisition_start()                          # 手動でacquisition開始
     5. [スケジュール時刻にAction0発火]
     ```

  3. **DEFERを使わない場合**: `stream_setup()` が自動的に `acquisition_start()` を呼び、各カメラがバラバラに取得開始してしまう

  4. **全参照実装で使用**: s04〜s10_rec4cams.py, s01_mkraw125.py 等、同期録画では必ず使用

- **反映先**: feature_design.md §4.1 シーケンス図、§5.1 データフロー

---

### INV-004: カメラパラメータの取得元
- **状態**: 解決（ユーザー指示）
- **関連**: feature_design.md §12.1
- **背景**: WIDTH/HEIGHT/FRAME_RATEを固定値(1920x1080, 30fps)とするか、カメラ現在値を動的取得するか
- **調査方法**:
  - [x] ユーザー指示
- **結果**:

  **結論: カメラ現在値を動的取得**

  録画開始時に各カメラの `device_property_map` から以下を取得:
  - `WIDTH`: `ic4.PropId.WIDTH`
  - `HEIGHT`: `ic4.PropId.HEIGHT`
  - `FRAME_RATE`: `ic4.PropId.ACQUISITION_FRAME_RATE`
  - `PIXEL_FORMAT`: 固定 `BayerGR8`（要求仕様より）

  **実装方針**:
  ```python
  width = grabber.device_property_map.get_value_int(ic4.PropId.WIDTH)
  height = grabber.device_property_map.get_value_int(ic4.PropId.HEIGHT)
  fps = grabber.device_property_map.get_value_float(ic4.PropId.ACQUISITION_FRAME_RATE)
  ```

- **反映先**: feature_design.md §12.1 を動的取得に変更

---

### INV-005: ACTION_SCHEDULER_INTERVALの必要性
- **状態**: 解決
- **関連**: feature_design.md §7.2
- **背景**: 参照実装では設定しているが、要求仕様では明記なし。連続FrameStartに必要か
- **調査方法**:
  - [x] 参照実装(s10_rec4cams.py)の該当箇所確認
  - [x] IC4_ActionScheduler.py のコメント確認
- **結果**:

  **結論: 連続フレーム取得に必須**

  1. **ACTION_SCHEDULER_INTERVALの役割**:
     - **ACTION_SCHEDULER_TIME**: 最初のAction0発火時刻（単位: ns）
     - **ACTION_SCHEDULER_INTERVAL**: 以後の発火間隔（単位: µs）

  2. **動作原理** (`IC4_ActionScheduler.py:180`):
     > "未来の開始時刻（単位：ns）"と"発火間隔（単位：µs）"をセットし、COMMITでアクションスケジューラを開始。

  3. **計算式** (`s10_rec4cams.py:314`):
     ```python
     interval_us = round(1_000_000 / fps)
     # fps=30 → interval_us=33333 µs ≈ 33.3 ms
     ```

  4. **設定しない場合**: 最初の1フレームのみ取得され、以後のフレームが取得されない可能性がある

  5. **全参照実装で使用**: s04〜s10, IC4_ActionScheduler.py, 06_encode_single/s03 等

- **反映先**: feature_design.md §7.2 に説明を追記（必須パラメータとして明記）

---

### INV-006: 一部カメラのみPTP Slave失敗時の挙動
- **状態**: 解決（ユーザー指示）
- **関連**: feature_design.md §9
- **背景**: 全カメラがSlave必須か、成功したカメラのみで録画続行するか
- **調査方法**:
  - [x] ユーザー指示
- **結果**:

  **結論: 全カメラSlave必須。失敗時は録画中止。**

  **エラー処理方針**:
  1. PTP Slave待機中にタイムアウト（30秒）した場合
  2. エラーメッセージをGUIに表示
  3. 録画を開始せずに IDLE 状態に戻る

  **エラーメッセージ例**:
  ```
  "PTP synchronization failed: Not all cameras reached Slave state within timeout.
   Slave: 3, Master: 0, Other: 1"
  ```

  **UI表現**:
  - Status ラベルにエラー表示
  - Start ボタンを再度有効化（リトライ可能）

- **反映先**: feature_design.md §9 エラーハンドリング方針に追記

---

## 調査優先度（参考）

**全項目解決済み**

---

## 設計への影響サマリ

| 項目 | 結論 | 設計への影響 |
|------|------|-------------|
| INV-001 | 録画中プレビュー停止（今回） | 録画開始時に stream_stop()、録画終了時に再開 |
| INV-002 | 新規sink作成 | RecordingSlot に recording_sink, recording_listener を追加 |
| INV-003 | stream_stop() → stream_setup(DEFER) → acquisition_start() | 録画開始シーケンスを明確化 |
| INV-004 | カメラ現在値を動的取得 | §12.1 を固定値から動的取得に変更 |
| INV-005 | ACTION_SCHEDULER_INTERVAL は必須 | §7.2 に必須パラメータとして明記 |
| INV-006 | 全カメラSlave必須、失敗時は録画中止 | §9 にエラー処理方針を追記 |
| INV-007 | ffmpeg起動失敗時は全体中止 | §9 にエラー処理方針を追記 |
| INV-008 | 録画中チャンネル変更不可を前提 | §5.5, §11.1 に前提条件として明記 |
