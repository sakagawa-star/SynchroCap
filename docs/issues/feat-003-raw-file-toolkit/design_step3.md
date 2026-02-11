# feat-003 機能設計書: Raw→MP4エンコード (Step 3)

対象: `dev/tutorials/13_raw_viewer/s13_raw_tool.py` （既存ツールにサブコマンド追加）
基準文書: `requirements_step3.md`（本ディレクトリ内）
参照仕様: `../feat-002-raw-file-recording/design.md`（SRAWフォーマット仕様）
参照実装: `dev/tutorials/12_rec_raw/s12_rec4cams.py`（ffmpegオプション）

---

## 1. 機能概要

### 1.1 機能名

Raw→MP4エンコーダ（Raw to MP4 Encoder）

### 1.2 機能説明

既存の `s13_raw_tool.py` に `encode` サブコマンドを追加する。セッション内の指定カメラのRawファイル群を読み込み、タイムスタンプベースのフレーム選択を行い、ffmpegにパイプしてMP4を出力する。

### 1.3 処理方式

**2パス方式**を採用する。

- **Pass 1（ヘッダスキャン）**: 全Rawファイルのフレームヘッダをスキャンし、タイムスタンプ一覧とファイル内オフセットを収集する。フレーム選択計画を生成する。
- **Pass 2（エンコード）**: 選択計画に従ってペイロードを読み出し、ffmpegのstdinにパイプする。

---

## 2. データ構造設計

### 2.1 FrameLocation

フレームの所在情報。Pass 1で収集し、Pass 2でペイロード読み出しに使用する。

```python
class FrameLocation(NamedTuple):
    raw_path: str        # Rawファイルのパス
    file_offset: int     # FrameHeaderのファイル内オフセット
    payload_size: int    # ペイロードサイズ（バイト）
    frame_index: int     # フレームインデックス
    timestamp_ns: int    # タイムスタンプ（ナノ秒）
```

### 2.2 フレーム選択計画

```python
# plan[i] = FrameLocation リスト内のインデックス
# MP4フレーム i に使用するRawフレームを示す
plan: List[int]
```

---

## 3. モジュール設計

### 3.1 追加する関数一覧

| 関数名 | 責務 |
|--------|------|
| `scan_frame_locations(raw_files)` | 全Rawファイルのフレーム所在情報を収集 |
| `build_frame_plan(locations, fps)` | フレーム選択計画を生成 |
| `build_ffmpeg_encode_command(width, height, fps, output_path)` | ffmpegコマンドライン構築 |
| `encode_frames(plan, locations, ffmpeg_proc)` | 計画に従いペイロードをffmpegにパイプ |
| `cmd_encode(args)` | encodeサブコマンド本体 |

### 3.2 `scan_frame_locations(raw_files: List[str]) -> Tuple[FileHeader, List[FrameLocation]]`

全Rawファイルのヘッダをスキャンし、FrameLocationリストを返す。

```
1. 最初のRawファイルからFileHeaderを読み、以降のファイルでも一貫性を確認
2. 各Rawファイルについて:
   a. read_file_header(f) → FileHeader取得
   b. iter_frame_infos(f) → 各FrameInfoのfile_offsetとraw_pathを記録
   c. FrameLocation を生成しリストに追加
3. (FileHeader, List[FrameLocation]) を返す
```

**前提**: raw_filesはstartframeの昇順でソート済み（discover_session_filesが保証）。

### 3.3 `build_frame_plan(locations: List[FrameLocation], fps: int) -> List[int]`

タイムスタンプベースでフレーム選択計画を生成する。

```
1. t_first = locations[0].timestamp_ns
2. t_last = locations[-1].timestamp_ns
3. interval_ns = 1_000_000_000 / fps
4. plan = []
5. raw_idx = 0  # 現在のRawフレーム位置
6. mp4_frame = 0
7. loop:
   a. t_target = t_first + mp4_frame * interval_ns
   b. t_target > t_last → 最後のフレームを追加して終了
   c. raw_idx を進めて、t_target 以前で最も近いフレームを見つける（floor方式）:
      - locations[raw_idx + 1].timestamp_ns <= t_target の間、raw_idx を進める
   d. plan.append(raw_idx)
   e. mp4_frame += 1
8. return plan
```

**計算量**: O(N + M) — N=Rawフレーム数, M=MP4フレーム数。raw_idxは前方にのみ進むため。

### 3.4 `build_ffmpeg_encode_command(width, height, fps, output_path) -> List[str]`

```python
[
    "ffmpeg",
    "-hide_banner",
    "-nostats",
    "-loglevel", "error",
    "-f", "rawvideo",
    "-pix_fmt", "bayer_grbg8",
    "-s", f"{width}x{height}",
    "-framerate", f"{fps}",
    "-i", "-",
    "-vf", "format=yuv420p",
    "-c:v", "hevc_nvenc",
    "-b:v", "2200k",
    "-maxrate", "2200k",
    "-bufsize", "4400k",
    "-preset", "p4",
    output_path,
]
```

### 3.5 `encode_frames(plan, locations, ffmpeg_stdin) -> Tuple[int, int]`

