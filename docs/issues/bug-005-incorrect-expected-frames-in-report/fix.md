# bug-005 修正: Recording Reportのexpected値計算

## 要件定義

### 概要

Recording Reportで表示されるexpected（期待フレーム数）の計算に`slot.fps`ではなく`slot.trigger_interval_fps`を使用するよう修正する。

### 要求仕様

| ID | 要求 |
|----|------|
| REQ-01 | expectedの計算に`slot.trigger_interval_fps`を使用する |
| REQ-02 | deltaは「Action Schedulerで期待されるフレーム数との差」を表す |

---

## 機能設計

### 変更対象ファイル

| ファイル | 変更種別 | 内容 |
|---------|---------|------|
| `src/synchroCap/recording_controller.py` | 修正 | expected計算式の変更 |

### 変更詳細

#### 変更箇所: `_cleanup()` (612行目)

#### 変更前

```python
expected = int(self._duration_s * slot.fps)
```

#### 変更後

```python
expected = int(self._duration_s * slot.trigger_interval_fps)
```

### 動作確認

1. trigger_interval_fps=30で録画を実行
2. 録画終了後のRecording Reportを確認
3. expected = duration × 30 となっていることを確認
4. deltaが実際のフレーム数との差を正しく表示していることを確認
