# 機能設計書: feat-020 Offline Calibration - Spec-based Intrinsic Guess

## 1.1 対応要求マッピング

| 要求ID | 設計セクション |
|---|---|
| FR-001 | 1.4.1 (CLI オプション), 1.4.2 (初期 K 組み立て) |
| FR-002 | 1.4.3 (CalibrationEngine 変更) |
| FR-003 | 1.4.4 (結果表示) |
| FR-004 | 1.4.1 (CLI オプション), 1.4.2 (バリデーション) |
| FR-005 | 1.4.3 (CalibrationEngine 変更) |

## 1.2 システム構成

```
tools/offline_calibration.py        # 変更: --use-spec-guess / --focal-mm / --pixel-pitch-mm / --fix-aspect-ratio 追加、初期 K 組み立て、engine 呼び出し変更
src/synchroCap/calibration_engine.py # 変更: calibrate() に initial_camera_matrix / fix_aspect_ratio 引数追加
src/synchroCap/calibration_exporter.py # 変更なし
src/synchroCap/ui_calibration.py     # 変更なし（デフォルト引数で従来動作を維持）
tests/test_calibration_engine.py     # 追加: initial_camera_matrix / fix_aspect_ratio のテスト
```

依存方向: `offline_calibration.py` → `calibration_engine.py`（既存と同じ。循環依存なし）。

**責務分離（設計判断）**: 工業値 → 初期 K 行列の組み立ては **CLI 側（`offline_calibration.py`）の責務**とする。`CalibrationEngine` は汎用的に `numpy.ndarray`（3x3 行列）を受け取るのみとし、工業値（`fmm`, `px`, `py`）の知識を持たせない。これにより Engine の再利用性を保ち、将来 GUI から別経路で初期 K を渡す拡張にも対応できる。

却下案: Engine に `focal_mm`/`pixel_pitch_mm` を直接渡す案 — Engine が工業値ドメインに依存し、行列を直接持つ呼び出し元（将来の GUI 等）が使いにくくなるため却下。

## 1.3 技術スタック

- Python 3.10（micromamba 環境 `SynchroCap`）
- OpenCV (`cv2.calibrateCamera`, `cv2.CALIB_USE_INTRINSIC_GUESS`, `cv2.CALIB_FIX_ASPECT_RATIO`) — 既存利用。新規ライブラリ導入なし（`TECH_STACK.md` 更新不要）
- NumPy — 既存利用（初期 K 行列の構築）

## 1.4 各機能の詳細設計

### 1.4.1 CLI オプション（FR-001）

`tools/offline_calibration.py` の `parse_args()` に追加:

```python
parser.add_argument(
    "--use-spec-guess",
    action="store_true",
    help="Build an initial camera matrix from manufacturer spec values "
         "(--focal-mm, --pixel-pitch-mm) and pass it as an intrinsic guess "
         "(CALIB_USE_INTRINSIC_GUESS). The matrix is NOT fixed; it is only "
         "the optimization starting point.",
)
parser.add_argument(
    "--focal-mm",
    type=float,
    default=None,
    help="Lens focal length in mm (required with --use-spec-guess). e.g. 3.5",
)
parser.add_argument(
    "--pixel-pitch-mm",
    type=float,
    default=None,
    help="Sensor pixel pitch in mm, assumed square (required with "
         "--use-spec-guess). e.g. 0.003",
)
parser.add_argument(
    "--fix-aspect-ratio",
    action="store_true",
    help="Fix the aspect ratio fx/fy to the spec value (1.0 for square "
         "pixels) during optimization (CALIB_FIX_ASPECT_RATIO). Requires "
         "--use-spec-guess. Scale (absolute focal length) and principal "
         "point remain free.",
)
```

- `--lens`（feat-019）とは独立。両者は直交して指定可能。
- `--fix-aspect-ratio` は `--use-spec-guess` との併用必須（FR-004、バリデーションは 1.4.2）。

### 1.4.2 初期 K 組み立て（FR-001）

`main()` 内、`image_size` 確定後・`engine.calibrate()` 呼び出し前に実施する。

#### バリデーション（擬似コード）

