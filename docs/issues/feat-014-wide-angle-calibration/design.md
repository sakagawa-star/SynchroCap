# 機能設計書: Camera Calibration - Wide-Angle Lens Support (8-coefficient model)

対象: feat-014
作成日: 2026-03-20
基準文書: `docs/DESIGN_STANDARD.md`
要求仕様書: `docs/issues/feat-014-wide-angle-calibration/requirements.md`

---

## 1. 対応要求マッピング

| 要求ID | 要求名 | 設計セクション |
|--------|--------|---------------|
| FR-001 | 8係数モデルによるキャリブレーション計算 | 4.1 |
| FR-002 | UI歪み係数表示の8係数対応 | 4.2 |
| FR-003 | JSONエクスポートの8係数対応 | 4.3 |
| FR-004 | Pose2Sim TOMLエクスポートの互換性維持 | 4.4 |

---

## 2. システム構成

### 2.1 関連ファイル

| ファイル | 役割 | 変更種別 |
|---------|------|---------|
| `src/synchroCap/calibration_engine.py` | キャリブレーション計算エンジン | **変更** |
| `src/synchroCap/ui_calibration.py` | Tab5 CalibrationWidget（歪み係数表示変更） | **変更** |
| `src/synchroCap/calibration_exporter.py` | エクスポートエンジン | **変更なし** |
| `tests/test_calibration_engine.py` | キャリブレーションエンジンテスト | **変更** |
| `tests/test_calibration_exporter.py` | エクスポーターテスト | **変更** |

### 2.2 モジュール間の依存関係

既存と同一。変更なし。

---

## 3. 技術スタック

既存と同一。新規ライブラリの追加なし。`cv2.CALIB_RATIONAL_MODEL` は opencv-contrib-python >=4.9.0 で提供されている。

---

## 4. 各機能の詳細設計

### 4.1 8係数モデルによるキャリブレーション計算（FR-001）

#### 変更箇所

`calibration_engine.py` `calibrate()` メソッド内の `cv2.calibrateCamera()` 呼び出しにフラグを追加し、戻り値の `dist_coeffs` を先頭8要素にトリミングする。

変更前:
```python
rms, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
    object_points_list,
    image_points_list,
    image_size,
    None,
    None,
)
```

変更後:
```python
rms, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
    object_points_list,
    image_points_list,
    image_size,
    None,
    None,
    flags=cv2.CALIB_RATIONAL_MODEL,
)
# cv2.CALIB_RATIONAL_MODEL returns shape=(1,14).
# Trim to first 8 coefficients (k1,k2,p1,p2,k3,k4,k5,k6).
# Remaining 6 (s1-s4, τx, τy) are thin-prism/tilted-sensor
# parameters, not enabled and always zero.
dist_coeffs = dist_coeffs[:, :8]
```

#### CalibrationResult docstring 更新

変更前（L23）:
```python
dist_coeffs: numpy.ndarray         # shape=(1,5), float64
```

変更後:
```python
dist_coeffs: numpy.ndarray         # shape=(1,8), float64
```

#### `_compute_per_image_errors()` への影響

`cv2.projectPoints()` は `dist_coeffs` の要素数に関係なく動作する（4, 5, 8, 12, 14 要素を自動判定）。8要素を渡しても正常に動作する。コード変更不要。

#### エラーハンドリング

| エラー | 検出方法 | リカバリ | ログ |
|--------|---------|---------|------|
| `cv2.calibrateCamera()` 失敗 | `cv2.error` catch | 既存と同一。呼び出し元（`ui_calibration.py`）でキャッチしステータスに表示 | WARNING |

`dist_coeffs` のトリミング `[:, :8]` は `cv2.CALIB_RATIONAL_MODEL` 指定時に shape=(1,14) が保証されるため、shape 検証は不要。

#### 境界条件

- 8係数モデルでも `cv2.calibrateCamera()` の最小キャプチャ数は4件のまま（`MIN_CAPTURES` 変更不要）
- 標準レンズ（画角60°以下）で8係数モデルを使用しても問題ない（追加パラメータ k4, k5, k6 がゼロ付近に収束する）。合成データ（歪み係数ゼロ）でも RMS=0.000011 で収束し、fx/fy が既知値と一致することを実験で確認済み

**設計判断**: フラグの固定 vs 選択
- 採用: `cv2.CALIB_RATIONAL_MODEL` を常に使用する。8係数モデルは5係数モデルの上位互換であり、標準レンズでも精度が劣化しない
- 却下: UI で5係数/8係数を切り替えるオプション（不要な複雑さ。全カメラが広角レンズのため）

**設計判断**: dist_coeffs のトリミング
- 採用: `calibrate()` 内で `dist_coeffs[:, :8]` にトリミングし、CalibrationResult には常に shape=(1,8) を格納する。下流コード（UI表示、エクスポート）が一貫して8要素を前提にできる
- 却下: shape=(1,14) をそのまま格納（下流コードが14要素中の有効な8要素を判別する必要があり、複雑化する）

### 4.2 UI歪み係数表示の8係数対応（FR-002）

#### 変更箇所

`ui_calibration.py` の `_display_calibration_result()` メソッドの歪み係数表示部分を変更する。

変更前:
```python
d = result.dist_coeffs.flatten()
self._dist_label.setText(
    f"k1={d[0]:.4f}, k2={d[1]:.4f}\n"
    f"p1={d[2]:.4f}, p2={d[3]:.4f}\n"
    f"k3={d[4]:.4f}"
)
```

