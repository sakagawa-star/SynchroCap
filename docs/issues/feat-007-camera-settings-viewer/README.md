# feat-007: Camera Settings Viewer (Tab4)

## Status: Closed (実装完了)

## Created: 2026-02-23

## Summary

接続しているカメラ（チャンネル紐付け済み）の設定を一覧表示する新規タブ（Tab4）を追加する。

## Requirements

### 表示項目（全カメラ分）

| 項目 | 説明 |
|------|------|
| Resolution | 解像度 |
| PixelFormat | ピクセルフォーマット |
| Framerate (fps) | フレームレート |
| Trigger Interval (fps) | トリガーインターバル |
| Auto White Balance | Off / Continuous |
| Auto Exposure | Off / Continuous |
| Auto Gain | Off / Continuous |

### 機能要件

- カメラから直接設定値を取得して表示する
- 全カメラの設定が同一かどうかをチェックし、結果を表示する
- チャンネルとカメラの紐付けが完了しているカメラが対象

## Documents

- [要件定義書](requirements.md)
- [機能設計書](feature_design.md)

## References

- `src/synchroCap/ui_camera_settings.py` - プロパティ取得パターンの参照実装
- `src/synchroCap/mainwindow.py` - タブ切り替え制御の参照実装
