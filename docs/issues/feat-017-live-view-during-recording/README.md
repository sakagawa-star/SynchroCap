# feat-017: Live View During Recording

## Status: Closed

## 概要
録画中もマルチビュー（Tab3）のライブビューを継続表示する。
録画開始・停止時の一時的な映像途切れは許容する。

## 背景
- 現在の設計では録画中にプレビューが停止する（シンプルさ優先の設計判断）
- IC4 SDK の `stream_setup(sink, display)` は sink と display の同時接続をサポートしている
- 録画中の映像確認ができないため、ユーザーは録画状態を視覚的に確認できない

## 影響範囲
- `src/synchroCap/recording_controller.py` — `RecordingSlot` に display フィールド追加、`_setup_recording()` で display を渡す
- `src/synchroCap/ui_multi_view.py` — `RecordingSlot` 構築時に display を渡す、録画終了時のプレビュー再開ロジック調整