```
# --- 引数のみで判定できるチェック（検出処理の前 / parse_args 直後）---
if args.fix_aspect_ratio and not args.use_spec_guess:
    print("Error: --fix-aspect-ratio requires --use-spec-guess", stderr)
    return 1
if args.use_spec_guess:
    if args.focal_mm is None or args.pixel_pitch_mm is None:
        print("Error: --use-spec-guess requires --focal-mm and --pixel-pitch-mm", stderr)
        return 1
    if args.focal_mm <= 0 or args.pixel_pitch_mm <= 0:
        print("Error: --focal-mm and --pixel-pitch-mm must be positive", stderr)
        return 1

# --- 初期 K 組み立て（image_size 確定後）---
initial_camera_matrix = None
if args.use_spec_guess:
    initial_camera_matrix = _build_initial_camera_matrix(
        args.focal_mm, args.pixel_pitch_mm, image_size
    )
    # 初期 K を表示（FR-003）

# --- engine 呼び出し ---
calib_result = engine.calibrate(
    object_points_list, image_points_list, image_size,
    lens_model=args.lens,
    initial_camera_matrix=initial_camera_matrix,
    fix_aspect_ratio=args.fix_aspect_ratio,
)
```

- **実装方針（検証配置）**: 引数のみで判定できるチェック（`--fix-aspect-ratio` の `--use-spec-guess` 併用必須、`--use-spec-guess` 指定時の `--focal-mm`/`--pixel-pitch-mm` の欠落・非正値）は **検出処理の前**（`parse_args()` 直後）に行い、不正引数時に無駄な画像検出を避けて即 exit 1 する。初期 K の実際の組み立て（`Wpx/Hpx` が必要）は **`image_size` 確定後**に行う。
- `args.fix_aspect_ratio` は `--use-spec-guess` 併用必須のため、`initial_camera_matrix is not None` が保証された状態で `engine.calibrate()` に渡る（Engine 側でも二重に検証する。1.4.3 参照）。

#### 初期 K 組み立て関数（新規ヘルパー）

```python
def _build_initial_camera_matrix(
    focal_mm: float, pixel_pitch_mm: float, image_size: tuple[int, int]
) -> numpy.ndarray:
    """Build initial camera matrix K from manufacturer spec values.

    fx = focal_mm / pixel_pitch_mm,  fy = focal_mm / pixel_pitch_mm
    cx = W / 2,  cy = H / 2
    """
    w, h = image_size
    f_px = focal_mm / pixel_pitch_mm
    return numpy.array([
        [f_px,  0.0,  w / 2.0],
        [ 0.0, f_px,  h / 2.0],
        [ 0.0,  0.0,      1.0],
    ], dtype=numpy.float64)
```

- `fx = fy = focal_mm / pixel_pitch_mm`（正方画素仮定、requirements 1.5）。
- `cx = w/2`, `cy = h/2`。

### 1.4.3 CalibrationEngine 変更（FR-002, FR-005）

#### インターフェース定義

```python
def calibrate(
    self,
    object_points_list: list[numpy.ndarray],
    image_points_list: list[numpy.ndarray],
    image_size: tuple[int, int],
    lens_model: str = "wide",
    initial_camera_matrix: numpy.ndarray | None = None,
    fix_aspect_ratio: bool = False,
) -> CalibrationResult:
```

#### 処理ロジック（擬似コード）

```
1. lens_model が "normal"/"wide" 以外なら ValueError（既存）
2. MIN_CAPTURES チェック（既存）
3. initial_camera_matrix が None でない場合:
     - shape が (3,3) でなければ ValueError(f"initial_camera_matrix must be shape (3,3), got {shape}")
4. fix_aspect_ratio が True かつ initial_camera_matrix が None なら
     ValueError("fix_aspect_ratio=True requires initial_camera_matrix")
5. flags = CALIB_RATIONAL_MODEL if lens_model == "wide" else 0   # 既存
6. if initial_camera_matrix is not None:
       flags |= cv2.CALIB_USE_INTRINSIC_GUESS
       camera_matrix_arg = initial_camera_matrix.astype(numpy.float64).copy()
   else:
       camera_matrix_arg = None
7. if fix_aspect_ratio:
       flags |= cv2.CALIB_FIX_ASPECT_RATIO
8. cv2.calibrateCamera(obj, img, image_size, camera_matrix_arg, None, flags=flags)
9. dist_coeffs = dist_coeffs[:, :8]   # 既存（wide:14→8, normal:5 は無変化）
10. per_image_errors 計算（既存）
11. logger.info にモデル名 + intrinsic guess + fix_aspect_ratio 有無を追記
12. CalibrationResult 返却（既存）
```

