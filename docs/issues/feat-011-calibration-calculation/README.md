# feat-011: Camera Calibration - Calibration Calculation + Result Display

## Status: Open

## 概要

feat-009/010で蓄積したキャプチャデータ（image_points, object_points）を使い、`cv2.calibrateCamera()` でカメラ内部パラメータ（焦点距離、主点、歪み係数）を算出し、結果をUI上に表示する。各キャプチャの再投影誤差も表示し、品質の悪いキャプチャの特定を支援する。

## 依存関係

- feat-009: Auto Capture（キャプチャデータの蓄積）← 完了
- feat-010: Coverage Heatmap（カバレッジ可視化）← 完了
