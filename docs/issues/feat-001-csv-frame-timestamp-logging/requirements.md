# Requirements: feat-001 フレームタイムスタンプのCSV記録

## 1. 概要

録画中に取得した各フレームのメタデータをカメラごとのCSVファイルに記録する。

## 2. 機能要件

### 2.1 記録データ

| カラム名 | データ型 | 形式 | 取得元 |
|---------|---------|------|--------|
| frame_number | string | 5桁ゼロ埋め ("00001") | `buf.meta_data.device_frame_number` |
| device_timestamp_ns | int | ナノ秒整数 | `buf.meta_data.device_timestamp_ns` |

### 2.2 出力ファイル

#### パス構成
```
captures/
└── ${YYYYMMDD-hhmmss}/
    ├── cam${serial}.mp4      # 既存の動画ファイル
    └── cam${serial}.csv      # 新規追加
```

#### 命名規則
- ディレクトリ: 録画開始時刻（既存の `_output_dir` を使用）
- ファイル名: `cam{serial}.csv`
- 例: `captures/20260206-120000/cam05520125.csv`

### 2.3 CSVフォーマット

```csv
frame_number,device_timestamp_ns
00001,1770341767841840901
00002,1770341767875173901
00003,1770341767908506901
```

- ヘッダー行: あり（1行目）
- 区切り文字: カンマ
- 改行: LF または CRLF（Python csv標準）
- エンコーディング: UTF-8

## 3. 非機能要件

### 3.1 パフォーマンス

- **バッファリング**: 毎フレーム書き込みではなく、バッファに蓄積してまとめて書き込む
- **フラッシュ間隔**: 10フレームごと（参照実装準拠）
- **録画への影響**: CSV書き込みが録画処理を遅延させないこと

### 3.2 エラーハンドリング

- CSVファイルのオープン失敗: 警告ログを出力し、録画は継続
- CSV書き込み失敗: 警告ログを出力し、録画は継続
- 録画終了時: バッファに残っているデータをすべて書き込む

### 3.3 リソース管理

- 録画終了時にCSVファイルを確実にクローズ
- 異常終了時もfinally句でクリーンアップ

## 4. 設計方針

### 4.1 変更対象

| ファイル | 変更内容 |
|---------|---------|
| `recording_controller.py` | RecordingSlot拡張、CSV処理追加 |

### 4.2 RecordingSlot拡張

```python
@dataclass
class RecordingSlot:
    # 既存フィールド...

    # CSV関連（新規追加）
    csv_file: Optional[TextIO] = None
    csv_writer: Optional[csv.writer] = None
    csv_buffer: List[List] = field(default_factory=list)
    csv_path: Optional[Path] = None
```

### 4.3 処理フロー

```
_setup_recording()
    └── CSVファイルオープン、ヘッダー書き込み

_worker()
    └── フレームごとにバッファ追加
    └── 10フレームごとにフラッシュ

_cleanup()
    └── 残りバッファをフラッシュ
    └── CSVファイルクローズ
```

## 5. 参照実装との差異

| 項目 | 参照実装 (s10_rec4cams.py) | 本実装 |
|-----|---------------------------|--------|
| frame_number桁数 | 4桁 (`{:04}`) | 5桁 (`{:05}`) |
| 出力先ディレクトリ | `captures/csv/` | `captures/${timestamp}/` (動画と同じ) |
| ファイル命名 | `cam{serial}.csv` | `cam{serial}.csv` (同じ) |
| フラッシュ間隔 | 10フレーム | 10フレーム (同じ) |

## 6. テスト項目

- [ ] CSVファイルが動画と同じディレクトリに作成される
- [ ] ヘッダー行が正しく出力される
- [ ] frame_numberが5桁ゼロ埋めで出力される
- [ ] device_timestamp_nsが正しく出力される
- [ ] 複数カメラで個別のCSVファイルが作成される
- [ ] 録画終了後、全フレームがCSVに記録されている
- [ ] CSV書き込みエラー時も録画が継続する

## 7. 要調査事項

なし（参照実装で動作確認済みのため）