変更後:
```python
d = result.dist_coeffs.flatten()
self._dist_label.setText(
    f"k1={d[0]:.4f}, k2={d[1]:.4f}\n"
    f"p1={d[2]:.4f}, p2={d[3]:.4f}\n"
    f"k3={d[4]:.4f}, k4={d[5]:.4f}\n"
    f"k5={d[6]:.4f}, k6={d[7]:.4f}"
)
```

表示は4行。左パネルのQScrollArea内のため、既存の3行から1行増加しても問題なし。

#### 境界条件

`CalibrationResult.dist_coeffs` は `CalibrationEngine.calibrate()` が常に shape=(1,8) を保証するため、`d[5]`, `d[6]`, `d[7]` のインデックスアクセスで `IndexError` は発生しない。feat-013 のセッション保存はキャリブレーション結果を保存しないため、古い5係数データとの互換性問題は発生しない。

### 4.3 JSONエクスポートの8係数対応（FR-003）

#### 変更なし

`calibration_exporter.py` の `_build_json_dict()` は `result.dist_coeffs.flatten().tolist()` で配列をそのまま変換するため、shape が (1,8) になれば自動的に8要素リストが出力される。コード変更不要。

### 4.4 Pose2Sim TOMLエクスポートの互換性維持（FR-004）

#### 変更なし

`calibration_exporter.py` の `_build_toml()` は `d[0:4]` で先頭4要素のみを取り出すため、shape が (1,8) に変わっても出力は4要素のまま。コード変更不要。

---

## 5. 状態遷移

変更なし。

---

## 6. ファイル・ディレクトリ設計

変更なし。

---

## 7. インターフェース定義

### 7.1 calibration_engine.py（変更分のみ）

`CalibrationResult.dist_coeffs` の shape が `(1,5)` → `(1,8)` に変更される。公開メソッドのシグネチャは変更なし。

### 7.2 calibration_exporter.py

変更なし。`dist_coeffs.flatten().tolist()` が8要素を返すようになるのみ。

### 7.3 ui_calibration.py（変更分のみ）

`_display_calibration_result()` の歪み係数表示が3行→4行に変更。

---

## 8. ログ・デバッグ設計

変更なし。既存のログ出力で十分。

---

## 9. テスト方針

### 9.1 単体テスト: calibration_engine.py

既存テスト `tests/test_calibration_engine.py` を更新する:

- `dist_coeffs` の shape 検証を `(1,5)` → `(1,8)` に変更する
- 合成データテスト（歪み係数ゼロ、10枚）は `CALIB_RATIONAL_MODEL` でも RMS<0.001 で収束することを確認済み。`known_dist_coeffs` の変更は不要（投影時のゼロ歪みと推定結果のゼロ付近の歪みは整合する）
- `test_camera_matrix_close_to_known` は引き続きパスする（fx/fy が既知値800.0と一致、実験確認済み）

### 9.2 単体テスト: calibration_exporter.py

既存テスト `tests/test_calibration_exporter.py` を更新する:

- テストフィクスチャ `sample_result` の `dist_coeffs` を shape=(1,5) → shape=(1,8) に変更。具体値: `[[-0.0812, 0.1243, -0.0003, 0.0001, 0.0056, 0.0012, -0.0034, 0.0078]]`（既存の5要素 + k4=0.0012, k5=-0.0034, k6=0.0078）
- `test_dist_coeffs_5_elements` → `test_dist_coeffs_8_elements` にリネーム、要素数を5→8に変更
- `test_distortions_4_elements`: フィクスチャの変更に伴い、k3〜k6 の値（`0.0056`, `0.0012`, `-0.0034`, `0.0078`）がTOMLに含まれないことも検証する

### 9.3 統合テスト: 実画像によるキャリブレーション

広角レンズ（LM3NC1M）で撮影したテスト画像37枚を使用した統合テストを `tests/test_calibration_engine.py` に追加する:

- テスト画像パス: `src/synchroCap/captures/20260318-141544/intrinsics/cam05520125/*.png`
- ボード設定: ChArUco 5x7, DICT_6X6_250, square_mm=30.0, marker_mm=22.0（アプリのデフォルト設定）
- スキップ条件: `pytest.mark.skipif(not Path("src/synchroCap/captures/20260318-141544/intrinsics/cam05520125").is_dir(), reason="Test images not available")`
- テスト内容:
  1. 37枚の画像から ChArUco ボード検出（BoardDetector をデフォルト設定で使用）
  2. 検出成功した画像の object_points / image_points で `CalibrationEngine.calibrate()` を実行
  3. RMS 再投影誤差が 1.0px 以下であることを検証
  4. `dist_coeffs` の shape が `(1,8)` であることを検証
  5. カメラ行列の shape が `(3,3)` であることを検証

### 9.4 手動テスト

- Calibrationタブで広角レンズのカメラを選択 → キャプチャ → Calibrate → 8係数の歪み係数が表示されること
- Export → JSONファイルの `dist_coeffs` が8要素であること
- Export → TOMLファイルの `distortions` が4要素のままであること
- Camera Settings タブの動作に影響がないこと（回帰確認）

---

## 10. 実装時の追加更新対象

- feat-011 機能設計書 `docs/issues/feat-011-calibration-calculation/design.md`: `CalibrationResult.dist_coeffs` のコメントを `(1,8)` に更新
- feat-012 要求仕様書: FR-003 の `dist_coeffs` を「5パラメータ」→「8パラメータ」に更新