計画に従いペイロードを読み出してffmpegにパイプする。(duplicated_count, total_written) を返す。

```
1. last_payload = None  # メモリキャッシュ
2. last_raw_idx = -1    # 前回使用したRawフレームインデックス
3. current_file = None  # 現在開いているファイル
4. current_path = None  # 現在開いているファイルのパス
5. duplicated = 0

6. for mp4_frame, raw_idx in enumerate(plan):
   a. if raw_idx == last_raw_idx:
      → ffmpeg_stdin.write(last_payload)  # キャッシュから再送
      → duplicated += 1
      → continue
   b. loc = locations[raw_idx]
   c. if current_path != loc.raw_path:
      → current_file を close（開いていれば）
      → current_file = open(loc.raw_path, "rb")
      → current_path = loc.raw_path
   d. current_file.seek(loc.file_offset + FRAME_HEADER_SIZE)
   e. payload = current_file.read(loc.payload_size)
   f. ffmpeg_stdin.write(payload)
   g. last_payload = payload  # キャッシュ更新
   h. last_raw_idx = raw_idx

7. current_file を close
8. return (duplicated, len(plan))
```

### 3.6 `cmd_encode(args: argparse.Namespace) -> int`

```
1. 引数取得: session_dir, serial, fps
2. ディレクトリ存在チェック
3. discover_session_files(session_dir) → 指定serialのRawファイル取得
4. Rawファイルなし → EXIT_ERROR
5. 出力パス生成: {session_dir}/cam{serial}.mp4
6. 同名MP4存在チェック → EXIT_ERROR
7. scan_frame_locations(raw_files) → FileHeader, locations
8. pixel_format != BayerGR8 → EXIT_ERROR
9. フレーム数 == 0 → EXIT_ERROR
10. build_frame_plan(locations, fps) → plan
11. サマリ表示（Rawファイル一覧、フレーム数、時間、duplicated/skipped数）
    - skipped = len(locations) - len(set(plan))
    - duplicated = len(plan) - len(set(plan))
12. build_ffmpeg_encode_command() → cmd
13. subprocess.Popen(cmd, stdin=PIPE, stderr=PIPE)
14. encode_frames(plan, locations, proc.stdin)
15. proc.stdin.close()
16. proc.wait()
17. proc.returncode != 0 → stderrを表示、EXIT_FAIL
18. "Done." 表示
19. return EXIT_OK
```

---

## 4. CLI設計

### 4.1 argparse追加

```python
# encode
encode_parser = subparsers.add_parser("encode", help="Encode raw files to MP4")
encode_parser.add_argument("session_dir", help="Path to session directory")
encode_parser.add_argument("--serial", required=True, help="Camera serial number")
encode_parser.add_argument("--fps", type=int, default=30,
                           help="MP4 frame rate (default: 30)")
```

### 4.2 mainのディスパッチ追加

```python
elif args.command == "encode":
    return cmd_encode(args)
```

---

## 5. コンソール出力フォーマット

```
=== Encode: {session_dir} cam{serial} ===
  Raw files: {file1} ({n1} frames), {file2} ({n2} frames)
  Total raw frames: {total}
  Time span: {span:.3f} s
  MP4 fps: {fps}
  MP4 frames: {mp4_total} ({duplicated} duplicated, {skipped} skipped)
  Output: {output_path}
  Encoding...
  Done.
```

---

## 6. エラーハンドリング

| 状況 | 対応 | 終了コード |
|------|------|-----------|
| session_dir不存在 | エラーメッセージ | 2 |
| 指定serialのRawなし | エラーメッセージ | 2 |
| pixel_format != BayerGR8 | エラーメッセージ | 2 |
| 同名MP4既存 | エラーメッセージ | 2 |
| フレーム数 == 0 | エラーメッセージ | 2 |
| ffmpegコマンドが見つからない | subprocess起動時の例外をキャッチ、エラーメッセージ | 2 |
| ffmpeg異常終了 | stderrを表示、EXIT_FAIL | 1 |
| ペイロード読み込みエラー | エラーメッセージ、ffmpegを終了 | 1 |

---

## 7. 処理性能への考慮

### 7.1 メモリ使用量

- Pass 1: FrameLocationリスト。1エントリ≈100バイト。10万フレームで≈10MB。
- Pass 2: 直前ペイロードのキャッシュ1枚分。1920x1080 BayerGR8 = 約2MB。
- 合計: 大規模セッションでも数十MB程度。

### 7.2 I/O効率

- Pass 1: Payloadスキップ（seekのみ）で高速スキャン。
- Pass 2: フレーム選択計画はRawフレーム順で概ね前方アクセスとなるため、シーケンシャルに近いI/Oパターン。
- ファイル切り替え: 分割Rawファイル間の切り替えはstartframe順のため1方向。

---

## 8. 影響範囲

### 変更対象ファイル

| ファイル | 変更種別 |
|---------|---------|
| `dev/tutorials/13_raw_viewer/s13_raw_tool.py` | 修正（encodeサブコマンド追加） |

### 既存機能への影響

- なし（新規サブコマンドの追加のみ）
