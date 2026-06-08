# 機能設計書: feat-019 Offline Calibration - Lens Model Selection

## 1.1 対応要求マッピング

| 要求ID | 設計セクション |
|---|---|
| FR-001 | 1.4.1 (CLI オプション) |
| FR-002 | 1.4.2 (CalibrationEngine 変更) |
| FR-003 | 1.4.3 (エクスポート — 変更不要の確認) |
| FR-004 | 1.4.4 (結果表示) |

## 1.2 システム構成

```
tools/offline_calibration.py        # 変更: --lens オプション追加、engine 呼び出し変更
src/synchroCap/calibration_engine.py # 変更: calibrate() に lens_model 引数追加
src/synchroCap/calibration_exporter.py # 変更なし（係数長に非依存であることを確認済み）
src/synchroCap/ui_calibration.py     # 変更なし（デフォルト引数で従来動作を維持）
tests/test_calibration_engine.py     # 追加/変更: lens_model のテスト
```

依存方向: `offline_calibration.py` → `calibration_engine.py` / `calibration_exporter.py`（既存と同じ。循環依存なし）。

## 1.3 技術スタック

- Python 3.10（micromamba 環境 `SynchroCap`）
- OpenCV (`cv2.calibrateCamera`) — 既存利用。新規ライブラリ導入なし（`TECH_STACK.md` 更新不要）

## 1.4 各機能の詳細設計

### 1.4.1 CLI オプション（FR-001）

`tools/offline_calibration.py` の `parse_args()` に追加:

```python
parser.add_argument(
    "--lens",
    choices=["normal", "wide"],
    default="wide",
    help="Lens type: 'normal' = 5-coefficient model (k1,k2,p1,p2,k3), "
         "'wide' = rational 8-coefficient model (default: wide)",
)
```

- 不正値は argparse の `choices` 機構が usage 表示 + exit code 2 で終了する（自前バリデーション不要）。
- `main()` 内の呼び出しを `engine.calibrate(..., lens_model=args.lens)` に変更する。
- docstring（Usage 例）に `--lens normal` の例を1つ追加する。

### 1.4.2 CalibrationEngine 変更（FR-002）

#### インターフェース定義

```python
def calibrate(
    self,
    object_points_list: list[numpy.ndarray],
    image_points_list: list[numpy.ndarray],
    image_size: tuple[int, int],
    lens_model: str = "wide",
) -> CalibrationResult:
```

#### データフロー

| lens_model | flags | calibrateCamera 返却 dist_coeffs | トリム後 |
|---|---|---|---|
| `"wide"` | `cv2.CALIB_RATIONAL_MODEL` | shape=(1,14) | `[:, :8]` → shape=(1,8) |
| `"normal"` | `0` | shape=(1,5) | トリム不要 → shape=(1,5) |

#### 処理ロジック（擬似コード）

```
1. lens_model が "normal"/"wide" 以外なら ValueError(f"Unknown lens_model: {lens_model}") を送出
2. MIN_CAPTURES チェック（既存のまま）
3. flags = CALIB_RATIONAL_MODEL if lens_model == "wide" else 0
4. cv2.calibrateCamera(..., flags=flags)
5. dist_coeffs = dist_coeffs[:, :8]  # wide: 14→8 トリム。normal: (1,5) なのでスライスは無変化（5 < 8）
6. 以降は既存のまま（per_image_errors 計算、CalibrationResult 返却）
```

設計判断: ステップ5の `[:, :8]` は normal 時も無害（numpy スライスは範囲超過しても要素数までしか取らない）なので分岐を設けず共通化する。コメントで両モデルの挙動を明記する。

却下案: `flags: int` を直接引数にする案 — 呼び出し側が OpenCV フラグの知識を要するため却下。`"normal"`/`"wide"` の語彙はプロジェクト用語（requirements.md 1.2）と一致させる。

#### エラーハンドリング

| エラー | 検出 | 処理 | ログ |
|---|---|---|---|
| 不正な lens_model | calibrate() 冒頭の文字列比較 | `ValueError` 送出（リトライなし） | なし（例外メッセージで十分） |
| キャプチャ不足 | 既存の MIN_CAPTURES チェック | `ValueError`（既存のまま） | 既存のまま |
| cv2.error | calibrateCamera 内部 | 呼び出し元へ伝播（既存のまま） | 既存のまま |

既存の `logger.info("Calibration done: ...")` に `lens_model` を追記する:
`"Calibration done: RMS=%.4f px, %d images, model=%s"`。

#### 境界条件

