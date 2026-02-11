# feat-003 機能設計書: Rawフレームビューワー (Step 2)

対象: `dev/tutorials/13_raw_viewer/s13_raw_tool.py` （既存ツールにサブコマンド追加）
基準文書: `requirements_step2.md`（本ディレクトリ内）
参照仕様: `../feat-002-raw-file-recording/design.md`（SRAWフォーマット仕様）

---

## 1. 機能概要

### 1.1 機能名

Rawフレームビューワー（Raw Frame Viewer）

### 1.2 機能説明

既存の `s13_raw_tool.py` に `view` サブコマンドを追加する。Rawファイルから指定フレームのペイロードを読み込み、OpenCVでデベイヤー処理してカラー画像をウィンドウ表示する。

---

## 2. 外部依存の追加

| ライブラリ | 用途 |
|-----------|------|
| `opencv-python` (`cv2`) | デベイヤー処理、画像表示、PNG保存 |
| `numpy` (`np`) | ペイロードバイト列→2D配列変換 |

※ `numpy` は `opencv-python` の依存として自動インストールされる。

---

## 3. 追加する関数

| 関数名 | 責務 |
|--------|------|
| `read_frame_payload(f, frame_index)` | 指定インデックスのフレームまでシークし、FrameHeader + Payload を返す |
| `decode_bayer_gr8(payload, width, height)` | BayerGR8ペイロードをデベイヤーしBGR画像を返す |
| `cmd_view(args)` | viewサブコマンド本体 |

### 3.1 `read_frame_payload(f: BinaryIO, frame_index: int) -> Tuple[FrameHeader, bytes]`

```
1. ファイルポインタはFileHeader直後（offset=40）にある前提
2. frame_index 回だけFrameHeader読み→Payloadスキップを繰り返す
3. 目的フレームに到達したらFrameHeaderを読み、Payloadをf.read(payload_size)で取得
4. (FrameHeader, payload_bytes) を返す
5. 途中でEOFに達した場合はValueErrorを送出
```

### 3.2 `decode_bayer_gr8(payload: bytes, width: int, height: int) -> numpy.ndarray`

```
1. numpy.frombuffer(payload, dtype=numpy.uint8) で1D配列化
2. reshape((height, width)) で2D配列化
3. cv2.cvtColor(img, cv2.COLOR_BayerGR2BGR) でデベイヤー
4. BGR画像 (height, width, 3) の ndarray を返す
```

### 3.3 `cmd_view(args: argparse.Namespace) -> int`

```
1. 引数取得: raw_file, frame (default=0)
2. ファイル存在チェック → なければ EXIT_ERROR
3. ファイルを開き read_file_header(f)
4. pixel_format != 0 (BayerGR8) → エラーメッセージ、EXIT_ERROR
5. read_frame_payload(f, frame) → フレーム範囲外なら EXIT_ERROR
6. decode_bayer_gr8(payload, width, height)
7. コンソールにファイル情報・フレーム情報・操作説明を表示
8. cv2.imshow(window_name, bgr_image)
9. キーループ:
   a. cv2.waitKey(0)
   b. 's' → cv2.imwrite() でPNG保存、パスをコンソール表示
   c. 'q' または ESC → break
10. cv2.destroyAllWindows()
11. return EXIT_OK
```

---

## 4. CLI設計

### 4.1 argparse追加

```python
# view
view_parser = subparsers.add_parser("view", help="View a raw frame")
view_parser.add_argument("raw_file", help="Path to .raw file")
view_parser.add_argument("--frame", type=int, default=0,
                         help="Frame index to view (default: 0)")
```

### 4.2 ウィンドウタイトル

```
SynchroCap Raw Viewer - {basename} [frame {index}]
```

### 4.3 PNG保存パス生成

```python
stem = os.path.splitext(os.path.basename(raw_file))[0]
png_name = f"{stem}_frame{frame_index:06d}.png"
png_path = os.path.join(os.path.dirname(raw_file), png_name)
```

---

## 5. エラーハンドリング

| 状況 | 対応 | 終了コード |
|------|------|-----------|
| ファイルが存在しない | エラーメッセージ出力 | 2 |
| `--frame` がフレーム数以上 | エラーメッセージ（総フレーム数を表示） | 2 |
| pixel_format != BayerGR8 | エラーメッセージ（未対応フォーマット） | 2 |
| cv2 が import できない | エラーメッセージ（opencv-python のインストールを案内） | 2 |
| PNG保存失敗 | WARNINGをコンソール出力、ビューワーは継続 | — |

---

## 6. 影響範囲

### 変更対象ファイル

| ファイル | 変更種別 |
|---------|---------|
| `dev/tutorials/13_raw_viewer/s13_raw_tool.py` | 修正（viewサブコマンド追加） |

### 既存機能への影響

- なし（新規サブコマンドの追加のみ）
