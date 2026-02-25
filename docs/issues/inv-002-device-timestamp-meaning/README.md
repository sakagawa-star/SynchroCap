# inv-002: device_timestamp_ns の意味の切り分け

## Status: Closed (2026-02-25)

## Summary

DFK33GR0234 (GigE Vision) カメラの `ImageBuffer.MetaData.device_timestamp_ns` が
露光開始・露光終了・読み出し完了のどれを指すかを実験的に切り分ける。

## Background

- SynchroCapでは `device_timestamp_ns` をフレームタイムスタンプとしてCSVに記録し、カメラ間同期精度の評価に使用している
- しかし `device_timestamp_ns` が露光のどの時点を指すかが公式ドキュメントで明確にされていない
- カメラ販売元（アルゴ）から Line1 イベントタイムスタンプとの比較による切り分け手順を教示された
- タイムスタンプの正確な意味を把握することで、同期精度評価の信頼性を向上させる

## Approach

ソフトウェアトリガーと TIMESTAMP_LATCH を使って `device_timestamp_ns` の意味を判定する:

| 記号 | ソース | 意味 |
|------|--------|------|
| T0 | `TIMESTAMP_LATCH_VALUE` (TriggerSoftware 直前) | トリガー発行時刻の近似値 |
| C | `ImageBuffer.meta_data.device_timestamp_ns` | フレームメタデータ |
| E | `ExposureTime` (設定値) | 露光時間 |

C - T0 と E の関係から `device_timestamp_ns` の意味を判定する。

## Test Environment

- カメラ: DFK33GR0234 (GigE Vision, 1台)
- SDK: imagingcontrol4 (IC4 Python SDK)
- トリガー: ソフトウェアトリガー
- 露光時間: 100ms (長めに設定して開始と終了の差を大きくする)
- スクリプト: `tools/timestamp_test.py`

## Related Issues

- [feat-001](../feat-001-csv-frame-timestamp-logging/): フレームタイムスタンプのCSV記録

## Related Documents

- [requirements.md](requirements.md) - 要求仕様書
- [design.md](design.md) - 機能設計書
