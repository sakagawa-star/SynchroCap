# feat-018: Raw→MP4 エンコード品質改善

## Status: Closed

## 概要

`tools/raw_tool.py` の `encode` サブコマンドで生成されるMP4ファイルの画質が低い。
現在のffmpegエンコードオプション（CBR 2200kbps, preset p4）を見直し、高品質なMP4を出力できるようにする。

## 背景

- feat-003 Step 3 で実装されたエンコード機能は「とりあえず動画にできればよい」という位置づけだった
- 産業用カメラの映像に対して 2.2Mbps は極端に低いビットレート
- ファイル容量の増加は許容する

## 関連案件

- feat-003: Raw File Toolkit（元の実装）
- feat-002: Raw File Recording（SRAWフォーマット仕様）
