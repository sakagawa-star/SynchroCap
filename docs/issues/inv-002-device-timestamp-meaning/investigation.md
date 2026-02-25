# inv-002 調査メモ

## 作業ログ

### 2026-02-25: スクリプト作成・初回テスト

#### 作成物
- `tools/timestamp_test.py` — タイムスタンプ比較実験スクリプト

#### バグ修正済み

**修正1: `alloc_and_queue_buffers` と `stream_setup` の呼び出し順序**
- 症状: `ErrorCode.SinkNotConnected: 38` — Sink が接続されていない状態でバッファ割当
- 原因: `sink.alloc_and_queue_buffers(10)` を `grabber.stream_setup(sink)` より前に呼んでいた
- 修正: 268-269行目の順序を入れ替え (`stream_setup` → `alloc_and_queue_buffers`)
- 参考: `recording_controller.py:526-530` の正しいパターンに合わせた
- 検証: ストリーム開始成功、トリガー待ちまで正常到達を確認

**修正2: `GevTimestampTickFrequency` が取得できない** ✔ 修正済み
- 症状: `get_value_int` / `get_value_float` 両方失敗 → `タイムスタンプ単位は不明` と表示
- 影響: イベントタイムスタンプ (tick) を ns に変換できず、`device_timestamp_ns` との比較不可
- 調査結果:
  - 本番コード (`recording_controller.py`, `chktimestat.py`) は `GevTimestampTickFrequency` を一切使用していない
  - 代わりに `TIMESTAMP_LATCH` → `TIMESTAMP_LATCH_VALUE` (ns) パターンでタイムスタンプを取得
  - DFK33GR0234 では全タイムスタンプが ns 単位で統一されている可能性が高い
- 修正内容:
  - `TIMESTAMP_LATCH_VALUE` を参照点として取得する `_get_latch_timestamp_ns()` を追加
  - 3段階フォールバック: (1) GevTimestampTickFrequency → (2) LATCH との桁数比較 → (3) ns 仮定
  - `_print_results()` の `_to_ns()` を `event_unit` ベースに変更し、ns 仮定時は raw 値をそのまま返す
  - デバッグ用: tick_freq 取得不可時に `prop_map.all` で関連プロパティ名を列挙

**修正3: `Library.init was not called` GC時エラー群** — `del` による修正済み、`gc.collect()` 未実装
- 症状: スクリプト終了時に `Property.__del__` で `Library.init was not called` RuntimeError が約100回出力
- 原因: `del` でトップレベルオブジェクト (`grabber`, `prop_map` 等) を解放しても、SDK 内部で生成された `Property` オブジェクト（特に `prop_map.all` イテレーション由来の約100個）が Python GC 管理下に残る。`with` ブロック終了後に GC が走ると、Library が既に shutdown されておりエラーになる。
- 実施済み修正: `init_context` ブロック終了前に `del` で明示的に全 IC4 オブジェクトの参照を解放
  - 正常終了パス: `_print_results()` 後に `del tokens, sink, listener, prop_map, grabber, dev, devices`
  - 早期リターン (イベント未サポート): `grabber.device_close()` 後に `del prop_map, grabber, dev, devices`
  - 早期リターン (デバイスなし): `del devices`
- **未実施**: `del` の後に `gc.collect()` を呼び出して SDK 内部 Property を強制回収する処理
  - 要求仕様書セクション 5.5、機能設計書セクション 8.4 に仕様を追記済み

#### 実機テスト結果

**テスト1 (修正1のみ適用)**: ストリーム開始成功、トリガー待ちタイムアウト（物理トリガー未入力のため想定通り）

**テスト2 (修正1+2+3(del のみ) 適用)**: ハードウェアトリガーモードで実行
- スクリプト本体は正常動作（ストリーム開始→トリガー待ちタイムアウト→結果出力まで完了）
- 結果出力後に `Property.__del__` エラーが約100回出力 → `gc.collect()` 未追加のため
- フレーム取得は物理トリガー未入力のためタイムアウト（想定通り）

### 2026-02-25: ソフトウェアトリガー専用化

#### 変更理由
ハードウェアトリガー（Line1 物理信号入力）が物理的に使用不可のため、
スクリプトをソフトウェアトリガー専用に全面改修。

#### 変更内容
- **測定方式の変更**: Line1 イベント比較 → TIMESTAMP_LATCH + 露光時間方式
  - T0 = TIMESTAMP_LATCH (TriggerSoftware 直前) でトリガー時刻を近似取得
  - C - T0 と ExposureTime (E) の関係から判定
- **削除**: EventRecord, _enable_event, _register_event_callback, _estimate_event_unit, threading 関連
- **削除**: `--software-trigger` CLI引数（常にソフトウェアトリガー）
- **追加**: LATCH 動作確認 (ストリーム開始前にテスト)
- **gc.collect()**: 修正3 の残作業も完了（3箇所に追加）
- **デフォルト frames**: 1 → 3 に変更
- **要求仕様書・設計書**: 新方式に合わせて更新

## 次のステップ

1. 実機テスト: `python timestamp_test.py --frames 3 --exposure 100000`
2. 結果に基づいて `device_timestamp_ns` の意味を判定
