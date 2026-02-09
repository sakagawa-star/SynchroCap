# inv-001: 機能設計書

## 1. 変更概要

### 1.1 変更対象ファイル

| ファイル | 変更種別 | 内容 |
|---------|---------|------|
| `dev/tutorials/11_pixelformat/ptp-synchronizecapture.py` | 修正 | PIXEL_FORMAT確認機能の追加 |

## 2. 設計詳細

### 2.1 新規関数

```python
def verify_pixel_format(grabber: ic4.Grabber, cam_label: str, expected: str) -> bool:
    """
    PIXEL_FORMATの設定値を読み戻して確認する

    Args:
        grabber: カメラのGrabberインスタンス
        cam_label: ログ出力用のカメララベル（例: "cam1"）
        expected: 期待するPIXEL_FORMAT値（例: "BayerGR8"）

    Returns:
        True: 一致, False: 不一致
    """

def verify_resolution(grabber: ic4.Grabber, cam_label: str, expected_width: int, expected_height: int) -> bool:
    """
    WIDTH/HEIGHTの設定値を読み戻して確認する

    Args:
        grabber: カメラのGrabberインスタンス
        cam_label: ログ出力用のカメララベル（例: "cam1"）
        expected_width: 期待するWIDTH値
        expected_height: 期待するHEIGHT値

    Returns:
        True: 両方一致, False: いずれか不一致
    """
```

### 2.2 処理フロー

```
main()
    │
    ├── デバイスオープン
    │
    ├── apply_basic_properties(g)  [既存]
    │       └── PIXEL_FORMAT設定
    │
    └── verify_pixel_format(g, cam_label, expected)  [新規追加]
            ├── mp.get_value_str(ic4.PropId.PIXEL_FORMAT)
            ├── 設定値と比較
            └── 結果をターミナル出力
```

### 2.3 実装詳細

```python
def verify_pixel_format(grabber: ic4.Grabber, cam_label: str, expected: str) -> bool:
    """PIXEL_FORMATの設定値を読み戻して確認"""
    mp = grabber.device_property_map
    try:
        actual = mp.get_value_str(ic4.PropId.PIXEL_FORMAT)
        if actual == expected:
            print(f"[{cam_label}] PIXEL_FORMAT: set={expected}, readback={actual}, OK")
            return True
        else:
            print(f"[{cam_label}] PIXEL_FORMAT: set={expected}, readback={actual}, MISMATCH!")
            return False
    except Exception as e:
        print(f"[{cam_label}] PIXEL_FORMAT: readback error={e}")
        return False


def verify_resolution(grabber: ic4.Grabber, cam_label: str, expected_width: int, expected_height: int) -> bool:
    """WIDTH/HEIGHTの設定値を読み戻して確認"""
    mp = grabber.device_property_map
    ok = True
    try:
        actual_width = mp.get_value_int(ic4.PropId.WIDTH)
        if actual_width == expected_width:
            print(f"[{cam_label}] WIDTH: set={expected_width}, readback={actual_width}, OK")
        else:
            print(f"[{cam_label}] WIDTH: set={expected_width}, readback={actual_width}, MISMATCH!")
            ok = False
    except Exception as e:
        print(f"[{cam_label}] WIDTH: readback error={e}")
        ok = False

    try:
        actual_height = mp.get_value_int(ic4.PropId.HEIGHT)
        if actual_height == expected_height:
            print(f"[{cam_label}] HEIGHT: set={expected_height}, readback={actual_height}, OK")
        else:
            print(f"[{cam_label}] HEIGHT: set={expected_height}, readback={actual_height}, MISMATCH!")
            ok = False
    except Exception as e:
        print(f"[{cam_label}] HEIGHT: readback error={e}")
        ok = False

    return ok
```

### 2.4 main()への組み込み

```python
# 基本設定を適用
for g in grabbers:
    apply_basic_properties(g)

# [新規追加] プロパティ確認
for i, g in enumerate(grabbers):
    cam_label = f"cam{i+1}"
    verify_pixel_format(g, cam_label, DEFAULT_SETTINGS["PIXEL_FORMAT"])
    verify_resolution(g, cam_label, DEFAULT_SETTINGS["WIDTH"], DEFAULT_SETTINGS["HEIGHT"])
```

## 3. 出力仕様

### 3.1 正常時

```
[cam1] PIXEL_FORMAT: set=BayerGR8, readback=BayerGR8, OK
[cam2] PIXEL_FORMAT: set=BayerGR8, readback=BayerGR8, OK
[cam3] PIXEL_FORMAT: set=BayerGR8, readback=BayerGR8, OK
[cam4] PIXEL_FORMAT: set=BayerGR8, readback=BayerGR8, OK
```

### 3.2 不一致時

```
[cam1] PIXEL_FORMAT: set=BayerGR8, readback=BGR8, MISMATCH!
```

### 3.3 読み戻しエラー時

```
[cam1] PIXEL_FORMAT: readback error=<エラー内容>
```

## 4. エラーハンドリング

| 状況 | 動作 |
|------|------|
| 読み戻し成功・一致 | OK表示、処理続行 |
| 読み戻し成功・不一致 | MISMATCH警告、処理続行 |
| 読み戻し失敗 | エラー表示、処理続行 |

## 5. 参照実装

- `dev/tutorials/02_format_setup/main.py:104`
  ```python
  pixel = prop_map.get_value_str(ic4.PropId.PIXEL_FORMAT)
  ```

- `dev/tutorials/09_camera_init.ntb/s09_v4l2-raw125.py:82`
  ```python
  current_pf = dmap.get_value_str(ic4.PropId.PIXEL_FORMAT)
  ```
