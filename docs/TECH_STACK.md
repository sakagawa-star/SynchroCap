# 技術スタック定義書

最終更新: 2026-03-04

---

## プロジェクト基盤

| 項目 | 値 | 根拠 |
|------|-----|------|
| 言語 | Python 3.10 | `setup_env.sh`, `environment.yml` で 3.10 を指定 |
| パッケージ管理 | micromamba + pip | `setup_env.sh` で micromamba 環境を作成し pip でインストール |
| 環境定義ファイル | `setup_env.sh`（構築用）, `dev/tutorials/08_multi_cam_parallel/environment.yml`（フリーズ版） |
| 対象OS | Ubuntu Linux | `README.md` |
| GPU | NVIDIA（hevc_nvenc 対応必須） | `README.md`, `docs/requirements.md` |

---

## ライブラリ一覧

### メインアプリケーション（src/synchroCap/）

| ライブラリ名 | バージョン | 用途 | 使用箇所 | 選定理由 |
|-------------|-----------|------|---------|---------|
| imagingcontrol4 | >=1.2.0（`requirements.txt`）, ==1.3.0.3125（`environment.yml`） | The Imaging Source 産業用カメラ制御 SDK | main, mainwindow, device_resolver, ui_channel_manager, ui_camera_settings, ui_multi_view, recording_controller, chktimestat, ptp_sync_check, ui_camera_settings_viewer | カメラハードウェア指定 |
| imagingcontrol4pyside6 | バージョン未指定（`requirements.txt`）, ==6.8.0.102（`environment.yml`） | IC4 の PySide6 統合パッケージ | mainwindow（ResourceSelector） | IC4 SDK 公式 GUI 連携 |
| PySide6 | ==6.8.3（`environment.yml`）, `requirements.txt` では未固定 | Qt6 ベースの GUI フレームワーク | main, mainwindow, ui_channel_manager, ui_camera_settings, ui_multi_view, ui_camera_settings_viewer, resourceselector | IC4 SDK が PySide6 統合を提供 |
| opencv-contrib-python | >=4.9.0 | ArUco/ChArUco検出（CharucoDetector API）、BayerGR8→BGR変換 | ui_calibration, board_detector | ArUcoモジュールがcontrib版にのみ含まれる。`opencv-python` と競合するため置き換えて使用。4.7+で`CharucoDetector`導入、4.9以降で安定 |
| numpy | ==2.2.6（`environment.yml`）, `requirements.txt` では未記載 | 数値計算・画像データ配列操作 | ui_calibration, board_detector（+ tools/ で使用） | 画像データ処理の標準ライブラリ |

### ツール類（tools/）

| ライブラリ名 | バージョン | 用途 | 使用箇所 | 選定理由 |
|-------------|-----------|------|---------|---------|
| opencv-python (cv2) | 未固定 | 画像処理・チェスボード検出・Bayer変換 | tools/viz_corners, chk_qr, timeqr, cuda_bayer2jpeg, calibrate_intrinsics, estimate_extrinsics, extrinsics_opencv | 画像処理の標準ライブラリ。**注意**: メインアプリで `opencv-contrib-python` を使用するため、`opencv-python` は自動的に置き換えられる（共存不可） |
| numpy | ==2.2.6（`environment.yml`） | 数値計算・配列操作 | tools/ 内の大半のスクリプト | cv2 と組み合わせて使用 |
| toml | 未固定 | TOML 設定ファイル読み込み | tools/viz_corners, calibrate_intrinsics, estimate_extrinsics, extrinsics_opencv | キャリブレーション設定の読み込み |
| Pillow (PIL) | 未固定 | 画像生成 | tools/timeqr | QR コード画像生成の基盤 |
| qrcode | 未固定 | QR コード生成 | tools/timeqr | 時刻 QR コード表示ツール |
| matplotlib | 未固定（オプション） | 3D プロット描画 | tools/calib_geom_viewer/plotting | カメラ配置の可視化（オプション依存） |

### 外部コマンド

| コマンド名 | 用途 | 使用箇所 | 備考 |
|-----------|------|---------|------|
| ffmpeg（hevc_nvenc） | 動画エンコード（rawvideo → MP4） | recording_controller | NVIDIA GPU 必須、フォールバックなし |
| ptp4l | PTP Grandmaster 実装 | システムサービス（アプリ外） | linuxptp パッケージ |
| phc2sys | PHC-SystemClock 同期 | システムサービス（アプリ外） | linuxptp パッケージ |
| pmc | PTP Management Client | ptp_sync_check, chktimestat | linuxptp パッケージ |
| ethtool | NIC ハードウェアタイムスタンプ確認 | 環境構築時のみ | — |
| blender | 3D シーンエクスポート | tools/calib_geom_viewer/blender_export | オプション |

### 設計書に記載があるが実コードで未使用のもの

該当なし

---

## バージョン固定ポリシー

### 管理ファイル

| ファイル | 役割 | 固定方式 |
|---------|------|---------|
| `src/synchroCap/requirements.txt` | メインアプリの最小依存定義 | `>=` 下限指定またはバージョン未指定 |
| `dev/tutorials/08_multi_cam_parallel/environment.yml` | 動作確認済み環境のフリーズ | `==` 完全固定 |
| `setup_env.sh` | 新規環境構築スクリプト | `>=` 下限指定（アプリ本体）、バージョン未指定（ツール類） |

### 方針

- **メインアプリ（src/）**: `requirements.txt` で最小依存を `>=` 下限で管理。PySide6・numpy は imagingcontrol4 の依存として間接インストールされるため明示記載なし
- **再現環境**: `environment.yml` で `==` 完全固定のフリーズ版を管理
- **ツール類（tools/）**: `setup_env.sh` 内で pip install しているが、バージョン未固定

### 不整合

| 項目 | `requirements.txt` | `environment.yml` | 備考 |
|------|-------------------|-------------------|------|
| imagingcontrol4 | >=1.2.0 | ==1.3.0.3125 | 下限と固定の差異（意図的な運用） |
| imagingcontrol4pyside6 | バージョン未指定 | ==6.8.0.102 | `requirements.txt` でバージョン未固定 |
| numpy | 未記載 | ==2.2.6 | `requirements.txt` に記載なし |
| PySide6 | 未記載 | ==6.8.3 | `requirements.txt` に記載なし（間接依存） |

---

## 制約・禁止事項

### 技術上の必須条件

| 制約 | 内容 | 根拠 |
|------|------|------|
| エンコーダ固定 | hevc_nvenc 固定。フォールバック・代替エンコーダは実装しない | `docs/requirements.md` §3.3 |
| Pixel format 固定 | BayerGR8（ffmpeg 入力: bayer_grbg8） | `docs/requirements.md` §3.2 |
| PTP Slave 必須 | 全カメラが PTP Slave 状態でなければ録画開始不可 | `docs/requirements.md` §2.2 |
| DEFER_ACQUISITION_START 必須 | 複数カメラの同時開始に必須 | `docs/requirements.md` §5.3 |
| NVIDIA GPU 必須 | hevc_nvenc の動作に必要 | `docs/requirements.md` §3.3 |
| linuxptp 必須 | ptp4l, phc2sys, pmc がシステムサービスとして動作すること | `README.md` |

### 使用禁止ライブラリ

未定義（要求仕様書に明示的な禁止リストの記載なし）

### 非要件（実装対象外）

以下は `docs/requirements.md` §6 で明示的に対象外とされている:

- Raw ファイル保存（※ feat-002 で後から追加済み）
- MP4 以外の形式
- 出力パス指定 UI
- 録画品質切替
- 録画成否判定
- 高度なエラーハンドリング
