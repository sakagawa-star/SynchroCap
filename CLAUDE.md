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
│       ├── mainwindow.py     # メインウィンドウ
│       ├── ui_multi_view.py  # マルチビューUI・録画統合
│       ├── recording_controller.py  # 録画制御ロジック
│       └── ...
├── dev/
│   └── tutorials/            # チュートリアル・サンプルコード
│       ├── 01_list_devices/
│       ├── 02_single_view/
│       └── ...
├── docs/
│   ├── requirements.md       # 要件定義
│   ├── feature_design.md     # 機能設計書
│   └── investigation.md      # 調査記録
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
