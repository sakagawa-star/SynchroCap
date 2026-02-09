# inv-001: 要求定義書

## 概要

`ptp-synchronizecapture.py` に対して、カメラにPIXEL FORMATが正常に反映されたかを確認する機能を追加する。

## 背景

PIXEL FORMATとしてBayerGR8を設定しているが、実際にカメラに反映されていない疑いがある。

## 要求仕様

### 機能要求

| ID | 要求 |
|----|------|
| REQ-01 | `apply_basic_properties()` 終了後に、PIXEL_FORMATの設定値を読み戻して確認する |
| REQ-02 | 確認結果をターミナルに表示する |
| REQ-03 | 設定値と読み戻し値が不一致の場合、警告を表示して処理を続行する |

### 確認対象

| プロパティ | 設定値 | 型 |
|-----------|--------|-----|
| PIXEL_FORMAT | BayerGR8 | string |
| WIDTH | 1920 | int |
| HEIGHT | 1080 | int |

### 出力フォーマット

```
[cam1] PIXEL_FORMAT: set=BayerGR8, readback=BayerGR8, OK
[cam2] PIXEL_FORMAT: set=BayerGR8, readback=BGR8, MISMATCH!
```

### 不一致時の動作

- 警告表示のみ
- 処理は続行

## 対象ファイル

- `dev/tutorials/11_pixelformat/ptp-synchronizecapture.py`

## 変更箇所

- `apply_basic_properties()` 呼び出し後に確認処理を追加
