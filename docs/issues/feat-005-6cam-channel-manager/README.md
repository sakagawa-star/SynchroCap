# feat-005: Channel Managerの6カメラ対応

## Status: Closed (対応不要 2026-02-11)

## Summary

本番アプリのChannel Manager（Tab 1）を4チャンネルから6チャンネルに拡張し、最大6台のカメラを登録可能にする。

## Background

現状の本番アプリはカメラ同時4台の仕様となっている。これを6台まで対応可能にする。タブ毎に開発を分けて対応し、本件はChannel Manager（Tab 1）を対象とする。

## 調査結果

コード調査の結果、Channel Manager（Tab 1）は既に6台以上の登録に対応済みであることが判明した。

- `channel_registry.py`: チャンネルID 1〜99を受け付け、登録数の上限なし
- `ui_channel_manager.py`: テーブルは動的にサイズ変更、SpinBoxは1〜99の範囲

4チャンネル制限はMulti View（Tab 3）の `ui_multi_view.py` にのみ存在する。

## 結論

Channel Manager（Tab 1）は変更不要。クローズ。
