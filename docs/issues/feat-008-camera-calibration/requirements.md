# 要求仕様書: Camera Calibration - Live View with Board Detection

対象: feat-008
作成日: 2026-03-04
基準文書: `docs/REQUIREMENTS_STANDARD.md`

---

## 1. プロジェクト概要

### 1.1 何を作るか

SynchroCapに新規タブ（Tab5、index=4: Calibration）を追加し、カメラ内部パラメータキャリブレーションの第1段階として、カメラ選択・ライブビュー表示・ChArUcoボードのリアルタイム検出オーバーレイを実装する。

### 1.2 なぜ作るか

Pose2Simのキャリブレーションではボード検出の成功/失敗がリアルタイムでわからない。ライブビュー上にボード検出結果をリアルタイムで重畳表示することで、撮影品質を即座に確認できるようにする。本案件は後続のキャプチャ・キャリブレーション計算機能（feat-009〜013）の基盤となる。

### 1.3 誰が使うか

SynchroCapを使用してモーションキャプチャ用の同期録画を行うオペレーター。

### 1.4 どこで使うか

SynchroCapと同一のPC環境（Ubuntu Linux、micromamba SynchroCap環境）。カメラ（DFK33GR0234）が物理接続された状態で使用する。

---

## 2. 用語定義

| 用語 | 定義 |
|------|------|
| ChArUcoボード | チェッカーボードとArUcoマーカーを組み合わせたキャリブレーションパターン。部分遮蔽時もマーカー単位で検出可能 |
| ArUco辞書 | ArUcoマーカーのID体系。本機能では `DICT_6X6_250`（6x6ピクセル、250種類）を使用する |
| チェッカーボード | 白黒の格子パターン。全コーナーが同時に映っている必要がある |
| 検出オーバーレイ | ライブビュー映像上にボード検出結果（コーナー点）を重ねて描画すること |
| BayerGR8 | DFK33GR0234が出力するピクセルフォーマット。BGR画像に変換して使用する |

---

## 3. 機能要求一覧

### FR-001: Calibrationタブ追加

- **概要**: SynchroCapのメインウィンドウにTab5（index=4）「Calibration」を追加する
- **入力**: SynchroCapの起動
- **出力**: 既存タブ（Tab1〜Tab4、index=0〜3）の末尾にCalibrationタブが追加される
- **受け入れ基準**:
  - タブをクリックするとCalibration画面が表示される
  - 録画中（tabs_locked状態）はタブが無効化される
  - Calibrationタブへの遷移時に、CameraSettingsWidgetのプレビューとMultiViewWidgetのストリームが停止される
  - Calibrationタブから他タブへの遷移時に、Calibrationのライブビューが停止しGrabberが解放される
  - ウィンドウサイズの縮小を妨げないこと。低解像度ディスプレイでも全UI要素（ステータスラベル含む）が表示されること
- **異常系**:
  - CalibrationWidgetのインスタンス化に失敗した場合: タブを追加せず、SynchroCapの他機能は通常通り動作する

### FR-002: カメラ選択

- **概要**: ChannelRegistryに登録済みかつ物理接続されたカメラの一覧から、1台を選択する
- **入力**: ユーザーがタブ内のカメラ一覧からカメラをクリック
- **出力**: 選択したカメラのライブビューが開始される
- **前提条件**: Channel Managerでチャンネル登録が完了していること。キャリブレーション用のカメラ設定は事前にCamera Settingsタブ（Tab2）で行っておくこと
- **受け入れ基準**:
  - 登録済みかつ接続中のカメラが `Ch-{id} ({serial})` 形式で一覧に表示される
  - 未接続のカメラはグレーアウト表示される
  - クリックでライブビューが開始される
  - 以下のカメラ設定は変更しない（Camera Settingsタブのみが変更を許可されている）。カメラが現在保持している設定をそのまま使用する:
    - Resolution, PixelFormat, FrameRate, Trigger Interval
    - Auto White Balance, White Balance
    - Auto Exposure, Exposure
    - Auto Gain, Gain
  - 別のカメラをクリックすると、前のカメラを切断して新しいカメラに切り替わる
- **異常系**:
  - デバイスオープン失敗（`ic4.IC4Exception`）: ステータスバーにエラーメッセージを表示し、カメラ未選択状態に戻る。ライブビューは開始しない
  - 前カメラのstream_stop失敗: 例外を握りつぶし、新カメラの接続を続行する
