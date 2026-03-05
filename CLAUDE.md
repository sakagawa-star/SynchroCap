# CLAUDE.md

このファイルはClaude Codeがプロジェクトを理解するためのガイドです。

## プロジェクト概要

SynchroCapは、PTP (Precision Time Protocol, IEEE 1588) を使用して複数の産業用カメラを同期させ、フレーム単位で同期した動画録画を行うGUIアプリケーションです。

### 主な機能
- PTP同期による複数カメラの同時録画
- Action Scheduler (Action0) によるフレーム同期トリガー
- ffmpeg (hevc_nvenc) によるリアルタイムMP4エンコード
- マルチビューでの複数カメラプレビュー

## 技術スタック

- **言語**: Python 3.x
- **GUI**: PySide6 (Qt6)
- **カメラSDK**: imagingcontrol4 (IC4) - The Imaging Source社製産業用カメラ用
- **動画エンコード**: ffmpeg with hevc_nvenc (NVIDIA GPU)
- **同期方式**: PTP (IEEE 1588) + Action Scheduler

## ディレクトリ構成

```
SynchroCap/
├── src/
│   └── synchroCap/           # メインアプリケーション
│       ├── __init__.py
│       ├── main.py           # エントリーポイント
│       ├── mainwindow.py     # メインウィンドウ・タブ管理
│       ├── ui_channel_manager.py    # Tab1: チャンネル管理
│       ├── ui_camera_settings.py    # Tab2: 個別カメラ設定（読み書き）
│       ├── ui_multi_view.py         # Tab3: マルチビューUI・録画統合
│       ├── recording_controller.py  # 録画制御ロジック
│       ├── channel_registry.py      # チャンネル登録管理
│       └── device_resolver.py       # シリアル→DeviceInfo解決
├── dev/
│   └── tutorials/            # チュートリアル・サンプルコード
│       ├── 01_list_devices/
│       ├── 02_single_view/
│       └── ...
├── docs/
│   ├── BACKLOG.md            # 案件一覧
│   ├── CHANGELOG.md          # リリース履歴
│   ├── architecture.md       # アーキテクチャ概要
│   ├── requirements.md       # 要件定義
│   ├── feature_design.md     # 機能設計書
│   └── issues/               # 案件フォルダ
│       └── bug-001-.../      # 個別案件
├── tests/                    # テストコード
│   └── results/              # テスト結果保存先
└── output/                   # 録画出力先
```

## アプリケーション起動方法

```bash
cd src/synchroCap
python main.py
```

## コーディング規約

- **命名規則**:
  - クラス名: PascalCase (例: `RecordingController`)
  - 関数・メソッド: snake_case (例: `start_recording`)
  - プライベートメソッド: `_` プレフィックス (例: `_on_frame_received`)
  - 定数: UPPER_SNAKE_CASE (例: `ACTION_SCHEDULER_INTERVAL`)

- **型ヒント**: 関数シグネチャに型ヒントを使用

- **Qt シグナル/スロット**: PySide6のSignal/Slotパターンを使用

- **カメラ操作**: IC4 SDKのcontext managerパターンを活用
  ```python
  with ic4.Library.init_context():
      # カメラ操作
  ```

## 重要な設計判断

- **録画中のプレビュー**: 録画中はプレビューを停止（シンプルさ優先）
- **1カメラ = 1スレッド**: 録画は各カメラごとに独立したスレッドで実行
- **PTP Slave必須**: 全カメラがPTP Slaveになることが録画開始の前提条件
- **DEFER_ACQUISITION_START**: 複数カメラの同時開始に必須

## 開発方針

- **シンプルな機能を一つずつ作り、積み重ねて目的を達成する**
- 大きな機能を一度に作らない。小さく作って動作確認し、次の機能へ進む

### 機能ごとの開発フロー

各機能について、以下のフローを**厳守**する。**planモードは使わない**（通常モードで調査・計画を行う）。

1. **案件作成** → `docs/issues/{type}-{number}-{slug}/` フォルダを作成し、`BACKLOG.md` に追加する
2. **調査・計画** → 通常モードで既存コードを調査し、要求仕様書（`docs/REQUIREMENTS_STANDARD.md` 準拠）と機能設計書（`docs/DESIGN_STANDARD.md` 準拠）を作成する
3. **ドキュメント保存** → 要求仕様書を `docs/issues/{案件フォルダ}/requirements.md`、機能設計書を `docs/issues/{案件フォルダ}/design.md` にファイル保存する。**保存が完了するまで実装に進んではならない**
4. **レビュー（Subagent + 人）** → 保存されたドキュメントをSubagent（Agentツール）でレビューする。ユーザーも同時にレビューする。レビュー実行時は `docs/REVIEW_CRITERIA.md` の基準に従うこと
5. **修正（必要な場合）** → レビューで問題があれば、再調査してドキュメントを更新する。**ステップ2〜4を問題がなくなるまで繰り返す**
6. **引き継ぎ・/clear** → CLAUDE.mdの「現在進行中の案件」セクションを更新し、実装セッションに必要な情報を整える。その後ユーザーが `/clear` を実行
7. **実装** → ドキュメント（要求仕様書・機能設計書・CLAUDE.md）を読んで実装

### ドキュメント作成ルール

