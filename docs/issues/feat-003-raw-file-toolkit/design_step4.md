# feat-003 Step 4 機能設計書: encodeサブコマンドの統計表示改善

## 1. 概要

`cmd_encode()`内の統計表示部分を変更し、Raw実効fpsの表示と duplicated/skipped の状況判定ノートを追加する。

## 2. 変更対象

| ファイル | 関数 | 変更内容 |
|---------|------|---------|
| `dev/tutorials/13_raw_viewer/s13_raw_tool.py` | `cmd_encode()` | 統計表示部分のみ |

変更なし: `build_frame_plan()`, `encode_frames()`, `build_ffmpeg_encode_command()`, その他全関数

## 3. 変更内容

### 3.1 変更対象の既存コード（s13_raw_tool.py 814〜846行目付近）

```python
    # Statistics
    t_first = locations[0].timestamp_ns
    t_last = locations[-1].timestamp_ns
    time_span_s = (t_last - t_first) / 1_000_000_000

    unique_in_plan = len(set(plan))
    duplicated = len(plan) - unique_in_plan
    skipped = len(locations) - unique_in_plan

    # ... (file summary省略) ...

    print(f"=== Encode: {session_dir} cam{serial} ===")
    print(f"  Raw files: {raw_desc}")
    print(f"  Total raw frames: {len(locations)}")
    print(f"  Time span: {time_span_s:.3f} s")
    print(f"  MP4 fps: {fps}")
    print(f"  MP4 frames: {len(plan)} ({duplicated} duplicated, {skipped} skipped)")
    print(f"  Output: {output_path}")
    print(f"  Encoding...")
```

### 3.2 変更後のコード

```python
    # Statistics
    t_first = locations[0].timestamp_ns
    t_last = locations[-1].timestamp_ns
    time_span_s = (t_last - t_first) / 1_000_000_000

    # Raw実効fps
    raw_effective_fps = (len(locations) - 1) / time_span_s if time_span_s > 0 else 0.0

    unique_in_plan = len(set(plan))
    duplicated = len(plan) - unique_in_plan
    skipped = len(locations) - unique_in_plan

    # 状況判定ノート
    note = _classify_frame_plan(raw_effective_fps, fps, duplicated, skipped, len(plan))

    # ... (file summary省略) ...

    print(f"=== Encode: {session_dir} cam{serial} ===")
    print(f"  Raw files: {raw_desc}")
    print(f"  Total raw frames: {len(locations)}")
    print(f"  Time span: {time_span_s:.3f} s")
    print(f"  Raw effective fps: {raw_effective_fps:.1f}")       # 追加
    print(f"  MP4 fps: {fps}")
    print(f"  MP4 frames: {len(plan)} ({duplicated} duplicated, {skipped} skipped -- {note})")  # ノート追加
    print(f"  Output: {output_path}")
    print(f"  Encoding...")
```

### 3.3 新規追加: _classify_frame_plan() 関数

モジュールレベル関数として追加する。`cmd_encode()`の直前に配置。

```python
def _classify_frame_plan(
    raw_fps: float,
    mp4_fps: int,
    duplicated: int,
    skipped: int,
    total_mp4_frames: int,
) -> str:
    """duplicated/skipped の状況を判定してノート文字列を返す"""
    if duplicated == 0 and skipped == 0:
        return "exact match"

    total_mismatch = duplicated + skipped
    mismatch_ratio = total_mismatch / total_mp4_frames if total_mp4_frames > 0 else 0.0
    fps_diff_ratio = abs(raw_fps - mp4_fps) / mp4_fps if mp4_fps > 0 else 0.0
    fps_similar = fps_diff_ratio < 0.10  # 10%以内なら同等とみなす

    if fps_similar and mismatch_ratio < 0.01:
        return "timestamp jitter"

    if raw_fps > mp4_fps and skipped > duplicated:
        return f"downsampled from {raw_fps:.1f} fps"

    if raw_fps < mp4_fps and duplicated > skipped:
        return f"upsampled from {raw_fps:.1f} fps"

    if mismatch_ratio >= 0.01:
        return "WARNING: significant mismatch"

    return "timestamp jitter"
```

### 3.4 判定ロジックの詳細

| 優先順 | 条件 | 返値 | 意味 |
|--------|------|------|------|
| 1 | duplicated + skipped == 0 | `exact match` | 完全一致 |
| 2 | fps差 < 10% かつ mismatch < 1% | `timestamp jitter` | PTPジッタによる正常な微小ずれ |
| 3 | raw_fps > mp4_fps かつ skip > dup | `downsampled from X fps` | 高fpsからのダウンサンプリング |
| 4 | raw_fps < mp4_fps かつ dup > skip | `upsampled from X fps` | 低fpsからのアップサンプリング |
| 5 | mismatch >= 1% | `WARNING: significant mismatch` | 異常の可能性あり |
| 6 | その他 | `timestamp jitter` | フォールバック |

### 3.5 出力例

#### ケース1: 同一fps、ジッタ（今回のケース）
```
  Raw effective fps: 30.0
  MP4 fps: 30
  MP4 frames: 153 (1 duplicated, 1 skipped -- timestamp jitter)
```

#### ケース2: 完全一致
```
  Raw effective fps: 30.0
  MP4 fps: 30
  MP4 frames: 150 (0 duplicated, 0 skipped -- exact match)
```

#### ケース3: 50fps録画→30fpsエンコード
```
  Raw effective fps: 50.1
  MP4 fps: 30
  MP4 frames: 152 (0 duplicated, 98 skipped -- downsampled from 50.1 fps)
```

#### ケース4: 大量のフレーム落ち（異常）
```
  Raw effective fps: 25.3
  MP4 fps: 30
  MP4 frames: 153 (20 duplicated, 5 skipped -- WARNING: significant mismatch)
```

## 4. テスト確認項目

1. 既存のRawデータで`encode`を実行し、ノートが `timestamp jitter` と表示されること
2. エンコード結果のMP4ファイルが変更前と同一であること（表示変更のみ）