- **境界条件**:
  - カメラ0台（全て未接続）: リストは表示されるが全てグレーアウト
  - ChannelRegistryが空: リストが空。ステータスに `No channels registered` と表示

### FR-003: ライブビュー表示

- **概要**: 選択したカメラの映像をリアルタイムで表示する
- **入力**: FR-002でのカメラ選択
- **出力**: カメラ映像がタブ内のQLabel上に表示される
- **受け入れ基準**:
  - ic4 QueueSinkでフレームを取得し、BGR8形式でQLabel上に表示される
  - QueueSinkは `accepted_pixel_formats=[ic4.PixelFormat.BGR8]` を指定し、IC4内部でBayer→BGR変換を行わせる（Camera Settingsで設定されたピクセルフォーマットに関わらず、IC4がBGR8に変換する）
  - フレームレートが10FPS以上で表示される
  - `QPixmap.scaled()` で `Qt.KeepAspectRatio` を使用し、QLabel領域内にアスペクト比を保ってスケーリングされる
  - ライブビュー領域に最小サイズ制約を設けない。ウィンドウ縮小に追従してライブビューも縮小される
- **異常系**:
  - stream_setup失敗（`ic4.IC4Exception`）: ステータスにエラー表示。ライブビューは開始しない
  - カメラが途中で切断: 最後のフレームが表示されたまま停止。ステータスに `Camera disconnected` と表示

### FR-004: ChArUcoボード検出オーバーレイ

- **概要**: ライブビュー上にChArUcoボードの検出結果をリアルタイムで重畳表示する
- **入力**: ライブビューの各フレーム
- **出力**:
  - 検出成功時: コーナー点を緑色のドットで描画。ステータスに検出コーナー数を表示（例: `Detected: 24/24 corners`）
  - 検出失敗時: オーバーレイなし。ステータスに `No board detected` と表示
- **受け入れ基準**: ボードが映っている場合に検出コーナーが緑色で描画され、映っていない場合はオーバーレイが消えること。検出コーナー数が6未満の場合は検出失敗として扱い、オーバーレイは表示しない。QTimerによるフレームスキップ方式（インターバル33ms）で、検出処理中に到着したフレームは最新フレームのみ保持し、検出処理が表示を停止させないこと
- **異常系**:
  - OpenCV検出処理で例外（`cv2.error`）が発生した場合: 該当フレームの検出をスキップし、ステータスにエラー理由を表示。ライブビュー自体は継続する

### FR-005: チェッカーボード検出オーバーレイ

- **概要**: FR-004と同様の機能をチェッカーボードに対して提供する
- **入力**: ライブビューの各フレーム
- **出力**: FR-004と同様（コーナー描画 + ステータス表示）
- **受け入れ基準**: チェッカーボードのコーナーが検出・描画されること。ChArUcoとはボード設定パネルで切り替える
- **異常系**: FR-004と同様（OpenCV例外時は該当フレームの検出をスキップ）

### FR-006: ボード設定パネル

- **概要**: ボードタイプとパラメータを設定するUIパネル
- **入力**: 以下のパラメータをGUI上で設定する
  - ボードタイプ: `ChArUco`（デフォルト）または `Checkerboard` のQComboBoxによる選択
  - 列数: QSpinBox（デフォルト: 5、範囲: 3〜20）
  - 行数: QSpinBox（デフォルト: 7、範囲: 3〜20）
  - チェッカーサイズ: QDoubleSpinBox（デフォルト: 30.0mm、範囲: 1.0〜200.0mm）
  - マーカーサイズ: QDoubleSpinBox（デフォルト: 22.0mm、範囲: 1.0〜チェッカーサイズ未満、ChArUco選択時のみ有効）
- **出力**: 設定変更時にボード検出器が再初期化され、新しい設定で検出が行われる
- **受け入れ基準**: 各パラメータが入力範囲内で設定でき、変更が即座にライブビューの検出に反映されること。Checkerboard選択時はマーカーサイズが無効化（disable）されること

---

## 4. 非機能要求

### 4.1 パフォーマンス

| 項目 | 基準 |
|------|------|
| ライブビュー表示レート | 10FPS以上 |
| ボード検出遅延 | フレーム取得から300ms以内にオーバーレイ描画が完了する |

### 4.2 信頼性

本案件はライブビュー表示のみで、データの永続化（キャプチャ・保存）を行わない。データ消失のリスクはない。カメラ切断やOpenCVエラーは各FRの異常系に定義した通り、ステータス表示とフレームスキップで対応する。