- normal 時 `dist_coeffs` shape=(1,5): `_compute_per_image_errors()` の `cv2.projectPoints()` は5要素の dist_coeffs を正式サポートするため変更不要。
- docstring / `CalibrationResult.dist_coeffs` のコメント（`calibration_engine.py` 内 dataclass フィールド `dist_coeffs` の `# shape=(1,8), float64`）を `shape=(1,5) or (1,8)` に更新する。

### 1.4.3 エクスポート（FR-003）— 変更不要

`calibration_exporter.py` は `result.dist_coeffs.flatten()` で全要素を列挙するため、係数長に自動追従する:

- TOML: `distortions = [...]` が5要素（normal）/ 8要素（wide）
- JSON: `"dist_coeffs"` が5要素 / 8要素

**コード変更なし。** 単体テストで5要素入力時の出力配列長を検証する（1.9 参照）。

### 1.4.4 結果表示（FR-004）

`offline_calibration.py` の歪み係数表示部（`labels = [...]` 定義とその直後の `for` ループ。行番号は変動しうるためシンボルで特定すること）:

```python
labels = ["k1", "k2", "p1", "p2", "k3", "k4", "k5", "k6"]
for label, val in zip(labels, d):   # zip は短い側で打ち切られる
    print(f"  {label} = {val:.6f}")
```

既存の `zip()` が短い側（5要素の d）で打ち切るため、ラベルリストは変更不要。**変更対象はこの歪み係数ループのみ**: 未使用の `enumerate` インデックス `i` を削除する（これは FR-004 に付随する軽微なクリーンアップであり、FR-004 の受け入れ基準＝表示行数の検証対象外）。直後の per-image errors 表示ループ（`for i, err in enumerate(calib_result.per_image_errors):`）は `i` を `image {i+1:03d}` で実際に使用しているため**変更しない**。ヘッダー行 `Distortion coefficients (N coefficients):` は `dist_coeffs.shape[1]` を既に表示しており変更不要。

## 1.5 状態遷移

なし（CLI の一方向処理。GUI 変更なし）。

## 1.6 ファイル・ディレクトリ設計

- 出力ファイル名・パス規約は既存のまま: `<output_dir>/cam{serial}_intrinsics.toml` / `.json`
- TOML/JSON のキー名は変更なし。`distortions` / `dist_coeffs` の配列長のみ 5 または 8 となる

## 1.7 インターフェース定義

| モジュール | シグネチャ | 変更内容 |
|---|---|---|
| `CalibrationEngine.calibrate` | `(self, object_points_list, image_points_list, image_size, lens_model: str = "wide") -> CalibrationResult` | `lens_model` 追加（デフォルト `"wide"` で後方互換） |
| `parse_args` (offline_calibration.py) | 変更なし（Namespace に `lens` 属性が追加される） | `--lens` オプション追加 |
| `CalibrationExporter.export` | 変更なし | — |

## 1.8 ログ・デバッグ設計

- INFO: `Calibration done: RMS=%.4f px, %d images, model=%s`（既存ログにモデル名追記）
- その他のログポイントは既存のまま

## 1.9 テスト設計

`tests/test_calibration_engine.py`（既存があれば追記、なければ新規）:

1. `test_calibrate_wide_returns_8_coeffs` — 合成データで `lens_model="wide"` → dist_coeffs.shape == (1,8)
2. `test_calibrate_normal_returns_5_coeffs` — `lens_model="normal"` → dist_coeffs.shape == (1,5)
3. `test_calibrate_default_is_wide` — 引数省略 → shape == (1,8)
4. `test_calibrate_invalid_lens_model_raises` — `lens_model="fisheye"` → ValueError
   - 既存の `test_dist_coeffs_shape`（tests/test_calibration_engine.py 内、デフォルト呼び出しで (1,8) を期待）は「デフォルト=wide」の確認テストとして残置する（改名・削除しない）

注: 本設計書内の行番号参照はすべて執筆時点の目安であり、実装時はシンボル名（関数名・変数名・テスト名）で対象を特定すること。
5. `test_export_normal_5_distortions` — shape=(1,5) の CalibrationResult を export → TOML の distortions が5要素、JSON の dist_coeffs が5要素
6. `test_calibrate_normal_accuracy` — 合成データ（既知カメラ行列・歪みなし）で `lens_model="normal"` → 推定カメラ行列の fx, fy, cx, cy が既知値の±5%以内、かつ RMS < 1.0 px（normal モデルの推定精度検証。既存の `test_camera_matrix_close_to_known` / `test_rms_error_reasonable` は wide のみのため）

合成データ: 既知のカメラ行列・歪みなしで `cv2.projectPoints()` により生成した平面格子点（既存テストの方式があればそれに従う）。

テスト実行: `micromamba run -n SynchroCap pytest -v`（Subagent で実行）。結果は `tests/results/feat-019_test_result.txt` に保存する。
