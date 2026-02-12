# SynchroCap

PTP (Precision Time Protocol, IEEE 1588) を使用して複数の産業用カメラを同期させ、フレーム単位で同期した動画録画を行うGUIアプリケーションです。

## 主な機能

- PTP同期による複数カメラ（最大8台）の同時録画
- Action Scheduler (Action0) によるフレーム同期トリガー
- ffmpeg (hevc_nvenc) によるリアルタイムMP4エンコード
- SRAW形式によるRaw録画
- マルチビューでの複数カメラプレビュー
- フレームタイムスタンプのCSV記録

## 技術スタック

| 項目 | 技術 |
|------|------|
| 言語 | Python 3.x |
| GUI | PySide6 (Qt6) |
| カメラSDK | imagingcontrol4 (IC4) — The Imaging Source社製産業用カメラ用 |
| 動画エンコード | ffmpeg with hevc_nvenc (NVIDIA GPU) |
| 同期方式 | PTP (IEEE 1588) + Action Scheduler |

## システム要件

- **OS**: Ubuntu Linux
- **GPU**: NVIDIA（hevc_nvenc対応）
- **カメラ**: The Imaging Source社製 PTP対応 GigEカメラ
- **NIC**: ハードウェアタイムスタンプ対応（`ethtool -T <iface>` で確認）
- **PTP**: linuxptp (`ptp4l`, `phc2sys`, `pmc`)

## セットアップ手順

### 1. PTP環境の構築

linuxptpをインストールし、PCをPTP Grandmasterとして設定します。

```bash
sudo apt-get update
sudo apt-get install -y linuxptp ethtool
```

NICのハードウェアタイムスタンプ対応を確認:

```bash
ethtool -T enp3s0
```

ptp4lをGrandmasterモードで起動:

```bash
sudo ptp4l -i enp3s0 -f /dev/stdin -2 -m -s /var/run/ptp4l <<'EOF'
[global]
time_stamping=hardware
network_transport=UDPv4
delay_mechanism=E2E
twoStepFlag=1
defaultDS.domainNumber=0
gmCapable=1
priority1=10
slaveOnly=0
[enp3s0]
logAnnounceInterval=1
logSyncInterval=-3
logMinDelayReqInterval=0
EOF
```

PHCとシステムクロックを同期:

```bash
sudo phc2sys -s enp3s0 -c CLOCK_REALTIME -O 0 -w
```

> 本番運用では systemd サービスとして登録することを推奨します。詳細は [dev/tutorials/08_multi_cam_parallel/Readme.md](dev/tutorials/08_multi_cam_parallel/Readme.md) の「systemd」セクションを参照してください。

### 2. IC4 SDKのインストール

```bash
pip install imagingcontrol4>=1.2.0
pip install imagingcontrol4pyside6
```

### 3. ffmpegのインストール

NVIDIA GPU対応のffmpegが必要です。hevc_nvencが利用可能であることを確認してください。

```bash
ffmpeg -encoders | grep nvenc
# h264_nvenc, hevc_nvenc, av1_nvenc が表示されればOK
```

> NVIDIA GPU対応ffmpegのビルド手順は [dev/tutorials/08_multi_cam_parallel/Readme.md](dev/tutorials/08_multi_cam_parallel/Readme.md) の「Build FFmpeg with NVIDIA GPU」セクションを参照してください。

### 4. Python仮想環境の構築

```bash
python -m venv .venv
source .venv/bin/activate
pip install imagingcontrol4>=1.2.0 imagingcontrol4pyside6
```

### 5. アプリケーションの起動

```bash
cd src/synchroCap
python main.py
```

## アプリケーション構成

アプリケーションは3つのタブで構成されています。

| タブ | 名称 | 説明 |
|------|------|------|
| Tab1 | Channel Manager | カメラとチャンネルID (01-99) の紐付け管理 |
| Tab2 | Camera Settings | 個別カメラのプロパティ設定 |
| Tab3 | Multi View | マルチカメラプレビュー・PTP同期録画 |

## 録画の仕組み

1. 全カメラがPTP Slaveになるまで待機
2. TIMESTAMP_LATCHでホスト-カメラ間の時刻差分を算出
3. Action Scheduler (Action0) に開始時刻を設定し、FrameStartを同時発火
4. 各カメラごとに独立したスレッドでフレームを取得・書き込み
5. Duration経過で自動停止

### 出力形式

| 形式 | 説明 |
|------|------|
| MP4 | hevc_nvencによるリアルタイムエンコード |
| Raw | SRAWフォーマット（FileHeader + FrameHeader + Payload） |

出力先: `captures/YYYYMMDD-HHmmss/` 配下にカメラごとのファイルを生成

## ディレクトリ構成

```
SynchroCap/
├── src/
│   └── synchroCap/           # メインアプリケーション
│       ├── main.py           # エントリーポイント
│       ├── mainwindow.py     # メインウィンドウ
│       ├── ui_multi_view.py  # マルチビューUI・録画統合
│       ├── recording_controller.py  # 録画制御ロジック
│       └── ...
├── dev/
│   └── tutorials/            # チュートリアル・サンプルコード
├── docs/                     # ドキュメント
│   ├── BACKLOG.md            # 案件一覧
│   ├── CHANGELOG.md          # リリース履歴
│   ├── architecture.md       # アーキテクチャ概要
│   ├── requirements.md       # 要件定義
│   ├── feature_design.md     # 機能設計書
│   └── issues/               # 個別案件フォルダ
├── tools/                    # CLIツール
└── output/                   # 録画出力先
```

## ドキュメント

- [docs/architecture.md](docs/architecture.md) — アーキテクチャ概要・コンポーネント設計
- [docs/requirements.md](docs/requirements.md) — 要求仕様
- [docs/feature_design.md](docs/feature_design.md) — 機能設計書
- [docs/BACKLOG.md](docs/BACKLOG.md) — 案件一覧とステータス
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — リリース履歴
