# feat-001: フレームタイムスタンプのCSV記録

## Status: Closed (2026-02-06)

## Summary

録画中に取得したフレームごとのメタデータ（frame_number, device_timestamp_ns）を
カメラごとのCSVファイルに記録する機能を追加する。

## Requirements

### 記録項目
| 項目 | 形式 | 例 |
|-----|------|-----|
| frame_number | 5桁ゼロ埋め文字列 | "00001" |
| device_timestamp_ns | ナノ秒整数 | 1770341767841840901 |

### 出力先
- ルート: `captures/`
- ディレクトリ: `captures/${YYYYMMDD-hhmmss}/`
- ファイル: `captures/${YYYYMMDD-hhmmss}/cam<serial>.csv`

### 出力例
```
captures/20260101-010101/
├── cam05520125.mp4
├── cam05520125.csv   ← 新規追加
├── cam05520126.mp4
├── cam05520126.csv   ← 新規追加
...
```

### CSVフォーマット
```csv
frame_number,device_timestamp_ns
00001,1770341767841840901
00002,1770341767875173901
00003,1770341767908506901
...
```

## Reference Implementation

- `dev/tutorials/10_csv_continuity/s10_rec4cams.py`
  - `record_raw_frames()` 関数内のCSV出力処理

## Affected Files

- `src/synchroCap/recording_controller.py`

## Implementation Notes

（実装メモをここに記録）
