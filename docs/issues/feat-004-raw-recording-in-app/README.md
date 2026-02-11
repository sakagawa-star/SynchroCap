# feat-004: 本番アプリへのRaw形式録画機能追加

## Status: Open

## Summary

feat-002でミニマムアプリ（`dev/tutorials/12_rec_raw/s12_rec4cams.py`）に実装・検証済みのヘッダ付きRawファイル形式での録画機能を、本番アプリ（`src/synchroCap/`）に移植する。

## Background

feat-002にてSRAWフォーマットによるRaw録画の実装と検証が完了した。feat-003の検証ツールにより、SRAWフォーマットの整合性・映像内容・MP4変換の正常性が確認されている。本番アプリでもMP4形式に加えてRaw形式での録画を選択可能にする。

## Scope

- 本番アプリのMulti View（Tab 3）にOutput Format切り替えUI（MP4 / Raw）を追加
- 録画制御ロジックにRaw形式での録画パスを追加
- feat-002のミニマムアプリで検証済みの実装を移植

## GUI配置案

Recording GroupBox内に「Output Format」行を追加:

```
Recording
  Start after:    [8 sec]
  Duration:       [30 sec]
  Output Format:  (●) MP4  ( ) Raw
  Status:         Ready
  [Start] [Stop]
```

## Steps

### Step 1: 要件定義・設計

- 要求仕様書の作成
- 機能設計書の作成

### Step 2: 実装

- GUI変更（Output Format切り替え）
- 録画制御ロジックの変更
- Raw形式録画パスの追加

### Step 3: テスト

- MP4形式での録画が従来通り動作すること
- Raw形式での録画が正常に動作すること
- feat-003ツールでRawファイルを検証

## Related Documents

- [feat-002](../feat-002-raw-file-recording/) - ヘッダ付きRawファイル形式での録画対応（ミニマムアプリ）
- [feat-002 design.md](../feat-002-raw-file-recording/design.md) - SRAWフォーマット仕様
- [feat-003](../feat-003-raw-file-toolkit/) - Rawファイル検証・変換ツール