- ステップ4は順序上ステップ3（shape 検証）の後に置く。`initial_camera_matrix` が不正 shape の場合は先に shape の `ValueError` が出る。
- `CALIB_FIX_ASPECT_RATIO` は `CALIB_USE_INTRINSIC_GUESS` 指定時、初期 K の `fx/fy` 比のみを固定する（`fx` を `fy` に従属させる）。`fy` のスケール値・主点 cx,cy は最適化対象のまま（`fy` が初期値に固定される意味ではない）。本案件では初期 K の `fx=fy`（正方画素由来）なので比 1.0 が固定され、最適化後も `fx == fy`（FR-005 受け入れ基準）。

#### 設計上の注意点

- **`.copy()` の必要性（実測で確認済み）**: `cv2.calibrateCamera()` は `CALIB_USE_INTRINSIC_GUESS` 指定時、渡された `cameraMatrix` 配列を **in-place で更新**するだけでなく、**戻り値の `camera_matrix` が入力した `cameraMatrix` と同一オブジェクトを指す**（`passed_in is returned_cm` が `True`）。したがって `.copy()` せずに呼び出し元の初期 K をそのまま渡すと、(a) 呼び出し元（`_build_initial_camera_matrix` の戻り値）が破壊され、かつ (b) `result.camera_matrix is initial_K` となり `numpy.allclose(result.camera_matrix, initial_K)` が常に `True` になって **テスト #3（not_fixed）/ #7（does_not_mutate_input）が破綻する**。これを防ぐため、Engine 内で `initial_camera_matrix.astype(numpy.float64).copy()` を渡す（`.astype()` は新規配列を返すが、元が float64 の場合はコピーを返さない実装もあるため `.copy()` を明示する）。これにより呼び出し元は元の初期 K を保持でき、最適化後の K（戻り値）と独立して比較できる。
- **`.astype(numpy.float64)`**: OpenCV は float64 を要求するため明示変換する（呼び出し元が float32 を渡しても安全）。
- **dtype/shape チェック**: shape のみ検証する（(3,3) でなければ `ValueError`）。dtype は `.astype()` で吸収するため検証不要。
- **固定はアスペクト比のみ**: 固定してよいのは `CALIB_FIX_ASPECT_RATIO`（`fix_aspect_ratio=True` 時）のみ。`CALIB_FIX_FOCAL_LENGTH` / `CALIB_FIX_PRINCIPAL_POINT` は付与しない（requirements 1.5 / 1.6）。アスペクト比固定時もスケール（焦点距離絶対値）と主点 cx,cy は自由のまま。
- **アスペクト比固定の前提検証（アプリ層の安全策）**: `fix_aspect_ratio=True` かつ `initial_camera_matrix=None` は `ValueError`（擬似コード ステップ4）。**注意（実測で確認済み）**: これは OpenCV の制約ではない。`cameraMatrix=None` + `CALIB_FIX_ASPECT_RATIO` でも `cv2.calibrateCamera()` はエラーを出さず、内部初期化のアスペクト比（実質 1.0）で動作してしまう。しかし「どの比を固定するか」の出所が初期 K なしでは不定（ユーザー意図と無関係な内部値で固定される）ため、**本案件では意味が定まらない指定として明示的に拒否する**（アプリ層の安全策）。CLI 側でも併用必須を検証するが（1.4.2）、Engine 単体利用・将来の GUI 呼び出しに備え Engine 側でも防御的に検証する。

#### エラーハンドリング

| エラー | 検出 | 処理 | ログ |
|---|---|---|---|
| 不正な lens_model | calibrate() 冒頭（既存） | `ValueError`（既存） | なし |
| キャプチャ不足 | MIN_CAPTURES チェック（既存） | `ValueError`（既存） | 既存 |
| 不正な initial_camera_matrix shape | calibrate() 内 shape 検証 | `ValueError` 送出（リトライなし） | なし（例外メッセージで十分） |
| fix_aspect_ratio=True かつ initial_camera_matrix=None | calibrate() 内検証 | `ValueError` 送出（リトライなし） | なし（例外メッセージで十分） |
| cv2.error | calibrateCamera 内部 | 呼び出し元へ伝播（既存） | 既存 |

