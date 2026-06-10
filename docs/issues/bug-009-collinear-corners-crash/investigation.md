# bug-009: 調査・修正計画

## イテレーション1 (2026-06-10)

## 1.1 不具合の特定

### 対応する要求ID

- **feat-008 FR-004**（ChArUco検出・オーバーレイ表示）
  - 受け入れ基準（抜粋）: 「検出コーナー数が6未満の場合は検出失敗として扱い、オーバーレイは表示しない」
  - 検出成功の判定基準が**コーナーの数のみ**であり、コーナーの幾何学的配置（共線）を
    考慮していない。FR-004の意図は「キャリブレーションに使用できる検出結果のみを
    成功として扱う」ことであり、キャリブレーション計算をクラッシュさせる検出結果が
    成功として通過するのは要求の意図に反する
- **feat-011**（キャリブレーション計算）requirements.md 5.4 は最小キャプチャ数4を規定するが、
  個々のキャプチャの幾何学的有効性は規定していない

本不具合は「要求仕様の受け入れ基準の不備（数のみで配置を未考慮）」に起因するため、
修正に併せて feat-008 の要求仕様書・機能設計書の変更案を提示する（セクション1.3参照）。

### 対応する設計セクション

- feat-008 design.md「4. 検出エンジン」ChArUco検出手順（design.md:438-440）:
  - 手順4: 「コーナー数 < 6 の場合: `success=False, failure_reason="Detected only {n} corners (minimum: 6)"`」
  - 手順5: 「コーナー数 >= 6 の場合: `success=True`」
  - 共線判定の手順が存在しない

### 現在の動作

再現手順は `README.md` を参照。要約:

1. ChArUcoボードの1列分（6コーナー）だけが検出された画像が、最小コーナー数6を
   ちょうど満たして検出成功となる
2. その object_points / image_points が `CalibrationEngine.calibrate()` →
   `cv2.calibrateCamera()` に渡される
3. `CALIB_USE_INTRINSIC_GUESS` なしの場合、OpenCV内部の `initIntrinsicParams2D` が
   画像ごとにホモグラフィを計算するが、共線点群では退化してホモグラフィが空になり、
   `CV_Assert(matH0.size() == Size(3, 3))` で `cv2.error` が送出される（プロセスはエラー終了）

### 期待する動作

- キャリブレーションに使用できない共線配置の検出結果は、コーナー数不足と同様に
  **検出失敗として扱われる**こと
- その結果、オフラインツールでは該当画像が理由付きでスキップされ、
  アプリ本体（Tab5）では該当フレームがキャプチャ対象にならず、
  `cv2.calibrateCamera()` がクラッシュしないこと

## 1.2 原因分析

### 原因箇所

- ファイル: `src/synchroCap/board_detector.py`
- 関数: `BoardDetector._detect_charuco()`
- 該当コード（board_detector.py:142-151）:

  ```python
  n = len(charuco_corners)
  if n < 6:
      return DetectionResult(
          success=False, ...
          failure_reason=f"Detected only {n} corners (minimum: 6)",
      )
  ```

### 原因の説明

検出成功の判定が「コーナー数 >= 6」のみで、コーナーが張る2次元空間のランクを
検査していない。5x7ボードの内部コーナーグリッドは4x6であり、**1列分がちょうど6コーナー**
のため、ボード端の1列だけが画角に入ると「6点・完全共線」の検出結果が成功として通過する。

共線点群では物体平面→画像平面のホモグラフィが一意に定まらない（自由度不足）ため、
`cv2.findHomography` は失敗し（実データで `None` を返すことを確認済み）、
`cv2.calibrateCamera()` 内部の `initIntrinsicParams2D` の assertion に落ちる。

### 根本原因 or 表面的原因

**根本原因**である。検出結果の有効性判定（BoardDetector）が、その結果の唯一の用途である
キャリブレーション計算で使用可能であることを保証していないことが本質。
本判定が検査するのは、クラッシュの直接原因である共線配置
（`cv2.findHomography` が `None` を返す退化配置）である。

検出経路は以下の全てで共有されるため、`BoardDetector` での修正が全経路を保護する:

- `tools/offline_calibration.py`（今回の発生箇所）— 検出失敗画像は理由付きでスキップされる既存ロジックあり
- `src/synchroCap/ui_calibration.py`（Tab5）— 安定検出トリガーは検出成功フレームのみキャプチャする

`CalibrationEngine.calibrate()` 側での防御的チェックは行わない（理由はセクション1.3「変更しないファイル」参照）。

## 1.3 修正内容

### 変更対象ファイル

#### (1) `src/synchroCap/board_detector.py`

共線判定をヘルパメソッド `_is_collinear()` として追加し、`_detect_charuco()` の
object_points 抽出後（最小コーナー数チェック通過後）から呼び出す
（ヘルパ切り出しは単体テストで判定ロジックを直接検証可能にするため）:

