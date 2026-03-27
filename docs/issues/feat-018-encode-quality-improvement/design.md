# feat-018 機能設計書: Raw→MP4 エンコード品質改善

対象: `tools/raw_tool.py`
基準文書: `requirements.md`（本ディレクトリ内）
参照: `docs/issues/feat-003-raw-file-toolkit/design_step3.md`（現在の設計）

---

## 1. 対応要求マッピング

| 要求ID | 設計セクション |
|--------|---------------|
| FR-001 | 3.1 ffmpegコマンド変更 |
| FR-002 | 3.1 ffmpegコマンド変更 |
| FR-003 | 3.1 ffmpegコマンド変更, 3.2 HEVC profile |
| FR-004 | 3.3 CLI変更 |

---

## 2. システム構成

### 2.1 変更対象ファイル

| ファイル | 変更種別 | 変更内容 |
|---------|---------|---------|
| `tools/raw_tool.py` | 修正 | `build_ffmpeg_encode_command` の引数追加・コマンド変更、argparse追加 |

### 2.2 変更しないファイル・関数

- `build_frame_plan()` — フレーム選択ロジックは変更なし
- `encode_frames()` — パイプ処理は変更なし
- `scan_frame_locations()` — ヘッダスキャンは変更なし
- `cmd_encode()` — `build_ffmpeg_encode_command` の呼び出し引数追加とQPバリデーション追加のみ

### 2.3 技術スタック

| 項目 | 要件 |
|------|------|
| ffmpeg | hevc_nvenc エンコーダが使用可能であること |
| NVIDIA GPU | hevc_nvenc の yuv444p サポートが必要（Maxwell世代以降） |
| NVIDIA ドライバ | ffmpeg の hevc_nvenc が動作するバージョン |

既存の依存関係（Python 3.10、ffmpeg）に変更なし。新規ライブラリの追加なし。

---

## 3. 各機能の詳細設計

### 3.1 `build_ffmpeg_encode_command` の変更（FR-001, FR-002, FR-003）

#### 現在のシグネチャ

```python
def build_ffmpeg_encode_command(
    width: int, height: int, fps: int, output_path: str,
) -> List[str]:
```

#### 変更後のシグネチャ

```python
def build_ffmpeg_encode_command(
    width: int, height: int, fps: int, output_path: str,
    qp: int = 20,
) -> List[str]:
```

#### 変更後のffmpegコマンド

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
    "-vf", "format=yuv444p",
    "-c:v", "hevc_nvenc",
    "-profile:v", "rext",
    "-rc", "constqp",
    "-qp", f"{qp}",
    "-preset", "p7",
    output_path,
]
```

#### 変更点の対比

| 項目 | 変更前 | 変更後 | 操作 | 対応要求 |
|------|--------|--------|------|---------|
| 色空間変換 | `-vf format=yuv420p` | `-vf format=yuv444p` | 変更 | FR-003 |
| HEVC profile | (なし、デフォルト main) | `-profile:v rext` | 追加 | FR-003 |
| レート制御 | `-b:v 2200k -maxrate 2200k -bufsize 4400k` | `-rc constqp -qp {qp}` | 変更 | FR-001 |
| preset | `-preset p4` | `-preset p7` | 変更 | FR-002 |
| 削除オプション | `-b:v 2200k`, `-maxrate 2200k`, `-bufsize 4400k` | — | **削除**（constqpモードでは不要） | FR-001 |

#### 設計判断

**レート制御方式の選定**:
- 採用案: `constqp`（Constant QP）
  - 理由: 品質が一定で最もシンプル。オフラインツールであり、ファイルサイズの予測可能性は不要
- 却下案: `vbr` + `-cq`（VBR Constant Quality）
  - 理由: constqpで十分。VBRはビットレート上限/下限の設定が追加で必要になり複雑化する。Spatial AQはVBR/CBRでのみ有効だが、constqpの品質で十分と判断
- 却下案: CBRのビットレートを上げる
  - 理由: シーンの複雑さに関係なく固定ビットレートを消費する。静止シーンでは無駄、動きの多いシーンでは不足する

**Spatial AQ の不採用**:
- `-spatial-aq 1` は `constqp` モードではQPが固定されるため、ビット再配分が機能しない
- VBRに変更すればSpatial AQは有効になるが、constqpのシンプルさを優先し不採用とした

**yuv444p + rext profile の選定**:
- 採用案: yuv444p + profile rext
  - 理由: Bayer demosaic直後の色情報をフルに保持。hevc_nvencがyuv444pをサポートしていることを確認済み。profileをrextに明示指定しないとエラーになる可能性がある
- 却下案: yuv420pのまま
  - 理由: 色差サブサンプリングによる劣化が発生する
- 注意: yuv444p + rext profileは一部の古いプレイヤー（Windows Media Player等）で非対応の可能性がある。VLC、mpv、ffplayでは再生可能

**ffmpeg `-y` オプション不使用**:
- `cmd_encode` 内で出力ファイルの存在チェックを行い、同名ファイルが既に存在する場合は `EXIT_ERROR` で終了する（既存動作、変更なし）
- そのため ffmpeg に `-y`（上書き許可）は付与しない

**QP値のデフォルト**:
- 採用案: qp=20
  - 理由: 高品質でありながら過大なファイルサイズにならないバランス点。一般的に18〜23が「視覚的に高品質」とされる範囲
- 参考: qp=0は数学的ロスレスだがファイルサイズが極端に大きい。qp=30以上は品質低下が目立つ

### 3.2 HEVC profile 設定（FR-003）

yuv444pを使用するには HEVC の Range Extensions (rext) profile が必要。mainプロファイルは yuv420p のみ対応。

ffmpegコマンドに `-profile:v rext` を追加する。これにより hevc_nvenc が 4:4:4 エンコードを行う。

### 3.3 CLI変更（FR-004）

#### argparse追加

```python
encode_parser.add_argument("--qp", type=int, default=20,
                           help="QP value for constant quality (0-51, default: 20)")
