# inv-002 要求仕様書: device_timestamp_ns の意味の切り分け

対象: `tools/timestamp_test.py`
スコープ: device_timestamp_ns が露光タイムライン上のどの時点を指すかの切り分け実験

> **注意**
> - 本文は「要求仕様」のみを記述する。
> - 実装コードは一切含めない。

---

## 1. 目的と成功条件

### 1.1 目的

DFK33GR0234 (GigE Vision) カメラの `ImageBuffer.MetaData.device_timestamp_ns` が
露光開始・露光終了・読み出し完了のどれを指すかを、ソフトウェアトリガーと
TIMESTAMP_LATCH を使った時刻比較で特定する。

### 1.2 成功条件

以下の値を同一フレームについて取得し、比較結果を表示できること:

| 記号 | ソース | 意味 |
|------|--------|------|
| T0 | `TIMESTAMP_LATCH_VALUE` (TriggerSoftware 直前に取得) | トリガー発行時刻の近似値 |
| C | `ImageBuffer.meta_data.device_timestamp_ns` | フレームメタデータのタイムスタンプ |
| E | `ExposureTime` (設定値) | 露光時間 |

C - T0 と E の関係から、`device_timestamp_ns` が露光タイムラインのどの時点を表すかを判定できること。

### 1.3 期待される判定パターン

| パターン | C - T0 の大きさ | 解釈 |
|---------|----------------|------|
| C ≒ T0 | ≒ 0 ms | device_timestamp_ns は露光開始時刻 |
| C ≒ T0 + E | ≒ 100 ms | device_timestamp_ns は露光終了時刻 |
| C > T0 + E | > 100 ms | device_timestamp_ns は読み出し完了時刻 |

---

## 2. 実験条件

### 2.1 カメラ設定

| パラメータ | 値 | 備考 |
|-----------|-----|------|
| TriggerMode | On | — |
| TriggerSelector | FrameStart | — |
| TriggerSource | Software | ソフトウェアトリガー固定 |
| ExposureAuto | Off | — |
| ExposureTime | 100,000 μs | 100ms。開始と終了の差を大きくするため |

### 2.2 トリガーモード

ソフトウェアトリガーのみ (`TriggerSoftware` コマンド実行)。
ハードウェアトリガーは物理信号が使用不可のためサポートしない。

### 2.3 撮影枚数

- デフォルト: 3枚
- `--frames N` オプションで変更可能

---

## 3. 機能要件

### 3.1 トリガー時刻の取得

ソフトウェアトリガー (`TriggerSoftware`) 発行直前に `TIMESTAMP_LATCH` を実行し、
`TIMESTAMP_LATCH_VALUE` (ns) をトリガー発行時刻の近似値 (T0) として記録する。

本番コード (`recording_controller.py`, `chktimestat.py`) と同じ
`TIMESTAMP_LATCH` → `TIMESTAMP_LATCH_VALUE` パターンを使用する。

### 3.2 フレームタイムスタンプ取得

`QueueSink` でフレームを受信し、`ImageBuffer.meta_data.device_timestamp_ns` を記録する (= C)。

### 3.3 結果出力

各フレームについて以下をコンソールに表示する:

```
--- Frame #1 (frame_number=N) ---

  T0 (トリガー直前 LATCH):      {t0} ns
  C  (device_timestamp_ns):      {c}  ns
  E  (ExposureTime):             {e}  ns ({e_ms} ms)

  C - T0          = {diff} ns  ({diff_ms} ms)
  C - T0 - E      = {diff2} ns ({diff2_ms} ms)

  → device_timestamp_ns は {判定結果} を表す
```

複数フレーム取得時はサマリ (平均・最小・最大) も表示する。

---

## 4. CLI インターフェース

### 4.1 コマンド体系

```
python timestamp_test.py [OPTIONS]
```

### 4.2 オプション

| オプション | 型 | デフォルト | 説明 |
|-----------|-----|-----------|------|
| `--frames` | int | 3 | 取得フレーム数 |
| `--timeout` | float | 15.0 | フレーム待ちタイムアウト (秒) |
| `--exposure` | float | 100000.0 | 露光時間 (μs) |

### 4.3 終了コード

| コード | 意味 |
|-------|------|
| 0 | 正常終了 |
| 1 | IC4 エラー |
| 130 | ユーザーによる中断 (Ctrl+C) |

---

## 5. エラーハンドリング要件

### 5.1 カメラ未接続

カメラが見つからない場合はエラーメッセージを出力して終了する。

### 5.2 TIMESTAMP_LATCH 未サポート

`TIMESTAMP_LATCH` が動作しない場合は、エラーメッセージを出力して終了する。

### 5.3 フレーム待ちタイムアウト

指定秒数 (`--timeout`) 以内にフレームが到着しない場合は、
タイムアウトメッセージを出力して次のフレームまたは結果出力に進む。

### 5.5 IC4 Property オブジェクトのライフサイクル管理

`with ic4.Library.init_context():` ブロックの終了時に、IC4 SDK が内部で生成した
全 `Property` オブジェクトの参照が解放されていること。

解放されていない場合、Python GC がブロック終了後に `Property.__del__` を呼び出し、
`Library.init was not called` RuntimeError が大量に発生する（機能には影響しないが、
出力が汚染されて正常終了かどうかの判断が困難になる）。

**対象となる Property オブジェクトの生成源**:

| 生成源 | 生成数 | 説明 |
|--------|--------|------|
| `prop_map.set_value()` / `get_value_*()` 内部 | 呼び出し回数分 | SDK 内部で一時的に Property オブジェクトが生成される可能性がある |

**要件**: ブロック終了前に `gc.collect()` を呼び出すか、IC4 操作を行う関数のスコープを
分離して、ローカル変数の Property 参照が `with` ブロック内で確実に破棄されること。
終了時に `Property.__del__` エラーが一切出力されないこと。

---

## 6. 非要件

- 本番アプリ (SynchroCap) のコード変更は行わない
- 複数カメラの同時テストは不要 (1台で十分)
- テスト結果のファイル保存機能は不要 (コンソール出力のみ)
- PTP 同期は不要 (単体カメラのテスト)

---

## 7. 依存関係

- imagingcontrol4 (IC4 Python SDK)
- Python 3.x 標準ライブラリ (argparse, time, gc)
- micromamba 環境 `SynchroCap`