```python
@staticmethod
def _is_collinear(obj_points: numpy.ndarray) -> bool:
    """object_points (N,1,3) が共線配置かを判定する。

    共線点群はホモグラフィを定義できず cv2.calibrateCamera() の
    内部初期推定 (initIntrinsicParams2D) をクラッシュさせる。
    中心化した2Dボード座標のSVDの特異値比で判定する。
    """
    obj_2d = obj_points.reshape(-1, 3)[:, :2].astype(numpy.float64)
    centered = obj_2d - obj_2d.mean(axis=0)
    sv = numpy.linalg.svd(centered, compute_uv=False)
    return sv[0] <= 0.0 or sv[1] / sv[0] < BoardDetector.COLLINEARITY_RATIO_MIN
```

`_detect_charuco()` 側の呼び出し:

```python
if self._is_collinear(obj_points):
    return DetectionResult(
        success=False,
        image_points=charuco_corners,
        object_points=None,
        charuco_ids=charuco_ids,
        num_corners=n,
        failure_reason=f"Corners are collinear ({n} corners on a line)",
    )
```

- クラス定数 `COLLINEARITY_RATIO_MIN: float = 1e-6` を追加する
- 判定方式: object_points（ボード座標系の正確な格子座標。検出ノイズなし）の
  2D成分を float64 に変換・中心化し、SVDの特異値比 `sv[1]/sv[0]` で判定する
  - float64 変換の理由: object_points は float32（機械イプシロン ≈ 1.2e-7）であり、
    大きなボードでは丸め誤差の蓄積が閾値 1e-6 に近づき得る。float64 で計算すれば
    共線時の比は 1e-16 オーダーとなり、閾値との余裕が無条件に成立する
  - 共線（縦・横・斜めすべて）: 比 ≈ 0（float32 のままでの実測: capture_041 で
    3.7e-8 / 1.4e-1 ≈ 2.6e-7。float64 化でさらに小さくなる）
  - 非共線（最低2列2行に分散）: 比はボード格子間隔オーダー（実測: 8点2列の capture_007 で
    4.1e-2 / 1.4e-1 ≈ 0.29。非共線の最小ケースでも 0.2 以上）
  - 両者は5桁以上離れており、閾値 1e-6 で誤判定しない
- `sv[0] <= 0.0` ガード: 全点同一座標の場合 `sv[1]/sv[0]` がゼロ除算になるための防御
  （ChArUco IDは一意で格子座標は相異なるため実際には発生しないが、防御として置く）
- 検出失敗時の戻り値構成（image_points / charuco_ids を保持、object_points=None）は
  既存のコーナー数不足時（board_detector.py:144-151）と同一形式に揃える

チェッカーボード検出（`_detect_checkerboard()`）には追加しない。
`cv2.findChessboardCorners` は全コーナー（4x6格子全体）の検出が成功条件であり、
共線になり得ないため。

#### (2) `docs/issues/feat-008-camera-calibration/requirements.md`（変更案）

FR-004 受け入れ基準に追記:

> 検出コーナー数が6未満の場合は検出失敗として扱い、オーバーレイは表示しない。
> **また、検出コーナーが全て一直線上に並ぶ場合（共線配置）も、キャリブレーション計算に
> 使用できないため検出失敗として扱う。**

#### (3) `docs/issues/feat-008-camera-calibration/design.md`（変更案）

「4. 検出エンジン」ChArUco検出手順の手順4と5の間に挿入:

> 4b. コーナー数 >= 6 だが全コーナーが共線の場合（`_is_collinear()`: float64 に変換・
> 中心化した2Dボード座標のSVD特異値比 `sv[1]/sv[0] < 1e-6`）:
> `success=False, failure_reason="Corners are collinear ({n} corners on a line)"`

#### (4) `tests/test_board_detector.py`（新規作成）

セクション1.5「自動テスト」参照。

### 変更しないファイル

- **`src/synchroCap/calibration_engine.py`**: 検出層（BoardDetector）での修正が
  全呼び出し経路（オフラインツール・Tab5）を保護するため、エンジン側の重複チェックは
  追加しない。BUGFIX_STANDARD 2.3（スコープの限定）に従う。
  エンジンに到達する点群は全て BoardDetector を通過したものである。
  feat-013（セッション保存/再開）は Board Settings（5項目のJSON）のみを永続化し、
  キャプチャデータ（検出結果）は永続化しない（feat-013 requirements.md スコープ外に明記。
  実コードも `board_settings_store.py` は設定5項目のみ、検出結果はメモリ内
  `self._captures` のみ）。よって保存済みデータ経由で共線キャプチャがエンジンに
  到達する経路は存在しない。唯一の永続化経路は Save ボタンの生フレームPNG保存 →
  `offline_calibration.py` での再検出であり、再検出は修正後の BoardDetector を通るため保護される
- **`tools/offline_calibration.py`**: 検出失敗画像のスキップ・理由表示ロジックは
  実装済み（offline_calibration.py:202-204, 211-214）。BoardDetector の修正だけで
  該当画像が `Skipped ... Corners are collinear` と表示されるようになる
- **`src/synchroCap/ui_calibration.py`**: 安定検出トリガーは検出成功フレームのみを
  対象とするため、BoardDetector の修正だけで共線フレームのキャプチャが防止される

