# 要求仕様書: Camera Calibration - Wide-Angle Lens Support (8-coefficient model)

対象: feat-014
作成日: 2026-03-20
基準文書: `docs/REQUIREMENTS_STANDARD.md`

---

## 1. プロジェクト概要

### 1.1 何を作るか

キャリブレーション計算で使用する歪みモデルを、OpenCVの5係数モデル（k1, k2, p1, p2, k3）から8係数モデル（k1, k2, p1, p2, k3, k4, k5, k6、rational model）に変更する。UIの歪み係数表示とJSONエクスポートも8係数に対応する。

### 1.2 なぜ作るか

現在使用中のレンズ LM3NC1M（焦点距離3.5mm、画角89.0°×73.8°）は広角レンズであり、標準5係数モデルでは樽型歪みを十分に表現できない。OpenCVの `cv2.CALIB_RATIONAL_MODEL` フラグにより8係数の rational model を使用し、歪み補正精度を向上させる。

### 1.3 誰が使うか

SynchroCapを使用してモーションキャプチャ用の同期録画を行うオペレーター。

### 1.4 どこで使うか

Ubuntu Linux、Python 3.10、micromamba SynchroCap環境。

---

## 2. 用語定義

| 用語 | 定義 |
|------|------|
| 5係数モデル | OpenCVの標準歪みモデル。(k1, k2, p1, p2, k3)。k1,k2,k3は放射歪み、p1,p2は接線歪み |
| 8係数モデル（rational model） | OpenCVの拡張歪みモデル。(k1, k2, p1, p2, k3, k4, k5, k6)。k4,k5,k6は分母側の放射歪み係数で、広角レンズの強い歪みを正確に表現できる |
| `cv2.CALIB_RATIONAL_MODEL` | `cv2.calibrateCamera()` に渡すフラグ。8係数モデルを有効にする |
| LM3NC1M | The Imaging Source社のCマウントレンズ。焦点距離3.5mm、画角89.0°×73.8° |

---

## 3. 機能要求一覧

### FR-001: 8係数モデルによるキャリブレーション計算

- **概要**: `cv2.calibrateCamera()` に `cv2.CALIB_RATIONAL_MODEL` フラグを追加し、8係数の歪みモデルで計算する
- **入力**: 既存と同一（object_points_list, image_points_list, image_size）
- **処理**:
  1. `cv2.calibrateCamera()` の第5引数（flags）に `cv2.CALIB_RATIONAL_MODEL` を指定する
  2. `cv2.calibrateCamera()` は `CALIB_RATIONAL_MODEL` 指定時に shape=(1,14) の `dist_coeffs` を返す。先頭8要素（k1, k2, p1, p2, k3, k4, k5, k6）のみが有効であり、残り6要素（thin-prism/tilted-sensor パラメータ）はゼロ。先頭8要素にトリミングして shape=(1,8) として格納する
- **出力**: `CalibrationResult` の `dist_coeffs` が shape=(1,8) になる
- **受け入れ基準**:
  - `dist_coeffs` が8要素（k1, k2, p1, p2, k3, k4, k5, k6）で返されること
  - 広角レンズ（LM3NC1M, 37枚のテスト画像）でキャリブレーションが実行でき、RMS再投影誤差が1.0px以下であること

### FR-002: UI歪み係数表示の8係数対応

- **概要**: Calibrationタブの歪み係数表示を5係数から8係数に拡張する
- **入力**: `CalibrationResult.dist_coeffs` (shape=(1,8))
- **処理**:
  1. 歪み係数の表示を以下の4行に変更する:
     ```
     k1=..., k2=...
     p1=..., p2=...
     k3=..., k4=...
     k5=..., k6=...
     ```
  2. 各値は小数点以下4桁で表示する（既存と同一）
- **出力**: UIの Dist ラベルの表示更新
- **受け入れ基準**:
  - 8個の歪み係数（k1〜k6, p1, p2）がすべて表示されること
  - 左パネル幅200pxに収まること

### FR-003: JSONエクスポートの8係数対応

- **概要**: JSONエクスポートの `dist_coeffs` を5要素から8要素に拡張する
- **入力**: `CalibrationResult.dist_coeffs` (shape=(1,8))
- **処理**: `dist_coeffs` の `flatten().tolist()` で8要素リストを出力する（コード変更不要、shape変更に自動追従する）
- **出力**: JSONファイルの `dist_coeffs` が8要素になる
- **受け入れ基準**:
  - JSONの `dist_coeffs` が8要素で出力されること

### FR-004: Pose2Sim TOMLエクスポートの互換性維持

- **概要**: Pose2Sim TOML の `distortions` は4要素（k1, k2, p1, p2）を維持する
- **入力**: `CalibrationResult.dist_coeffs` (shape=(1,8))
- **処理**: 既存と同一（`dist_coeffs[0:4]` で先頭4要素を取り出す）。コード変更不要
- **出力**: TOMLファイルの `distortions` が4要素のまま
- **受け入れ基準**:
  - TOMLの `distortions` が4要素（k1, k2, p1, p2）で出力されること（変更なし）

---

## 4. 非機能要求

### 4.1 パフォーマンス

| 項目 | 基準 |
|------|------|
| キャリブレーション計算 | 1920x1080解像度、37キャプチャで2秒以下。8係数モデルは5係数モデルより計算量が増えるが、単一カメラの内部パラメータ推定であり十分高速 |

### 4.2 対応環境

Ubuntu Linux、Python 3.10、micromamba SynchroCap環境。

---

## 5. 制約条件

### 5.1 使用必須ライブラリ

既存と同一。新規ライブラリの追加なし。`cv2.CALIB_RATIONAL_MODEL` は既存の opencv-contrib-python で提供される。

### 5.2 テストデータ

広角レンズ（LM3NC1M, 3.5mm）で撮影したChArUcoボード画像37枚を使用する。パス: `src/synchroCap/captures/20260318-141544/intrinsics/cam05520125/*.png`

---

## 6. 優先順位

| 優先度 | 機能ID | 機能名 |
|--------|--------|--------|
| **Must** | FR-001 | 8係数モデルによるキャリブレーション計算 |
| **Must** | FR-002 | UI歪み係数表示の8係数対応 |
| **Must** | FR-003 | JSONエクスポートの8係数対応 |
| **Must** | FR-004 | Pose2Sim TOMLエクスポートの互換性維持 |

### MVP範囲

FR-001〜FR-004すべてがMVP。

---

## 7. スコープ外

- fisheyeモデル（`cv2.fisheye.calibrate()`）対応
- 歪みモデルの選択UI（5係数/8係数の切替）
- レンズ情報の管理・保存