ログ更新案: `"Calibration done: RMS=%.4f px, %d images, model=%s, intrinsic_guess=%s, fix_aspect_ratio=%s"`（`intrinsic_guess` は `initial_camera_matrix is not None`、`fix_aspect_ratio` はそのままの bool）。

### 1.4.4 結果表示（FR-003）

`offline_calibration.py` の `main()` 内、初期 K 組み立て時（`engine.calibrate()` 呼び出し前）に標準出力へ表示する:

```
Initial camera matrix (from spec, used as intrinsic guess):
  focal=3.5mm  pixel_pitch=0.003mm  image=1920x1200
  fx=1166.67  fy=1166.67  cx=960.00  cy=600.00
  (NOT fixed; optimization starting point only)
  aspect ratio fx/fy FIXED at 1.000 (scale and principal point remain free)
```

（表示例の解像度は対象カメラ DFK 33GR0234 / AR0234CS のネイティブ 1920×1200。実際は入力画像サイズ `image_size` に追従する。`cx=W/2=960`, `cy=H/2=600`）

- 「`aspect ratio fx/fy FIXED ...`」の行は `--fix-aspect-ratio` 指定時のみ表示する。固定比は初期 K から `fx/fy` を算出して表示する（正方画素なら 1.000）。
- `--use-spec-guess` 省略時は初期 K ブロック全体を表示しない。`--use-spec-guess` 指定かつ `--fix-aspect-ratio` 省略時は初期 K ブロックを表示し、アスペクト比固定行のみ省く。
- 既存の最終結果表示（`Camera matrix: fx=... fy=... cx=... cy=...`）は変更しない。最適化後の K と初期 K を見比べられることで、最適化が K を更新したこと（およびアスペクト比固定時に `fx==fy` が維持されたこと）をユーザーが確認できる。

## 1.5 状態遷移

なし（CLI の一方向処理。GUI 変更なし）。

## 1.6 ファイル・ディレクトリ設計

- 出力ファイル名・パス規約は既存のまま: `<output_dir>/cam{serial}_intrinsics.toml` / `.json`
- TOML/JSON の内容・キー名は変更なし（初期推定値は最適化の出発点に過ぎず、出力は最適化後の値）

## 1.7 インターフェース定義

| モジュール | シグネチャ | 変更内容 |
|---|---|---|
| `CalibrationEngine.calibrate` | `(self, object_points_list, image_points_list, image_size, lens_model="wide", initial_camera_matrix: numpy.ndarray \| None = None, fix_aspect_ratio: bool = False) -> CalibrationResult` | `initial_camera_matrix`（デフォルト `None`）・`fix_aspect_ratio`（デフォルト `False`）追加。両デフォルトで後方互換 |
| `_build_initial_camera_matrix` (offline_calibration.py、新規) | `(focal_mm: float, pixel_pitch_mm: float, image_size: tuple[int, int]) -> numpy.ndarray` | 新規ヘルパー |
| `parse_args` (offline_calibration.py) | 変更なし（Namespace に `use_spec_guess`, `focal_mm`, `pixel_pitch_mm`, `fix_aspect_ratio` 属性が追加） | オプション追加 |
| `CalibrationExporter.export` | 変更なし | — |

## 1.8 ログ・デバッグ設計

- INFO: `Calibration done: RMS=%.4f px, %d images, model=%s, intrinsic_guess=%s, fix_aspect_ratio=%s`（既存ログに intrinsic guess 有無・アスペクト比固定有無を追記）
- CLI 標準出力: 初期 K の表示（FR-003、`--use-spec-guess` 時のみ）、アスペクト比固定行（`--fix-aspect-ratio` 時のみ）
- その他のログポイントは既存のまま

## 1.9 テスト設計

`tests/test_calibration_engine.py` に追記:

1. `test_calibrate_with_intrinsic_guess_returns_result` — 合成データ + 既知カメラ行列に近い初期 K で `initial_camera_matrix` 指定 → `CalibrationResult` を返し RMS < 1.0 px。
2. `test_calibrate_intrinsic_guess_sets_flag` — 初期 K 指定時に推定カメラ行列が既知値の ±5% 以内（guess が有効に働き正しく収束する）。
3. `test_calibrate_intrinsic_guess_not_fixed` — 初期 K（既知値からわざと 5% ずらした値）を渡し、最適化後の K が初期 K と**完全一致しない**こと（`numpy.allclose(result.camera_matrix, initial_K)` が `False`）。K が固定されていないことの確認。
4. `test_calibrate_invalid_initial_matrix_shape_raises` — shape=(2,2) の初期行列 → `ValueError`。
5. `test_calibrate_default_no_guess` — `initial_camera_matrix` 省略時に従来通り動作（`CalibrationResult` を返す。既存テストと同等の挙動）。
6. `test_calibrate_guess_with_normal_lens` — `lens_model="normal"` + `initial_camera_matrix` 指定 → dist_coeffs.shape == (1,5)（feat-019 と直交動作）。
7. `test_calibrate_guess_does_not_mutate_input` — 呼び出し元が渡した初期 K 配列が呼び出し後も不変であること（Engine 内 `.copy()` の検証）。
8. `test_calibrate_fix_aspect_ratio_keeps_fx_eq_fy` — 初期 K の `fx=fy`（既知値からスケールを 5% ずらした正方比）+ `fix_aspect_ratio=True` → 最適化後の `result.camera_matrix` の `fx` と `fy` が一致（`numpy.isclose(fx, fy)`）し、RMS < 1.0 px。比が固定されていることの確認。
9. `test_calibrate_fix_aspect_ratio_requires_initial_matrix` — `fix_aspect_ratio=True` かつ `initial_camera_matrix=None` → `ValueError`。
10. `test_calibrate_fix_aspect_ratio_default_false` — `fix_aspect_ratio` 省略時（`initial_camera_matrix` 指定あり）はアスペクト比を固定しない（`CALIB_FIX_ASPECT_RATIO` の効果がない）こと。検証方法: 初期 K の `fx≠fy`（例: fx を fy の 1.1 倍にした非正方初期値）で `fix_aspect_ratio=False` で呼ぶと、最適化が両者を独立に動かし真値（合成データは fx=fy=800）へ収束し `fx≈fy`（`fx/fy≈1.0`）になる一方、同じ初期 K で `fix_aspect_ratio=True` だと比 1.1 が固定され `fx/fy≈1.1` のまま残る。両者の差で固定の効きを確認する。
    - **重要（実測で確認済み）**: 判定は必ず **`fx/fy` 比**で行うこと。RMS でアサートしてはならない。誤った比 1.1 を固定した場合（Case B）でも合成データの自由度が高く RMS は約 0.70 px（< 1.0）に収まり、比 1.25/0.9 でも約 1.13 px 程度であり、RMS では固定の効きを判別できない。`fix_aspect_ratio=False`（Case A）の最終比は約 1.0、`fix_aspect_ratio=True`（Case B）の最終比は初期比（1.1）に厳密一致する、という**比の差**で判定する。

`tools/offline_calibration.py` のヘルパー関数テスト（同ファイル内または別テストファイル）:

11. `test_build_initial_camera_matrix` — `focal_mm=3.5, pixel_pitch_mm=0.003, image_size=(1920,1080)` → `fx≈1166.67, fy≈1166.67, cx=960, cy=540`、shape=(3,3)。`fx==fy` であることが FR-004 受け入れ基準「単一 `--pixel-pitch-mm`（px=py）併用時に固定比が 1.0」の根拠となる（このテストで `fx==fy`＝比1.0 を確認し、テスト#8で `CALIB_FIX_ASPECT_RATIO` がその比を維持することを確認する。両者で CLI 経路の比1.0固定を自動テストで担保）。

合成データ: 既存の `_generate_synthetic_data()`（既知カメラ行列 fx=fy=800, cx=320, cy=240、歪みなし）を再利用する。アスペクト比固定テスト（#8, #10）で「非正方初期 K」を作る場合は、既知行列の `fx` または `fy` を定数倍してコピーした行列を用いる。

注: CLI レベルのバリデーション（`--fix-aspect-ratio` の `--use-spec-guess` 併用必須、必須値欠落・非正値）は `tools/offline_calibration.py` の `main()` 内分岐であり、Engine 単体テストの対象外。Engine 側の防御的検証（#9）でアスペクト比固定の前提を担保する。CLI 分岐は手動テスト（ステップ7、実機確認）で確認する。

テスト実行: `micromamba run -n SynchroCap pytest -v`（Subagent で実行）。結果は `tests/results/feat-020_test_result.txt` に保存する。

注: 本設計書内の行番号参照はすべて執筆時点の目安であり、実装時はシンボル名（関数名・変数名・テスト名）で対象を特定すること。