### 修正が設計書に沿っているか

feat-008 design.md の検出手順に共線判定が存在しないため、**設計書の変更が必要**。
変更案は上記 (2)(3) の通り（BUGFIX_STANDARD 2.2 に従い、コードのみの変更は行わない）。

### スコープ外（調査中に発見した別問題）

`tools/offline_calibration.py` は `--focal-mm` / `--pixel-pitch-mm` を
`--use-spec-guess` なしで渡しても警告なく無視する（今回の発生時のコマンドラインで
実際に起きた）。BUGFIX_STANDARD 2.3 に従い本案件では修正せず、別案件として報告する。

## 1.4 影響範囲

### 他の機能への影響

| 機能 | 影響 | 評価 |
|------|------|------|
| Tab5 ライブビュー（feat-008） | 共線検出時、オーバーレイ非表示・検出失敗ステータス表示になる | 意図した動作（使用不能な検出を成功と表示しない） |
| 自動キャプチャ（feat-009） | 共線フレームが安定検出トリガーの対象外になる | 改善（無価値なキャプチャの混入防止） |
| カバレッジヒートマップ（feat-010） | 共線検出がヒートマップに加算されなくなる | 改善（同上） |
| キャリブレーション計算（feat-011） | 入力に共線キャプチャが混入しなくなる | 本修正の目的 |
| オフラインツール（feat-019/020） | 共線画像が理由付きスキップになる | 本修正の目的 |
| チェッカーボード検出 | 変更なし | 影響なし |

### リグレッションリスク

- **正常な検出の誤棄却**: 非共線の最小ケース（2列に分散した6点）でも特異値比は
  0.1オーダーであり、閾値 1e-6 とは5桁以上の余裕がある。誤棄却のリスクは実質ゼロ
- **検出処理の速度低下**: 追加されるのは高々 N=24 点の (N,2) 行列のSVD 1回であり、
  検出処理全体（ミリ秒オーダーの detectBoard）に対して無視できる
- **失敗時戻り値の形式**: 既存のコーナー数不足ケースと同一形式のため、
  呼び出し側（ui_calibration / offline_calibration）の分岐に変更は不要

## 1.5 確認方法

### テスト項目

1. 共線配置（縦1列・横1行・斜め直線）の object_points を持つ検出結果が
   `success=False`、`failure_reason` に "collinear" を含むこと
2. 非共線の最小ケース（2列に分散した6点）が `success=True` のままであること
3. 正常なフルボード画像（合成画像）の検出が引き続き成功すること
4. 共線画像を含む実画像セットでオフラインキャリブレーションがクラッシュせず完走すること

### 自動テスト（`tests/test_board_detector.py` 新規作成）

pytest で検証可能。実カメラ不要（合成画像と直接呼び出しで構成）:

- `CharucoBoard.generateImage()` で生成したフルボード合成画像 → `detect()` が
  `success=True`、num_corners=24（テスト項目3）
- 検出経由の統合テスト（テスト項目1）: フルボード合成画像
  （`generateImage((1000,1400), marginSize=50)`）の1列分だけを残して他を白でマスクした
  画像 → `detect()` が `success=False`、`failure_reason` に "collinear" を含む
  （レビュー時に実行可能性を実証済み: 6コーナー検出 ids=[0,4,8,12,16,20]、特異値比 6.4e-8。
  なお4x6格子で共線6点が成立するのは縦1列のみ。横1行は4点で最小コーナー数6未満が先に
  発動し、斜めは最大4点のため、これらは画像経由では到達できない）
- `_is_collinear()` ヘルパの直接単体テスト（テスト項目1, 2）:
  - 縦1列（x固定6点）→ True
  - 横1行（y固定4点）→ True（検出経由では n<6 で先に弾かれるが、判定単体で検証）
  - 斜め直線（(0,0),(1,1),... 格子対角4点）→ True
  - 2列6点 → False
  - フルグリッド24点 → False
- 既存テストのリグレッション確認: `micromamba run -n SynchroCap pytest -v`（全テスト）
- テスト結果は `tests/results/bug-009_test_result.txt` に保存する

### 手動テスト

1. 発生時の実画像セット82枚（`capture_041.png` を戻した状態。削除済みの場合は
   元データから復元）に対して以下を実行する:

   ```bash
   micromamba run -n SynchroCap python tools/offline_calibration.py \
       "/media/sakagawa/T5 EVO/SynchroCap/videos/20260610-092904/intrinsics/cam05520126" \
       05520126 --lens normal --square-mm 34 --marker-mm 22
   ```

2. 確認事項:
   - クラッシュせず完走すること
   - `capture_041.png` が `Skipped` 一覧に "Corners are collinear (6 corners on a line)" と表示されること
   - `Detection: 81 / 82 images OK` となること
   - RMS再投影誤差が `capture_041.png` 手動除外時の実行結果と一致すること
3. Tab5（実機）: ボードの端1列だけを画角に入れた状態で、検出失敗ステータスになり
   自動キャプチャが発火しないこと（カメラ使用可能になった時点で確認）
