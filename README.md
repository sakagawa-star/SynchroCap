# SynchroCap

PTP (Precision Time Protocol, IEEE 1588) を使用して複数の産業用カメラを同期させ、フレーム単位で同期した動画録画を行うGUIアプリケーションです。

## 主な機能

- PTP同期による複数カメラ（最大8台）の同時録画
- Action Scheduler (Action0) によるフレーム同期トリガー
- ffmpeg (hevc_nvenc) によるリアルタイムMP4エンコード
- SRAW形式によるRaw録画
- マルチビューでの複数カメラプレビュー
- フレームタイムスタンプのCSV記録
- カメラキャリブレーション（ChArUcoボード自動検出、8係数歪みモデル、Pose2Simエクスポート）

## 技術スタック

| 項目 | 技術 |
|------|------|
| 言語 | Python 3.10 |
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

アプリケーションは5つのタブで構成されています。

| タブ | 名称 | 説明 |
|------|------|------|
| Tab1 | Channel Manager | カメラとチャンネルID (01-99) の紐付け管理 |
| Tab2 | Camera Settings | 個別カメラのプロパティ設定（Resolution, PixelFormat, FPS, Trigger, WB, Exposure, Gain） |
| Tab3 | Multi View | マルチカメラプレビュー・PTP同期録画 |
| Tab4 | Camera Settings Viewer | 全カメラの設定値一覧表示・設定一致チェック |
| Tab5 | Calibration | カメラキャリブレーション（ライブビュー + ボード検出 + 自動キャプチャ + 計算 + エクスポート） |

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

## カメラキャリブレーション

Tab5 (Calibration) では、カメラの内部パラメータ（焦点距離、主点、歪み係数）を算出できます。

### ワークフロー

1. **ライブビュー + ボード検出**: カメラを選択するとライブビューが開始し、ChArUcoボードをリアルタイム検出
2. **自動キャプチャ**: ボードを2秒間安定して検出すると自動的にキャプチャ（3秒クールダウン）
3. **カバレッジヒートマップ**: 検出済みコーナーの分布をヒートマップでオーバーレイ表示（次にボードをどこに置くべきかを可視化）
4. **キャリブレーション計算**: 4枚以上キャプチャ後、カメラ行列・歪み係数（8係数 Rational Model）・RMS再投影誤差を算出
5. **エクスポート**: Pose2Sim互換TOML + 汎用JSON形式で出力

### ボード設定

| 項目 | デフォルト値 |
|------|-------------|
| ボードタイプ | ChArUco |
| 列×行 | 5×7 |
| 正方形サイズ | 30.0 mm |
| マーカーサイズ | 22.0 mm |
| ArUco辞書 | DICT_6X6_250 |

ボード設定はアプリ終了後も永続化されます（`~/.local/share/synchroCap/board_settings.json`）。

### エクスポート形式

| ファイル | 内容 |
|----------|------|
| `cam{serial}_intrinsics.toml` | Pose2Sim互換（カメラ行列、歪み係数4パラメータ） |
| `cam{serial}_intrinsics.json` | OpenCV完全互換（カメラ行列、歪み係数8パラメータ） |

保存先: `captures/{timestamp}/intrinsics/cam{serial}/`

## CLIツール

| ツール | 説明 |
|--------|------|
| `tools/offline_calibration.py` | 保存済みChArUco画像からオフラインキャリブレーションを実行 |
| `tools/raw_tool.py` | Rawファイルの検証・表示・エンコード |
| `tools/calibrate_intrinsics.py` | チェスボードからのキャリブレーション（レガシー） |

## ディレクトリ構成

```
SynchroCap/
├── src/
│   └── synchroCap/                  # メインアプリケーション
│       ├── main.py                  # エントリーポイント
│       ├── mainwindow.py            # メインウィンドウ・タブ管理
│       ├── ui_channel_manager.py    # Tab1: チャンネル管理
│       ├── ui_camera_settings.py    # Tab2: 個別カメラ設定
│       ├── ui_multi_view.py         # Tab3: マルチビューUI・録画統合
│       ├── ui_camera_settings_viewer.py  # Tab4: カメラ設定ビューア
│       ├── ui_calibration.py        # Tab5: キャリブレーション
│       ├── recording_controller.py  # 録画制御ロジック
│       ├── board_detector.py        # ChArUcoボード検出
│       ├── calibration_engine.py    # キャリブレーション計算エンジン
│       ├── calibration_exporter.py  # TOML/JSONエクスポート
│       ├── coverage_heatmap.py      # カバレッジヒートマップ生成
│       ├── stability_trigger.py     # 安定検出トリガー
│       ├── board_settings_store.py  # Board Settings永続化
│       ├── channel_registry.py      # チャンネル登録管理
│       └── device_resolver.py       # シリアル→DeviceInfo解決
├── dev/
│   └── tutorials/                   # チュートリアル・サンプルコード
├── docs/                            # ドキュメント
│   ├── BACKLOG.md                   # 案件一覧
│   ├── CHANGELOG.md                 # リリース履歴
│   ├── architecture.md              # アーキテクチャ概要
│   └── issues/                      # 個別案件フォルダ
├── tools/                           # CLIツール
├── tests/                           # テストコード
└── output/                          # 録画出力先
```

## ドキュメント

- [docs/architecture.md](docs/architecture.md) — アーキテクチャ概要・コンポーネント設計
- [docs/BACKLOG.md](docs/BACKLOG.md) — 案件一覧とステータス
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — リリース履歴
- [docs/TECH_STACK.md](docs/TECH_STACK.md) — 技術スタック定義書
