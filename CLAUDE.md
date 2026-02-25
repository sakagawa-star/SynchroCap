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
    └── investigation.md       # 調査メモ
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

なし

## 完了済み調査案件

- **inv-002**: `device_timestamp_ns` の意味の切り分け → `tools/timestamp_test.py` (ソフトウェアトリガー + TIMESTAMP_LATCH 方式)
