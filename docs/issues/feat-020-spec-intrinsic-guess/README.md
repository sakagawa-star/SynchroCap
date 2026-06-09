# feat-020: Offline Calibration - Spec-based Intrinsic Guess (`--use-spec-guess`)

## Status

Closed

## 概要

`tools/offline_calibration.py` に、メーカー公開の工業値（焦点距離・画素ピッチ）から初期カメラ行列 K を組み立て、`cv2.CALIB_USE_INTRINSIC_GUESS` で最適化の初期推定値として渡すオプション `--use-spec-guess` を追加する。加えて、信頼できる画素ピッチ由来のアスペクト比を固定する任意フラグ `--fix-aspect-ratio`（`cv2.CALIB_FIX_ASPECT_RATIO`）を追加する。

- **既定（A）**: 初期 K は **初期推定値**としてのみ使用し、**固定しない**（fx,fy,cx,cy すべて最適化対象のまま）
- **任意（B）**: `--fix-aspect-ratio` 指定時のみ、アスペクト比 `fx/fy`（正方画素なら 1.0）を固定。スケール（焦点距離絶対値）と主点は固定しない
- 目的: 最適化の収束安定化・局所解回避。信頼できる画素ピッチ情報を活かして歪み係数推定の頑健性向上を狙う
- デフォルトは従来動作（初期推定値なし = `None` 始動、アスペクト比固定なし）

## 背景

- ユーザーから「fmm, px, py, Wpx, Hpx が工業値として判明している場合、歪み係数推定精度は理論的に向上するか」という質問があった
- 結論: K を**誤った値で固定**すると歪み係数にバイアスが転写され悪化しうる。一方、**初期推定値として渡すだけ**ならバイアスを注入せず収束安定化に寄与する（安全側）
- そこで「固定」ではなく「初期推定値（`CALIB_USE_INTRINSIC_GUESS`）」として渡す版を追加する（既定A）
- さらに「px/py は工業値として信頼できる」という前提を活かす設計として、アスペクト比固定（任意B）を追加:
  - `fx/fy = (fmm/px)/(fmm/py) = py/px` であり `fmm` が約分で消える → アスペクト比は信頼できる画素ピッチのみで決まる
  - したがってアスペクト比に限り固定が安全（正方画素は真値=1.0 が既知。バイアスなしに自由度を1つ削減）
  - 一方、`fmm` 絶対値（フォーカス位置・公差で揺れる）と主点 cx,cy（センサー実装で揺れる）は固定しない
- 初期 K の式:
  - `fx = fmm / px`, `fy = fmm / py`（px, py は画素ピッチ mm。本案件は `px=py` 前提）
  - `cx = Wpx / 2`, `cy = Hpx / 2`（Wpx, Hpx は画像サイズ。画像から自動取得）
- 対象カメラ DFK 33GR0234（onsemi AR0234CS）は 3.0µm×3.0µm の正方画素・binning 不使用のため `px=py` が厳密に成立する

## 関連ファイル

- `tools/offline_calibration.py` — CLI オプション追加（`--use-spec-guess` / `--focal-mm` / `--pixel-pitch-mm` / `--fix-aspect-ratio`）・初期 K 組み立て
- `src/synchroCap/calibration_engine.py` — `calibrate()` に `initial_camera_matrix` / `fix_aspect_ratio` 引数追加
- `src/synchroCap/calibration_exporter.py` — 変更不要
- `src/synchroCap/ui_calibration.py` — 変更不要（デフォルト引数で従来動作維持）

## ドキュメント

- [requirements.md](requirements.md) — 要求仕様書
- [design.md](design.md) — 機能設計書
