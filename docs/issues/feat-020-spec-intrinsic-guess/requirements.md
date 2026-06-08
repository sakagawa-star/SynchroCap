# 要求仕様書: feat-020 Offline Calibration - Spec-based Intrinsic Guess

## 1.1 プロジェクト概要

- **何を作るのか**: `tools/offline_calibration.py` に、メーカー公開の工業値（レンズ焦点距離 `fmm`、センサー画素ピッチ `px`/`py`）から初期カメラ行列 K を組み立て、`cv2.CALIB_USE_INTRINSIC_GUESS` を用いてキャリブレーション最適化の**初期推定値**として渡すオプション `--use-spec-guess` を追加する機能。加えて、信頼できる画素ピッチ由来のアスペクト比（`fx/fy = py/px`）を最適化中に固定する任意フラグ `--fix-aspect-ratio`（`cv2.CALIB_FIX_ASPECT_RATIO`）を追加する。
- **なぜ作るのか**: 現状 `CalibrationEngine.calibrate()` はカメラ行列 K の初期値をゼロ（`None`）から OpenCV 内部推定で開始する。工業値が判明している場合、それを初期推定値として与えることで最適化の収束を安定化させ、局所解を回避し、歪み係数推定の頑健性向上を狙う。**重要（既定A）**: 初期 K は原則固定せず、最適化対象のままとする（焦点距離 `fmm` の絶対値はフォーカス位置・公差で揺れ、主点 cx,cy はセンサー実装で揺れるため、これらの固定は歪み係数へのバイアス転写を招く）。**例外（任意B）**: アスペクト比 `fx/fy = py/px` は `fmm` が約分で消え、信頼できる画素ピッチ `px, py` のみで決まる。このため `--fix-aspect-ratio` 指定時に限りアスペクト比を固定してよい（正方画素なら比=1.0。真値既知のためバイアスなしに自由度を1つ削減できる）。スケール（焦点距離絶対値）と主点は固定しない。
- **誰が使うのか**: SynchroCap の開発者・運用者（保存済み PNG 画像からオフラインでキャリブレーションを実行する人）。
- **どこで使うのか**: Linux PC 上の CLI（Python 3.10、micromamba 環境 `SynchroCap`）。カメラ接続は不要。

## 1.2 用語定義

| 用語 | 定義 |
|---|---|
| 内部パラメータ / カメラ行列 K | `[[fx, 0, cx], [0, fy, cy], [0, 0, 1]]`（3x3）。fx, fy は焦点距離（px 単位）、cx, cy は主点（px 単位） |
| 焦点距離 `fmm` | レンズの焦点距離（ミリメートル単位）。メーカー公称値（例: LM3NC1M 3.5mm） |
| 画素ピッチ `px`, `py` | センサー1画素の横幅・縦幅（ミリメートル単位）。メーカー公称値（例: 0.003mm） |
| 画像サイズ `Wpx`, `Hpx` | 画像の横幅・縦幅（ピクセル単位）。入力画像から自動取得する |
| 初期カメラ行列 / 初期 K | 工業値から組み立てた K。最適化の出発点として渡す。`fx=fmm/px`, `fy=fmm/py`, `cx=Wpx/2`, `cy=Hpx/2` |
| 初期推定値（intrinsic guess） | `cv2.CALIB_USE_INTRINSIC_GUESS` フラグで渡す K の初期値。最適化対象のまま（**固定ではない**） |
| `CALIB_USE_INTRINSIC_GUESS` | OpenCV のフラグ。指定すると `calibrateCamera` は渡された K を出発点として最適化を開始する |
| アスペクト比 | `fx/fy`。`fx/fy = (fmm/px)/(fmm/py) = py/px` であり `fmm` が約分で消えるため、画素ピッチ `px, py` のみで決まる。正方画素（`px=py`）では 1.0 |
| `CALIB_FIX_ASPECT_RATIO` | OpenCV のフラグ。`fx/fy` の比のみを初期 K の比に固定する（`fx` を `fy` に従属させ `fx = (fx/fy)_initial × fy` とする）。**比のみ固定であり、スケール（`fy` の値）・主点 cx,cy は引き続き最適化される**（`fy` が初期値に固定される意味ではない）。本案件では `--use-spec-guess` と併用し、初期 K の比（正方画素なら 1.0）に固定する |

本用語は機能設計書・コード内でも同一の語を使用する。

## 1.3 機能要求一覧

### FR-001: 初期推定値オプションの CLI 指定

- **概要**: `tools/offline_calibration.py` に以下のオプションを追加する。
  - `--use-spec-guess`: 工業値から初期 K を組み立てて初期推定値として使用する（フラグ、`store_true`）
  - `--focal-mm FLOAT`: レンズ焦点距離（mm）。`fmm`
  - `--pixel-pitch-mm FLOAT`: センサー画素ピッチ（mm）。`px = py` と仮定（正方画素）
