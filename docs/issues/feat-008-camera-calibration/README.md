# feat-008: Camera Calibration - Live View with Board Detection

## Status: Open

## Created: 2026-03-04

## Summary

SynchroCapに新規タブ（Tab5: Calibration）を追加し、カメラ接続・ライブビュー表示・ChArUcoボード検出オーバーレイを実装する。キャリブレーション機能の第1段階。

## Scope

- SynchroCapのTab5として統合
- タブ内でのカメラ選択（ChannelRegistry連携）
- ライブビュー表示（ic4 QueueSink + 自前BayerGR8→BGR変換）
- ChArUcoボードのリアルタイム検出＋オーバーレイ描画
- ボード設定パネル（タイプ、行列数、サイズ）

## Out of Scope（後続案件で対応）

- キャプチャ機能（手動/自動）
- キャリブレーション計算（calibrateCamera）
- エクスポート（TOML/JSON）
- カバレッジヒートマップ
- セッション保存/再開

## Documents

- [要求仕様書](requirements.md)
- [機能設計書](design.md)

## References

- `src/synchroCap/mainwindow.py` - タブ追加・切り替え制御パターン
- `src/synchroCap/ui_multi_view.py` - QueueSinkListener + stream_setup パターン
- `src/synchroCap/ui_camera_settings_viewer.py` - Tab4追加時のパターン（feat-007）
- `src/synchroCap/channel_registry.py` - ChannelRegistry API
- `src/synchroCap/device_resolver.py` - find_device_for_entry()