```

#### cmd_encode内の変更

`build_ffmpeg_encode_command` の呼び出しに `qp=args.qp` を追加する。

```python
# 変更前
cmd = build_ffmpeg_encode_command(file_hdr.width, file_hdr.height, fps, output_path)

# 変更後
cmd = build_ffmpeg_encode_command(file_hdr.width, file_hdr.height, fps, output_path,
                                  qp=args.qp)
```

#### QP値のバリデーション

argparseの `type=int` に加えて、`cmd_encode` 内で範囲チェックを行う。QPバリデーションは既存のバリデーション群（ディレクトリ存在チェック等）の直後、Pass 1 の前に配置する。

```python
if args.qp < 0 or args.qp > 51:
    print("Error: --qp must be 0-51", file=sys.stderr)
    return EXIT_ERROR
```

### 3.4 コンソール出力の変更

既存のサマリ表示の `MP4 fps:` 行のみ変更する。他の行は現状維持。

変更前:
```
  MP4 fps: {fps}
```

変更後:
```
  MP4 fps: {fps} (qp={qp})
```

---

## 4. エラーハンドリング

| 状況 | 対応 | 終了コード |
|------|------|-----------|
| `--qp` が 0〜51 の範囲外 | `"Error: --qp must be 0-51"` を stderr に出力 | `EXIT_ERROR` (2) |
| hevc_nvenc が yuv444p 非対応のGPU | ffmpegがエラー終了 → stderrを表示 | `EXIT_FAIL` (1) |

---

## 5. 境界条件

| 条件 | 振る舞い |
|------|---------|
| qp=0 | 数学的ロスレス。ファイルサイズが非常に大きくなるが正常動作する |
| qp=51 | 最低品質。正常動作する |
| qp未指定 | デフォルト20が使用される |

---

## 6. ログ・デバッグ設計

CLIツールのため、ログフレームワークは使用しない。すべての出力は `print()` による標準出力/標準エラー出力。

| 出力先 | 内容 |
|--------|------|
| stdout | エンコードサマリ（Raw files, Total raw frames, Time span, MP4 fps, MP4 frames, Output）、"Encoding..."、"Done." |
| stderr | エラーメッセージ、ffmpegのstderr出力 |

変更により追加されるログ出力: `MP4 fps:` 行への `(qp={qp})` 表示のみ。

---

## 7. 影響範囲

### 既存機能への影響

- `encode` サブコマンドの出力MP4の品質・サイズが変わる
- フレーム選択ロジック（時間的正しさ）は変更なし
- 他のサブコマンド（dump, validate, sync-check, view）は変更なし

### 本番アプリへの影響

- `tools/raw_tool.py` はスタンドアロンツールであり、本番アプリ（`src/synchroCap/`）に影響しない
- 本番アプリの `recording_controller.py` のffmpegオプションは本案件のスコープ外

### ドキュメント更新

- `docs/TECH_STACK.md`: 外部コマンドセクションのffmpeg行の使用箇所に `tools/raw_tool.py` を追加する