- **入力**: CLI 引数。例: `--use-spec-guess --focal-mm 3.5 --pixel-pitch-mm 0.003`。
- **出力**: 初期 K を組み立て、`engine.calibrate()` に初期カメラ行列として渡す。標準出力に組み立てた初期 K（fx, fy, cx, cy）を表示する。
- **受け入れ基準**:
  - `--use-spec-guess` 省略時はデフォルト動作（初期推定値なし、`None` 始動）であること。
  - `--use-spec-guess` 指定時に `--focal-mm` または `--pixel-pitch-mm` のいずれかが欠落していたら、エラーメッセージを表示して非ゼロ終了（exit code 1）すること。ファイル出力は行わないこと。
  - `--focal-mm` または `--pixel-pitch-mm` が 0 以下の場合、エラーメッセージを表示して非ゼロ終了（exit code 1）すること（ゼロ除算・不正行列の防止）。

### FR-002: CalibrationEngine の初期推定値対応

- **概要**: `CalibrationEngine.calibrate()` が初期カメラ行列を引数で受け取り、指定時は `cv2.CALIB_USE_INTRINSIC_GUESS` を有効化できるようにする。
- **入力**: 引数 `initial_camera_matrix: numpy.ndarray | None = None`。`None` のときは従来動作。`numpy.ndarray`（shape=(3,3)）のときは初期推定値として使用する。
- **出力**: `initial_camera_matrix` 指定時、`cv2.calibrateCamera()` に当該行列と `CALIB_USE_INTRINSIC_GUESS` フラグを渡してキャリブレーションを実行する。返却される `CalibrationResult` の構造は従来と同一。
- **受け入れ基準**:
  - `initial_camera_matrix=None`（デフォルト）で従来と同一の挙動となること（既存呼び出し元 `ui_calibration.py` は引数なしで従来動作）。
  - `initial_camera_matrix` 指定時、`CALIB_USE_INTRINSIC_GUESS` が `flags` に OR 結合されること。
  - `lens_model`（feat-019、normal/wide）と直交して組み合わせ可能であること（4通り: {normal, wide} × {guess あり, なし} すべて動作）。
  - `initial_camera_matrix` の shape が (3,3) でない場合、`ValueError` を送出すること。
  - 初期 K は**固定しない**（`CALIB_FIX_*` フラグは付与しない）。最適化後の K が初期 K と完全一致しないこと（=最適化が K を更新していること）を合成データで確認する。

### FR-003: 初期推定値・アスペクト比固定の結果表示

- **概要**: CLI の結果表示で、初期推定値を使用したか否か、使用時は初期 K の値、およびアスペクト比固定の有無を明示する。
- **入力**: `--use-spec-guess` / `--fix-aspect-ratio` の有無と組み立てた初期 K。
- **出力**:
  - `--use-spec-guess` 指定時: 計算前に組み立てた初期 K（`fx, fy, cx, cy` と算出根拠 `fmm, px/py, Wpx, Hpx`）を標準出力に表示する。
  - `--fix-aspect-ratio` 指定時: アスペクト比を固定した旨（固定比の値）を標準出力に表示する。
  - 最終結果表示（既存の Camera matrix 表示）は従来通り。
- **受け入れ基準**: `--use-spec-guess` 指定時に初期 K の表示行が出力されること。`--fix-aspect-ratio` 指定時にアスペクト比固定の表示行が出力されること。各オプション省略時はそれぞれの表示が出ないこと。

### FR-004: アスペクト比固定オプションの CLI 指定

- **概要**: `tools/offline_calibration.py` に `--fix-aspect-ratio` オプション（フラグ、`store_true`）を追加する。指定時、`cv2.CALIB_FIX_ASPECT_RATIO` を有効化し、初期 K のアスペクト比（正方画素なら 1.0）を最適化中に固定する。
- **入力**: CLI 引数 `--fix-aspect-ratio`。例: `--use-spec-guess --focal-mm 3.5 --pixel-pitch-mm 0.003 --fix-aspect-ratio`。
- **出力**: `cv2.CALIB_FIX_ASPECT_RATIO` を `engine.calibrate()` に伝え、`fx/fy` 比を初期値に固定したキャリブレーションを実行する。
- **受け入れ基準**:
  - `--fix-aspect-ratio` 省略時はアスペクト比を固定しない（fx, fy 独立最適化）こと。
  - `--fix-aspect-ratio` 指定時に `--use-spec-guess` が未指定の場合、エラーメッセージを表示して非ゼロ終了（exit code 1）すること（アスペクト比固定には初期 K が必須なため）。ファイル出力は行わないこと。
  - `--use-spec-guess`（単一 `--pixel-pitch-mm` で `px=py`）と併用時、固定される比は 1.0 であること。

