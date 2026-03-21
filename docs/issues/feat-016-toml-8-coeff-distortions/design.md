# feat-016: TOML Export — 8-Coefficient Distortions 機能設計書

## 1. 対応要求マッピング

| 要求ID | 設計セクション |
|--------|---------------|
| FR-001 | 4.1 _build_toml() 変更 |
| FR-002 | 4.2 export() シグネチャ不変の確認 |

## 2. システム構成

### 変更対象ファイル

| ファイル | 変更内容 |
|----------|----------|
| `src/synchroCap/calibration_exporter.py` | `_build_toml()` の distortions 出力行を変更 |
| `tests/test_calibration_exporter.py` | TOML 出力に関するアサーションを 8 要素に修正 |

### 変更不要ファイル

| ファイル | 理由 |
|----------|------|
| `src/synchroCap/ui_calibration.py` | `export()` シグネチャが変わらないため |
| `src/synchroCap/calibration_engine.py` | 出力側の変更であり、計算エンジンは無関係 |
| `tools/offline_calibration.py` | `CalibrationExporter.export()` を呼ぶだけのため |

## 3. 技術スタック

変更なし。既存の Python 3.10 + 標準文字列フォーマットのみ。

## 4. 各機能の詳細設計

### 4.1 _build_toml() 変更（FR-001）

#### データフロー

- **入力**: `result.dist_coeffs` — numpy.ndarray, shape=(1,8), dtype=float64
- **中間**: `d = result.dist_coeffs.flatten()` — numpy.ndarray, shape=(8,), dtype=float64（既存コードで実行済み）
- **出力**: TOML 文字列内の `distortions = [v0, v1, v2, v3, v4, v5, v6, v7]`（各値は `:.4f` フォーマット）

#### 処理ロジック

現在の実装（変更前）:
```python
lines.append(
    f"distortions = [{d[0]:.4f}, {d[1]:.4f}, {d[2]:.4f}, {d[3]:.4f}]"
)
```

変更後:
```python
dist_vals = ", ".join(f"{v:.4f}" for v in d)
lines.append(f"distortions = [{dist_vals}]")
```

`d` は `result.dist_coeffs.flatten()` で得られる shape=(8,) の配列。ループで全要素をフォーマットするため、要素数のハードコードが不要になる。

#### エラーハンドリング

- `dist_coeffs` の shape は CalibrationEngine が常に (1,8) を保証するため、追加の検証は行わない

#### 境界条件

- dist_coeffs の値がゼロの場合: `0.0000` として出力される（正常動作）

### 4.2 export() シグネチャ不変の確認（FR-002）

`export()` メソッドのシグネチャ:
```python
def export(self, result, serial, image_size, num_images, output_dir) -> list[Path]:
```

変更は `_build_toml()` 内部のフォーマット文字列のみであり、`export()` のシグネチャ・戻り値・呼び出し規約に変更はない。

## 5. ファイル・ディレクトリ設計

変更なし。出力ファイル名・パス規約は既存のまま。

TOML 出力例（変更後）:
```toml
[cam05520125]
name = "cam05520125"
size = [1920.0, 1080.0]
matrix = [[1177.4390, 0.0000, 956.5244], [0.0000, 1177.9494, 494.7850], [0.0000, 0.0000, 1.0000]]
distortions = [-1.8931, 4.5973, -0.0056, -0.0028, -4.5187, -1.8562, 4.5295, -4.4902]
rotation = [0.0, 0.0, 0.0]
translation = [0.0, 0.0, 0.0]
fisheye = false

[metadata]
adjusted = false
error = 0.3346
```

## 6. インターフェース定義

公開インターフェースの変更なし。

## 7. ログ・デバッグ設計

変更なし。既存の `logger.info("TOML written: %s", toml_path)` がそのまま有効。

## 8. テスト修正

### test_calibration_exporter.py

`TestBuildToml.test_distortions_4_elements` を以下のように変更:

**変更前**: 4 要素であること、k3〜k6 が含まれないことを検証
**変更後**: 8 要素であること、k3〜k6 の値が含まれることを検証

テスト名も `test_distortions_8_elements` に変更する。

検証内容:
- `distortions = [-0.0812, 0.1243, -0.0003, 0.0001, 0.0056, 0.0012, -0.0034, 0.0078]` が TOML 文字列に含まれること

## 9. 設計判断

### 採用案: dist_coeffs の全要素をループでフォーマット

`", ".join(f"{v:.4f}" for v in d)` により、要素数のハードコードを排除。dist_coeffs の shape が将来変わっても対応可能。

### 却下案: インデックスを 0〜7 にハードコード

```python
f"distortions = [{d[0]:.4f}, {d[1]:.4f}, ..., {d[7]:.4f}]"
```

動作上は等価だが、要素数がコードに埋め込まれるため保守性が劣る。