### 4.3 ログ出力

既存コードは `print()` を使用しているが、本モジュールでは `logging` モジュールを使用する。ログフォーマット: `[%(asctime)s] %(levelname)s %(name)s: %(message)s`。各モジュールで `logger = logging.getLogger(__name__)` を使用する。

### 4.4 対応環境

| 項目 | 値 |
|------|-----|
| OS | Ubuntu Linux |
| Python | 3.10 |
| パッケージ管理 | micromamba (SynchroCap環境) |
| カメラ | The Imaging Source DFK33GR0234 |
| GPU | 不要（キャリブレーション処理はCPUで実施） |

---

## 5. 状態遷移

CalibrationWidgetは以下の状態を持つ:

| 状態 | 説明 |
|------|------|
| Idle | カメラ未接続。カメラ一覧は操作可能、ライブビューは「カメラを選択してください」メッセージ表示 |
| Connecting | カメラ接続中。カメラ一覧は一時的に無効 |
| LiveView | ライブビュー表示中。検出オーバーレイとステータス表示が動作 |

遷移:
- `Idle → Connecting`: カメラクリック
- `Connecting → LiveView`: 接続成功
- `Connecting → Idle`: 接続失敗
- `LiveView → Connecting`: 別カメラクリック
- `LiveView → Idle`: タブ離脱
- `LiveView → Idle`: カメラ切断
- `Connecting → Idle`: タブ離脱（接続処理を中断し、Grabberを解放）

---

## 6. 制約条件

### 6.1 使用必須ライブラリ

| ライブラリ | 用途 |
|-----------|------|
| imagingcontrol4 (ic4) | カメラ制御（既存） |
| PySide6 | GUI（既存） |
| opencv-contrib-python | ChArUco/ArUco検出。`opencv-python` からの置き換え |
| numpy | 画像配列操作（既存） |

### 6.2 opencv-contrib-python の導入

`opencv-contrib-python` は `opencv-python` と競合する。既存の `opencv-python` をアンインストールしてから `opencv-contrib-python` をインストールする。ic4のPySide6統合には影響しない。バージョンは `>=4.9.0` を要求する（OpenCV 4.7+で `cv2.aruco.CharucoDetector` が導入、4.9以降で安定化）。

### 6.3 TECH_STACK.md の更新

実装時に `docs/TECH_STACK.md` を更新し、メインアプリケーションセクションに `opencv-contrib-python` を追加する。既存の `opencv-python`（ツール類セクション）との競合関係も記載する。

### 6.4 SynchroCapとの統合制約

- SynchroCapのメインウィンドウ（`mainwindow.py`）にTab5（index=4）を追加する
- 新規ファイルは `src/synchroCap/` 内に配置する（既存の `ui_*.py` と同じ場所）
- タブ切り替え時の排他制御は既存パターン（`onTabChanged()`）に準拠する
- 録画中のタブロックは既存の `set_tabs_locked()` を拡張して対応する

### 6.5 ic4パターンの準拠

SynchroCapで確立された以下のパターンに準拠する:
- `ic4.Library.init_context()` ブロック内で全操作を実行
- `QueueSinkListener` コールバックでバッファ割り当て・フレーム取得
- `Grabber.device_open()` → `Grabber.stream_setup(sink)` → `Grabber.stream_stop()` → `Grabber.device_close()` のライフサイクル

---

## 7. 優先順位

| 優先度 | 機能ID | 機能名 |
|--------|--------|--------|
| **Must** | FR-001 | Calibrationタブ追加 |
| **Must** | FR-002 | カメラ選択 |
| **Must** | FR-003 | ライブビュー表示 |
| **Must** | FR-004 | ChArUcoボード検出オーバーレイ |
| **Must** | FR-006 | ボード設定パネル |
| **Should** | FR-005 | チェッカーボード検出オーバーレイ |

### MVP範囲

FR-001〜FR-004, FR-006の5機能。チェッカーボード対応（FR-005）は余裕があれば実装する。

---

## 8. スコープ外

以下は本案件の対象外とする（後続案件で対応）:

- キャプチャ機能（手動/自動）
- キャリブレーション計算（cv2.calibrateCamera）
- 結果エクスポート（TOML/JSON）
- カバレッジヒートマップ
- 品質チェック（ブレ検出、サイズ判定）
- セッション保存/再開
- ChArUcoボード生成ツール
