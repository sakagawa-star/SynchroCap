# feat-014: Camera Calibration - Wide-Angle Lens Support (8-coefficient model)

## Status: On Hold（カメラ映像が撮れないため手動テスト不可）

## 概要

キャリブレーション計算を5係数モデル（k1, k2, p1, p2, k3）から8係数モデル（k1, k2, p1, p2, k3, k4, k5, k6）に変更する。広角レンズ（LM3NC1M, 3.5mm, 画角89°×73.8°）で発生する樽型歪みを正確に補正するため。

## 背景

- 現在使用中のレンズ LM3NC1M は水平画角89°の広角レンズ
- OpenCVの標準5係数モデルでは広角レンズの歪みを十分に表現できない
- `cv2.CALIB_RATIONAL_MODEL` フラグにより8係数モデル（rational model）を使用し、歪み補正精度を向上させる

## 依存

- feat-011 (Calibration Calculation) — キャリブレーション計算の変更
- feat-012 (Export) — エクスポートの歪み係数数の変更
