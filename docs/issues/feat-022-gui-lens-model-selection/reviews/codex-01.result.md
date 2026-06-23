**レビュー結果**

致命的な問題は見つかりませんでした。

- **高**: なし
- **中**: なし
- **低**: なし（瑣末な指摘は対象外として割愛）

整合性確認済みの要点:

- `CalibrationEngine.calibrate()` は既に `lens_model="normal" | "wide"` を受け取り、`normal` は5係数、`wide` は8係数を返す実装です: [calibration_engine.py](/home/sakagawa/git/SynchroCap/src/synchroCap/calibration_engine.py:38)
- 現行GUIはまだ `lens_model` 未指定で呼んでいますが、設計書はここを渡す変更として正しく指定しています: [ui_calibration.py](/home/sakagawa/git/SynchroCap/src/synchroCap/ui_calibration.py:641)
- 現行GUIの歪み表示は8係数固定参照で、`normal` 時に落ちる箇所ですが、設計書は動的表示へ変更する設計になっており妥当です: [ui_calibration.py](/home/sakagawa/git/SynchroCap/src/synchroCap/ui_calibration.py:703)
- TOML/JSON exporter は `dist_coeffs.flatten()` の全要素を列挙しており、5/8係数に自動追従するという要求・設計の記述と一致しています: [calibration_exporter.py](/home/sakagawa/git/SynchroCap/src/synchroCap/calibration_exporter.py:71)
- `BoardSettingsStore` は汎用dict保存なので、`lens_model` 追加はUI側の保存dict追加だけで成立します: [board_settings_store.py](/home/sakagawa/git/SynchroCap/src/synchroCap/board_settings_store.py:39)

レビューのみで、テスト実行はしていません。