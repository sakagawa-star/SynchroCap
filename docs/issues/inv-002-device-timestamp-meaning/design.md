# inv-002 機能設計書: device_timestamp_ns の意味の切り分け

対象: `tools/timestamp_test.py`
基準文書: `requirements.md`（本ディレクトリ内）

---

## 1. 機能概要

### 1.1 機能名

device_timestamp_ns タイムスタンプ切り分け実験ツール

### 1.2 機能説明

ソフトウェアトリガーと TIMESTAMP_LATCH を組み合わせ、トリガー発行時刻 (T0) と
`device_timestamp_ns` (C) を同一フレームで取得・比較する独立スクリプト。
既知の露光時間 (E) との関係から、device_timestamp_ns が露光タイムラインの
どの時点を表すかを判定する。

---

## 2. ファイル構成

### 2.1 配置

```
tools/
└── timestamp_test.py    # 単一ファイル
```

### 2.2 外部依存

- `imagingcontrol4` (IC4 Python SDK) — カメラ制御
- Python 3.x 標準ライブラリ: `argparse`, `time`, `gc`, `dataclasses`, `sys`

---

## 3. データ構造設計

### 3.1 CollectedData

全フレームの収集結果を保持する。

```python
@dataclass
class CollectedData:
    trigger_latch_ns: list[int]    # T0: フレームごとのトリガー直前 LATCH 値 (ns)
    frame_timestamps_ns: list[int] # C: device_timestamp_ns のリスト
    frame_numbers: list[int]       # device_frame_number のリスト
    exposure_time_ns: int          # E: 露光時間 (ns)
```

---

## 4. モジュール設計

### 4.1 関数一覧

| 関数名 | 責務 |
|--------|------|
| `_try_set(prop_map, name, value)` | PropertyMap に値を安全に設定 |
| `_get_latch_timestamp_ns(prop_map)` | TIMESTAMP_LATCH → TIMESTAMP_LATCH_VALUE (ns) を取得。`chktimestat.py:203-236` と同パターン |
| `run(args)` | メイン処理（カメラ設定→ストリーム開始→フレーム取得→結果出力→クリーンアップ） |
| `_print_results(data)` | 収集結果のフォーマットと表示 |
| `main()` | CLI 引数解析とエントリーポイント |

### 4.2 QueueSink リスナー

```python
class _FrameListener(ic4.QueueSinkListener):
    def sink_connected(self, sink, image_type, min_buffers_required) -> bool:
        return True
    def sink_disconnected(self, sink) -> None:
        pass
    def frames_queued(self, sink) -> None:
        pass
```

フレーム取得はメインループの `try_pop_output_buffer()` で行うため、リスナーは接続承認のみ。

---

## 5. 処理フロー設計

### 5.1 全体シーケンス

```
main()
 └─ run(args)
     ├─ [1] カメラ設定
     │    ├─ デバイス列挙・オープン
     │    ├─ TriggerMode=On, TriggerSource=Software, ExposureTime 設定
     │    └─ TIMESTAMP_LATCH 動作確認
     │
     ├─ [2] ストリーム開始
     │    ├─ QueueSink 作成
     │    ├─ grabber.stream_setup(sink)
     │    └─ sink.alloc_and_queue_buffers(10)
     │
     ├─ [3] フレーム取得ループ (num_frames 回)
     │    ├─ T0 = TIMESTAMP_LATCH (トリガー直前)
     │    ├─ TriggerSoftware 実行
     │    ├─ try_pop_output_buffer() でフレーム待ち (タイムアウト付き)
     │    ├─ C = device_timestamp_ns を記録
     │    └─ buf.release()
     │
     ├─ [4] ストリーム停止
     │    ├─ grabber.stream_stop()
     │    └─ grabber.device_close()
     │
     ├─ [5] 結果出力
     │    └─ _print_results(collected)
     │
     └─ [6] クリーンアップ
          ├─ del sink, listener, prop_map, grabber, dev, devices
          └─ gc.collect()
```