### FR-005: CalibrationEngine のアスペクト比固定対応

- **概要**: `CalibrationEngine.calibrate()` が `fix_aspect_ratio: bool` 引数を受け取り、`True` のとき `cv2.CALIB_FIX_ASPECT_RATIO` を有効化できるようにする。
- **入力**: 引数 `fix_aspect_ratio: bool = False`。デフォルトは `False`（従来動作）。
- **出力**: `fix_aspect_ratio=True` 指定時、`flags` に `CALIB_FIX_ASPECT_RATIO` を OR 結合してキャリブレーションを実行する。
- **受け入れ基準**:
  - `fix_aspect_ratio=False`（デフォルト）で従来と同一の挙動となること（既存呼び出し元 `ui_calibration.py` は引数なしで従来動作）。
  - `fix_aspect_ratio=True` かつ `initial_camera_matrix=None` の場合、`ValueError` を送出すること（比の基準となる初期 K がないため）。
  - `fix_aspect_ratio=True` かつ初期 K の `fx=fy`（正方画素由来）のとき、最適化後の `result.camera_matrix` の `fx` と `fy` が一致（`numpy.isclose(fx, fy)` が `True`）すること。
  - `lens_model`（normal/wide）・`initial_camera_matrix` と直交して組み合わせ可能であること。

## 1.4 非機能要求

- **パフォーマンス**: 既存処理と同等（初期推定値の指定による追加処理は K 行列組み立てと `cv2.calibrateCamera()` 内部のみ）。
- **対応環境**: Linux、micromamba 環境 `SynchroCap`（Python 3.10）。GPU 不要。カメラ接続不要。
- **信頼性**: 不正な引数（必須値欠落・非正値・不正 shape）は即座にエラー終了し、ファイル出力を行わない。
- **互換性**: GUI（Tab5 Calibration）の動作は一切変更しない（`initial_camera_matrix` のデフォルト `None`、`fix_aspect_ratio` のデフォルト `False` により従来動作を維持）。feat-019 の `--lens` オプションとも独立して共存する。

## 1.5 制約条件

- **OpenCV の仕様**: `CALIB_USE_INTRINSIC_GUESS` を指定する場合、`cv2.calibrateCamera()` の `cameraMatrix` 引数に有効な初期行列（`None` 不可）を渡す必要がある。
- **アスペクト比固定の前提（アプリ層の安全策）**: `--fix-aspect-ratio` は `--use-spec-guess` との併用を必須とする（単独指定はエラー）。理由: 固定すべき `fx/fy` 比は初期 K から取られる。初期 K がないと OpenCV は内部初期化の比（実質 1.0）で固定してしまい、ユーザー意図と無関係な値で固定される恐れがあるため、意味が定まらない指定として拒否する（OpenCV 自体は `cameraMatrix=None` + `CALIB_FIX_ASPECT_RATIO` でもエラーにならないが、本案件では許容しない設計判断）。
- **正方画素の仮定**: 本案件では `px = py`（正方画素）を前提とし、単一の `--pixel-pitch-mm` で画素ピッチを与える。非正方画素（`px ≠ py`）の個別指定対応は本案件のスコープ外（必要なら別オプションで将来拡張）。
- **cx, cy の算出**: 主点は `Wpx/2, Hpx/2`（画像中心）で初期化する。主点ずれの個別指定は本案件のスコープ外。
- **固定範囲の限定**: 固定してよいのはアスペクト比（`CALIB_FIX_ASPECT_RATIO`）のみ。焦点距離絶対値の固定（`CALIB_FIX_FOCAL_LENGTH`）・主点の固定（`CALIB_FIX_PRINCIPAL_POINT`）は本案件のスコープ外とする（`fmm` の絶対値・主点は工業値が実機の実効値と乖離しうるため、固定するとバイアス転写を招く。一方アスペクト比は `fmm` が約分で消え画素ピッチのみで決まるため固定が安全）。

## 1.6 スコープ外

- GUI（Tab5）への初期推定値・アスペクト比固定オプション追加
- 非正方画素（`px ≠ py`）の個別指定対応
- 主点 cx, cy の個別指定
- 焦点距離絶対値の固定（`CALIB_FIX_FOCAL_LENGTH`）・主点の固定（`CALIB_FIX_PRINCIPAL_POINT`）対応（※アスペクト比の固定 `CALIB_FIX_ASPECT_RATIO` は FR-004/FR-005 でスコープ内）
- 工業値（fmm, px, py）の自動取得（メーカー DB 連携等）
