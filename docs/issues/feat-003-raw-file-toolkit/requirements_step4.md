# feat-003 Step 4 要求仕様書: encodeサブコマンドの統計表示改善

## 1. 目的

`encode`サブコマンドの出力メッセージにおいて、`duplicated`/`skipped`の原因がタイムスタンプジッタ（正常）なのか、実際の問題なのかをユーザーが判別できるようにする。

## 2. 背景

現在の出力:
```
  MP4 frames: 153 (1 duplicated, 1 skipped)
```

この表示だけでは以下の区別がつかない:
- **正常（ジッタ）**: Raw fps ≈ MP4 fps で、PTPトリガーのタイムスタンプ微小ずれにより1〜2フレームのduplicated/skippedが発生
- **意図的（ダウンサンプリング）**: Raw fps > MP4 fps（例: 50fps録画→30fpsエンコード）でskipが多数発生
- **異常（フレーム落ち等）**: 大量のduplication/skipが発生

## 3. 機能要件

### FR-01: Raw実効fpsの表示

- Rawフレームのタイムスタンプから算出した実効fpsを表示する
- 計算式: `(フレーム数 - 1) / time_span_s`
- MP4 fpsと並べて表示し、比較できるようにする

### FR-02: duplicated/skipped行への状況判定ノートの付与

以下の条件に基づいてノートを付与する:

| 条件 | ノート |
|------|--------|
| duplicated + skipped == 0 | `(exact match)` |
| raw fps ≈ MP4 fps かつ比率が小さい（< 1%） | `(timestamp jitter)` |
| raw fps > MP4 fps でskipが多い | `(downsampled from {raw_fps:.1f} fps)` |
| raw fps < MP4 fps でduplicatedが多い | `(upsampled from {raw_fps:.1f} fps)` |
| 上記以外で比率が大きい（>= 1%） | `(WARNING: significant mismatch)` |

- 「raw fps ≈ MP4 fps」の判定閾値: 差が10%以内
- 「比率が小さい」の判定基準: `(duplicated + skipped) / len(plan) < 0.01`

### FR-03: 出力フォーマット

改善後の出力イメージ:

```
=== Encode: 20260211-172735 cam05520125 ===
  Raw files: cam05520125_000000.raw (100 frames), cam05520125_000100.raw (53 frames)
  Total raw frames: 153
  Time span: 5.067 s
  Raw effective fps: 30.0
  MP4 fps: 30
  MP4 frames: 153 (1 duplicated, 1 skipped -- timestamp jitter)
  Output: 20260211-172735/cam05520125.mp4
  Encoding...
  Done.
```

## 4. 非機能要件

### NFR-01: 後方互換性

- `encode`の動作（フレーム選択、エンコード処理）には一切変更を加えない
- 変更は統計表示メッセージのみ

## 5. 変更対象ファイル

| ファイル | 変更内容 |
|---------|---------|
| `dev/tutorials/13_raw_viewer/s13_raw_tool.py` | `cmd_encode()`内の統計表示部分のみ |

## 6. 関連ドキュメント

- [design_step3.md](design_step3.md) — Step 3（encode実装）の機能設計書