- **実装前に必ず「要求仕様書」と「機能設計書」を作成し、案件フォルダにファイル保存すること**
- ドキュメントが保存されていない場合は、**実装を中止**する
- 要求仕様書：何を達成すべきか（入出力、制約、品質基準）。作成時は `docs/REQUIREMENTS_STANDARD.md` の基準に従うこと
- 機能設計書：どう実現するか（モジュール構成、アルゴリズム、データ構造）。作成時は `docs/DESIGN_STANDARD.md` の基準に従うこと
- ドキュメントは `docs/issues/{案件フォルダ}/` に置く（`requirements.md`, `design.md`）
- **/clear 後でも実装がスムーズにできるよう、必要な情報を全て記述する**
- 暗黙知に頼らず、**自己完結したドキュメント**にする（前の会話コンテキストがなくても実装できること）
- レビュー実行時は `docs/REVIEW_CRITERIA.md` の基準に従うこと
- ライブラリの追加・変更・削除を行った場合は `docs/TECH_STACK.md` も更新すること
- 新規ライブラリ導入時は用途・選定理由・バージョンを `TECH_STACK.md` に追記すること

### テスト

- テストは `tests/` ディレクトリに置く
- **テスト実行はSubagent（Agentツール）を使う**
- テスト実行コマンド: `micromamba run -n SynchroCap pytest -v`
- **テスト結果は `tests/results/` にファイル保存する**
  - ファイル名：`{type}-{number}_test_result.txt`（例：`feat-008_test_result.txt`）
  - 内容：pytest の `-v` 出力をそのまま保存する

## ドキュメント管理ルール

### 案件管理

- **BACKLOG.md**: 全案件（バグ・機能追加）の一覧とステータス
- **CHANGELOG.md**: リリース履歴
- **issues/**: 個別案件のフォルダ

### 案件フォルダ構成

```
docs/issues/
└── {type}-{number}-{slug}/    # 例: bug-001-xxx, feat-002-yyy
    ├── README.md              # 概要、ステータス、再現手順
    ├── investigation.md       # 調査メモ
    ├── requirements.md        # 要求仕様書（機能追加時）
    └── design.md              # 機能設計書（機能追加時）
```

### 運用フロー

1. **新規案件**: issues/に案件フォルダを作成、BACKLOG.mdに追加
2. **調査中**: investigation.mdに調査メモを記録
3. **完了時**:
   - README.mdのStatusをClosedに変更
   - BACKLOG.mdのステータスを更新
   - CHANGELOG.mdに完了内容を記録

### 命名規則

- フォルダ名は英語で統一（例: `bug-001-cannot-restart-recording`）
- 案件フォルダは完了後も削除・移動しない

## 現在進行中の案件

### feat-008: Camera Calibration - Live View with Board Detection

- **ステータス**: 初回実装済み → **不具合修正中**
- **次のアクション**: ドキュメント（requirements.md, design.md）を読み、以下の未修正の不具合を修正する
- **ドキュメント**: `docs/issues/feat-008-camera-calibration/`
  - `requirements.md` - 要求仕様書（不具合対応の更新反映済み・レビュー済み）
  - `design.md` - 機能設計書（不具合対応の更新反映済み・レビュー済み）

#### 実装済みファイル（初回実装完了）
- `src/synchroCap/board_detector.py` — 新規作成済み（変更不要）
- `src/synchroCap/ui_calibration.py` — 新規作成済み（**要修正**）
- `src/synchroCap/mainwindow.py` — タブ追加・切り替え制御（変更済み、追加修正不要）
- `docs/TECH_STACK.md` — 更新済み

#### 未修正の不具合（2件）
1. **ステータスラベルが見切れる + ウィンドウ縮小不可**: `ui_calibration.py` の `_live_view_label.setMinimumSize(320, 240)` が原因。ドキュメント更新済み（FR-001, FR-003, design.md _create_ui）。修正内容: `setMinimumSize()` を削除し、ステータスラベルに `setFixedHeight(24)` + `stretch=0` を設定する
2. **ステータスラベルの `setMaximumHeight` → `setFixedHeight` 変更**: ルール違反で先行修正済み（コード上は既に `setFixedHeight(24)` + `stretch=0` に変更されている）。ドキュメントとの整合性は確認済み

#### 修正時の注意事項
- `ui_calibration.py` の修正箇所: `self._live_view_label.setMinimumSize(320, 240)` の行を削除するのみ
- ボード検出機能の動作確認がまだ（ステータスラベルが見えなかったため未確認）。修正後に実機テストで確認すること
- **カメラ設定変更禁止ルール**: Calibrationタブはカメラ設定を変更しない（Resolution, PixelFormat, FrameRate, Trigger Interval, Auto White Balance, White Balance, Auto Exposure, Exposure, Auto Gain, Gain）。設定変更はCamera Settingsタブのみが許可される

#### その他
- **追加ライブラリ**: `opencv-contrib-python >=4.9.0`（`opencv-python`と置き換え）→ TECH_STACK.md更新済み
- **タブ番号規約**: プロジェクト全体で1-indexed（Tab1=Channel Manager, Tab2=Camera Settings, Tab3=Multi View, Tab4=Camera Settings Viewer, Tab5=Calibration）。ソースコードの変数名・ログメッセージもこの規約に従う

### カメラキャリブレーション全体計画（feat-008〜013）

```
feat-008: ライブビュー + ボード検出 (Tab5追加) ← 今ここ
    │
    ▼
feat-009: 手動キャプチャ + キャリブレーション計算
    ├──> feat-010: エクスポート (TOML/JSON)
    ├──> feat-011: 自動キャプチャ + 品質チェック
    ├──> feat-012: カバレッジヒートマップ + ガイド
    └──> feat-013: セッション保存/再開
```

- feat-009〜013のドキュメントはfeat-008完了後に順次作成する
- 全モジュールは `src/synchroCap/` 内に配置（SynchroCapの一部として統合）
- 草案の全体像: `/home/sakagawa/Downloads/synchrocap_calibration_design.md`

## 完了済み調査案件

- **inv-002**: `device_timestamp_ns` の意味の切り分け → `tools/timestamp_test.py` (ソフトウェアトリガー + TIMESTAMP_LATCH 方式)
