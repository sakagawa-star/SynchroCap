# 要求仕様（最終更新版）
対象: ic4.demoapp/demoapp.py  
目的: PTP 同期 + Action Scheduler による複数カメラ同時録画（MP4 / ffmpeg）

> **注意（Codex 用）**
> - 本文は「要求仕様」のみを記述する。
> - 実装コードは一切含めない。
> - 仕様として未確定な事項のみ **「** 要調査 **」** と明記する。
> - 推測・補完は禁止。記載内容はコード事実またはユーザー確定仕様のみ。

---

## 1. 目的と成功条件

### 1.1 最終目的
PC を PTP グランドマスターとし、PTP 同期された複数カメラについて、  
Action Scheduler（Action0）を用いて FrameStart を同時に発火させ、  
各カメラの映像を録画する機能を GUI アプリ `ic4.demoapp/demoapp.py` に組み込む。

### 1.2 「同時開始」の定義
「同時開始」とは、カメラ側の FrameStart が Action Scheduler（Action0）によって発火し始めた時刻を指す。  
ホスト側の処理時刻やスレッド開始時刻は基準としない。

### 1.3 フェーズ範囲
本仕様は以下を対象とする。
- 録画開始スケジュール設定
- 録画開始（Action による FrameStart）
- 録画継続
- Duration に基づく自動停止

以下は本フェーズでは対象外とする。
- UI による明示的な停止操作
- 全停止ポリシーの高度化
- 録画成否判定
- 例外時リカバリ

---

## 2. 時刻同期・スケジューリング要件

### 2.1 PTP 構成
- PC が PTP グランドマスター
- カメラが PTP Slave
- 録画開始は Action Scheduler（Action0）で制御する

### 2.2 PTP Slave 待機
録画スケジュール設定前に、全カメラが PTP Slave 状態であることを確認する。  
待機方法・判定方法は `debug.demoapp/s10_rec4cams.py` と同一方式を踏襲する。

### 2.3 host–camera 時刻差分算出
`s10_rec4cams.py` と同一方式で以下を行う。
- TIMESTAMP_LATCH によりカメラ時刻をラッチ
- TIMESTAMP_LATCH_VALUE から camera_time_ns を取得
- host_ref_ns は time.time_ns() の前後平均
- delta_ns = camera_time_ns - host_ref_ns

### 2.4 相対秒から ACTION_SCHEDULER_TIME への写像
GUI 入力は相対秒のみとする。

- host_target_ns = time.time_ns() + start_delay_s * 1e9
- camera_target_ns = host_target_ns + delta_ns
- ACTION_SCHEDULER_TIME = camera_target_ns
- ACTION_SCHEDULER_COMMIT を実行

スケジュールが過去になっても補正は行わない。

### 2.5 Trigger 設定
各カメラで以下を設定する。
- TriggerSelector = FrameStart
- TriggerSource = Action0
- TriggerMode = On

---

## 3. 録画データ・保存要件

### 3.1 保存形式
保存形式は MP4。  
保存主体は ffmpeg とし、Python 側は raw フレーム bytes を ffmpeg の stdin に供給するのみ。

### 3.2 ffmpeg 入力形式
`s10_rec4cams.py` 準拠。
- rawvideo
- Pixel format: BayerGR8
- stdin 入力（-i -）
- arr.tobytes() を write

### 3.3 エンコード方式
- hevc_nvenc 固定
- エラー処理・フォールバックは行わない

### 3.4 保存先・命名規則
- 保存先ルート: captures/
- ディレクトリ: captures/YYYYMMDD-HHmmss/
- YYYYMMDD-HHmmss は **スケジュール確定時刻** 基準
- ファイル名: cam{serial}.mp4  
  例: cam05520125.mp4

---

## 4. GUI 要件

### 4.1 入力項目
- Start after（相対秒）
- Duration（秒）

出力パス指定 UI は存在しない。

### 4.2 操作
- Start によりスケジュール確定・録画開始
- UI 上で明示的な停止操作は行わない
- Duration 経過で自動停止

---

## 5. 実装構成要件

### 5.1 並列化モデル
1 カメラ = 1 スレッド（s10_rec4cams.py 準拠）。

### 5.2 録画スレッドの責務
- QueueSink からフレーム取得
- raw bytes 化
- ffmpeg stdin に write
- ffmpeg 異常終了検知時は早期停止

### 5.3 Stream setup と DEFER
- Display + QueueSink を同一 Grabber で併用する
- stream_setup 時に DEFER_ACQUISITION_START を使用
- acquisition_start() は録画スレッド内で呼ぶ

### 5.4 Duration 終了時の停止手順（確定）
Duration 経過による自動停止は、以下の順序で行う（`s10_rec4cams.py` 準拠）。

**録画スレッド側**
1. output_stream（= ffmpeg stdin）を flush
2. grabber.acquisition_stop()
3. grabber.stream_stop()
4. スレッド終了

**メイン（後始末）側**
5. ffmpeg_proc.stdin.close()（未 close の場合）
6. ffmpeg_proc.wait()
7. grabber.acquisition_stop()（保険的呼び出し）
8. grabber.stream_stop()（保険的呼び出し）
9. grabber.device_close()

### 5.5 GUI ライフサイクルの前提（確定）
- 録画中は、UI 操作によりタブ切替や表示ストリーム停止（slot_stop 相当の処理）が発生しない前提とする。
- 具体的には「録画中はタブ切替できないよう UI を固定する」機能を、次フェーズ以降の改修で追加する方針とする。
- 本フェーズの実装では、録画中に slot_start/slot_stop が再入して Grabber / Stream / Sink を破棄・再初期化しないことを前提に、
  Grabber / Stream / Sink / ffmpeg のライフサイクルは録画制御側が一元管理し、Duration 終了後にのみ停止・解放を行う。


---

## 6. 非要件
- raw ファイル保存
- mp4 以外の形式
- 出力パス指定 UI
- 録画品質切替
- 録画成否判定
- 高度なエラーハンドリング

---

## 7. 要調査項目一覧
1. GUI ライフサイクル（slot_start/stop、タブ切替）と録画スレッド／Grabber 管理の最終整合