### 5.2 フレーム取得ループの詳細

```
for i in range(num_frames):
    sleep(50ms)  # 前フレームとの間隔

    T0 = _get_latch_timestamp_ns(prop_map)  # トリガー直前の LATCH

    prop_map.execute_command(TRIGGER_SOFTWARE)

    deadline = now + timeout_sec
    while now < deadline:
        buf = sink.try_pop_output_buffer()
        if buf is not None:
            break
        sleep(1ms)

    if buf is None → タイムアウトエラー、break

    C = buf.meta_data.device_timestamp_ns
    buf.release()
```

---

## 6. 測定方式設計

### 6.1 タイムスタンプの関係

```
時間軸 →

T0          T0+?        T0+E        T0+E+R
|           |           |           |
LATCH       露光開始     露光終了     読み出し完了
(トリガー直前)

? = T0 から実際の露光開始までの遅延 (LATCH → TriggerSoftware → 露光開始)
E = ExposureTime (既知)
R = 読み出し時間 (不明だが通常数ms以下)
```

### 6.2 判定ロジック

```python
diff = C - T0        # device_timestamp_ns とトリガー時刻の差
diff_minus_e = diff - E  # 露光時間を引いた残差

if abs(diff) < 1ms:
    "露光開始 (≈トリガー時刻)"
elif abs(diff - E) < 1ms:
    "露光終了"
elif diff > E:
    "読み出し完了 (露光終了後)"
else:
    "判定困難"
```

### 6.3 T0 の精度

TIMESTAMP_LATCH は TriggerSoftware の直前に実行するため、
T0 と実際のトリガー発行時刻には数μs〜数十μsの誤差がある。
露光時間 100ms に対してこの誤差は無視できる。

---

## 7. 結果出力設計

### 7.1 フレーム単位の出力フォーマット

```
--- Frame #1 (frame_number=N) ---

  T0 (トリガー直前 LATCH):      {t0} ns
  C  (device_timestamp_ns):      {c}  ns
  E  (ExposureTime):             {e}  ns ({e_ms} ms)

  C - T0          = {diff} ns  ({diff_ms} ms)
  C - T0 - E      = {diff2} ns ({diff2_ms} ms)

  → device_timestamp_ns は {判定結果} を表す
```

### 7.2 サマリ (複数フレーム時)

```
--- サマリ ---
  C - T0 平均: {avg} ms
  C - T0 最小: {min} ms
  C - T0 最大: {max} ms
  ExposureTime: {e} ms
```

---

## 8. エラーハンドリング設計

### 8.1 カメラ未検出

```
DeviceEnum.devices() が空 → エラーメッセージ出力 → del + gc.collect() → return
```

### 8.2 TIMESTAMP_LATCH 未サポート

```
_get_latch_timestamp_ns() が None → エラーメッセージ → device_close() → del + gc.collect() → return
```

### 8.3 フレームタイムアウト

```
try_pop_output_buffer() が timeout_sec 以内に None 以外を返さない
→ タイムアウトメッセージ → break (結果出力へ進む)
```

### 8.4 IC4 オブジェクトのクリーンアップ

`with ic4.Library.init_context():` ブロック内で全 IC4 オブジェクトの作成・破棄を完結させる。

**対策**: `with` ブロック終了前に `del` で明示的に参照を解放し、
`gc.collect()` で SDK 内部 Property を強制回収する。

```
[6] クリーンアップ
 ├─ del sink, listener, prop_map, grabber, dev, devices
 └─ gc.collect()
```

**早期リターンパスの対策**:

| パス | クリーンアップ |
|------|-------------|
| カメラ未検出 | `del devices` → `gc.collect()` |
| LATCH 未サポート | `device_close()` → `del prop_map, grabber, dev, devices` → `gc.collect()` |

---

## 9. 影響範囲

### 変更対象ファイル

| ファイル | 変更種別 |
|---------|---------|
| `tools/timestamp_test.py` | 全面改修 |

### 既存機能への影響

- なし（独立したスタンドアロンスクリプト）
