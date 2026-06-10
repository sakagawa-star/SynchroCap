# bug-009: 共線コーナーのキャプチャでキャリブレーション計算がクラッシュする

- **Status**: Closed
- **Type**: Bug
- **作成日**: 2026-06-10
- **完了日**: 2026-06-10
- **関連案件**: feat-008 (Board Detection), feat-011 (Calibration Calculation), feat-019/020 (Offline Calibration)

## 概要

ChArUcoボードの検出コーナーが全て一直線上に並んだ画像（共線配置）がキャプチャに含まれていると、
`cv2.calibrateCamera()` がOpenCV内部の初期パラメータ推定（`initIntrinsicParams2D`）で
assertion エラーを出してクラッシュする。

`BoardDetector` の検出成功判定は「コーナー数6以上」（feat-008 FR-004）のみで、
コーナーの幾何学的配置（共線かどうか）を検査していないため、
キャリブレーションに使用できない退化したキャプチャが有効として通過してしまう。

## 再現手順

1. 5x7 ChArUcoボードの端の1列だけが画角に入った画像を撮影する
   （内部コーナーグリッドは4x6。1列分 = 6コーナーが検出され、最小コーナー数6をちょうど満たす）
2. その画像を含むディレクトリに対してオフラインキャリブレーションを実行する:

   ```bash
   micromamba run -n SynchroCap python tools/offline_calibration.py \
       <image_dir> <serial> --lens normal --square-mm 34 --marker-mm 22
   ```

3. 全画像の検出成功後、`cv2.calibrateCamera()` で以下のエラーが発生する:

   ```
   cv2.error: OpenCV(4.13.0) /io/opencv/modules/calib3d/src/calibration.cpp:94:
   error: (-215:Assertion failed) matH0.size() == Size(3, 3) in function 'initIntrinsicParams2D'
   ```

## 実際の発生事例 (2026-06-10)

- 画像セット: `/media/sakagawa/T5 EVO/SynchroCap/videos/20260610-092904/intrinsics/cam05520126/`（82枚）
- 問題の画像: `capture_041.png` — 検出6コーナー、ChArUco ID = 3, 7, 11, 15, 19, 23
- 6点全てがボード座標 x=0.136m の同一列（完全共線。中心化座標の第2特異値 ≈ 3.7e-8）
- この点群に対する `cv2.findHomography` は `None`（計算失敗）を返すことを確認済み
- `capture_041.png` を除外して再実行すると正常に完走する

## 補足

- `--use-spec-guess` 指定時は `CALIB_USE_INTRINSIC_GUESS` により `initIntrinsicParams2D` が
  スキップされるためクラッシュしないが、共線キャプチャが精度に寄与しない点は変わらない
- 同じ検出経路を使うアプリ本体（Tab5 Calibration の自動キャプチャ → Calibrate実行）でも
  発生し得る（共線検出が安定検出トリガーを通過してキャプチャされた場合）

## 調査・修正計画

`investigation.md` を参照。
