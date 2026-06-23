# テンプレート ⇄ リポジトリ ドキュメント マージ調査レポート

- 作成日: 2026-06-23
- 対象リポジトリ: SynchroCap
- 目的: `template/` 内の最新版ドキュメント（Claude Code 駆動開発テンプレート、レビューは Codex 前提）を、本リポジトリの `docs/` 配下ドキュメント（同テンプレートの旧版をリポジトリ向けにカスタムした物）にマージするための事前調査
- 本レポートの位置づけ: **調査・マージ要否の洗い出しまで。実際の編集は次ステップ**
- マージ方針（ユーザー合意済み）:
  - 基本は「**template の構成・記述基準を正**」とする
  - リポジトリ固有の情報（プロジェクト概要・案件フロー・カメラ設定ルール等）は**保持**する
  - 衝突時: 書式・プロセス基準は template 優先、固有の事実は docs 優先

---

## 0. 対象ファイル対応関係

| template | docs（現行） | 関係 | マージ難易度 |
|---|---|---|---|
| `CLAUDE.md` | ルート `CLAUDE.md` | 新旧 + 固有カスタム | **大** |
| `docs/REVIEW_CRITERIA.md` | `docs/REVIEW_CRITERIA.md` | 双方向（互いに独自追加あり） | **大** |
| `docs/BUGFIX_STANDARD.md` | `docs/BUGFIX_STANDARD.md` | 双方向 | 中 |
| `docs/DESIGN_STANDARD.md` | `docs/DESIGN_STANDARD.md` | ほぼ同一（語句のみ） | 小 |
| `docs/REQUIREMENTS_STANDARD.md` | `docs/REQUIREMENTS_STANDARD.md` | 完全同一 | なし |
| `docs/codex-exec-ubuntu24-bwrap-fix.md` | （無し） | template新規・参考資料 | 取込不要（合意済み） |

> **重要な総括**: これは「新版で旧版を上書き」という単純な作業ではない。template は**プロセス面**（Codex レビュー、Bash 運用ルール、レビュー収束条件）で新しい一方、現行 docs は**ドメイン面**（GUI 状態遷移、FPS 非機能要件、TECH_STACK 整合性、設計書整合性チェック）で template に無い独自基準を積み増している。**双方向マージ**が必要。

---

## 1. CLAUDE.md（マージ難易度: 大）

### 1-A. template にあり docs に無い → **docs へ取り込むべき新要素**

1. **レビュー方式の刷新: Subagent → Codex**
   - template はステップ4を「**レビュー（Codex → 人）**」とし、`codex exec` を Claude Code 自身が実行する方式。
   - 「**Codexによるレビューの実行方法**」セクション一式（template L126-180）が丸ごと新規:
     - 逐次（`resume` でセッション継続）レビュー、重要度「高・中」がゼロに収束→人レビューへ
     - 出力保存ルール（`reviews/codex-NN.result.md` と `.full.log` の分離、`-o` 必須、`result.md` のみ git 管理）
     - 初回レビュー（機能追加用 / 不具合修正用）の具体コマンド
     - 再レビュー（`resume {SESSION_ID}`）の具体コマンド
     - レビュー終了条件
   - これは現行 docs の「Subagent（Agentツール）でレビュー」（docs L120, L137, L160）を**置換**する変更。**プロジェクトの運用を Codex に切り替えるか否かの意思決定が必要**（最大の論点）。
   - 関連: codex の bwrap 注意（template L132、`codex-exec-ubuntu24-bwrap-fix.md` 参照）。本体は取込不要だが CLAUDE.md からの参照行をどうするか要判断。

2. **「Claude Code 運用ルール > Bash 実行時のルール」セクション（template L182-188）が新規**
   - `cd <path> && <command>` 連結禁止（allowlist 不一致でパーミッションプロンプトが出る問題）
   - `git -C` / `make -C` を使う指針
   - 現行 docs に該当なし。汎用的に有用なので取り込み推奨。

3. **テンプレート利用ガイドの HTML コメント（template L5-14）** — 雛形用。docs には不要（取り込まない）。

### 1-B. docs にあり template に無い → **保持必須のリポジトリ固有情報**

template は雛形のため `{{ }}` プレースホルダ。以下は現行 docs の実値で、**全て保持**:

- プロジェクト概要 / 主な機能（docs L10-18）
- 技術スタック（Python 3.10, PySide6, IC4, ffmpeg hevc_nvenc, PTP）（docs L20-26）
- ディレクトリ構成（実ファイル一覧）（docs L28-74）
- アプリケーション起動方法（docs L76-81）
- コーディング規約（実値）（docs L83-99）
- **重要な設計判断**（録画中プレビュー、1カメラ=1スレッド、PTP Slave必須、DEFER_ACQUISITION_START）（docs L101-106）
- **テスト**セクション（`micromamba run -n SynchroCap pytest -v`、`tests/results/` 保存規約）（docs L157-164）
  - ※ template の機能追加フローはテストを「テストのルールに従って実行」と簡略化。docs のテスト規約は固有情報として保持。
- ドキュメント管理ルール / 案件管理（docs L166-188）
- **現在進行中の案件**（feat-014/015/021）（docs L190-194）
- **カメラキャリブレーション全体計画 feat-008〜013**（docs L196-220）
- **設計ルール（全案件共通）**: カメラ設定変更禁止ルール、タブ番号規約、設定変更UIの設計思想（docs L222-225）
- **完了済み案件一覧**（docs L227-239）

### 1-C. 両方にあり差分がある → **要マージ判断**

- **機能追加/不具合フローの構造**: template は feat と bug を独立した番号付きセクションに分離。docs は「機能ごとの開発フロー」+「不具合修正フロー」。内容はほぼ同義だが、template はレビューを Codex 化、収束条件を明記。→ 1-A-1 の判断に追従。
- **完了時の処理**: docs は「README Status→Closed、BACKLOG更新、CHANGELOG記録、CLAUDE.md構成更新」と具体的。template は「BACKLOG を Closed、CLAUDE.md構成更新」と簡素。→ docs の具体版を保持推奨。
- **ディレクトリ構成図のコメント**: docs L66-68 に旧4ファイル（architecture.md, requirements.md, feature_design.md）が記載されている。→ 第3章の削除判断と連動。

---

## 2. REVIEW_CRITERIA.md（マージ難易度: 大・双方向）

template と docs が**それぞれ独自方向に発展**しており、単純置換不可。

### 2-A. template にあり docs に無い → 取り込み検討

- **「2. コードレビュー」セクション**（template L27-37）:
  - 重要度分類（高=クラッシュ/データ破損/セキュリティ/メモリリーク、中=潜在バグ/リソースリーク/未使用コード/型不整合、低=スタイル/命名/軽微な非効率）
  - 修正対象（高・中を修正、低は報告のみ）
  - → docs の REVIEW_CRITERIA には**コードレビュー観点が無い**（ドキュメントレビューのみ）。CLAUDE.md 側には重要度分類の記述があるが、基準書としては template の方が体系的。取り込み推奨。
- 階層構造（「1. ドキュメントレビュー」配下に 1.1〜1.5 をネスト）

### 2-B. docs にあり template に無い → 保持必須のドメイン固有基準

- **1. ドキュメント間の一貫性**（要求⇄設計の矛盾、用語統一）（docs L6-8）
- **6. 状態遷移**（GUI/プロセスの状態遷移網羅、遷移条件・遷移先）（docs L26-29）← GUI アプリ固有
- **7. 非機能要件**（FPS・応答時間、ログ・設定ファイル方針）（docs L31-33）← 固有
- **9. 技術スタックの整合性**（TECH_STACK.md と設計書の矛盾、import 一致、バージョン固定）（docs L37-40）← 固有
- 各観点が「タイムアウト値」「接続失敗」「カメラ」等ドメイン語に具体化されている

### 2-C. マージ方針案

template の二層構造（ドキュメントレビュー / コードレビュー＋重要度分類）を骨格に採用し、docs 固有の観点（状態遷移・非機能要件・TECH_STACK整合性・ドキュメント間一貫性）を「ドキュメントレビュー」配下の観点として統合する。

---

## 3. BUGFIX_STANDARD.md（マージ難易度: 中・双方向）

### 3-A. docs にあり template に無い → 保持すべき強化点（docs の方が手厚い）

- 仕様未定義の不具合は feat-XXX として扱う旨（docs L15-19）
- 「対応する要求ID」「対応する設計セクション」記録項目（docs L27-28）
- 期待動作で要求仕様書・設計書の該当箇所を引用（docs L30）
- 「修正が設計書に沿っているか」（docs L40）
- **2.2 設計書との整合性**（設計書に沿う、変更要なら変更案併記、コードだけ変えない）（docs L59-64）
- 自動テスト（pytest）/手動テストの区別（docs L48-49）

### 3-B. template にあり docs に無い → 取り込み検討

- 「修正コード（修正前・修正後）を示す」（template L34）← docs は「設計書に沿っているか」に置換済み。両立可能なら併記。
- 「テストコマンド: 具体的な実行コマンドと期待出力」（template L42）← docs の自動/手動テスト区分と統合余地。

### 3-C. 表現差

- template「手動テスト」↔ docs「開発フロー ステップ7（手動テスト）」: docs はフローのステップ番号に紐づけて具体化。→ docs 側保持。
- 日付例: template `YYYY-MM-DD` / docs `2025-01-15`。→ プレースホルダ `YYYY-MM-DD` の方が汎用的だが要統一。

---

## 4. DESIGN_STANDARD.md（マージ難易度: 小）

差分は語句のドメイン化のみ。**実質マージ作業なし、現行 docs を維持で良い**。

- L22: `uv, pip` → `micromamba, requirements.txt`（docs がドメイン化）→ docs 保持
- L49: `入力数不足` → `カメラ台数不足`（docs がドメイン化）→ docs 保持
- L100: docs に末尾空行1行追加のみ

→ template に DESIGN_STANDARD 側の**新規追加要素は無い**。現行 docs で問題なし。

---

## 5. REQUIREMENTS_STANDARD.md（マージ難易度: なし）

`diff` 完全一致。**マージ不要**。

---

## 6. 旧4ドキュメント（docs 直下）の使用状況と削除可否

調査対象: `docs/architecture.md` / `docs/feature_design.md` / `docs/investigation.md` / `docs/requirements.md`（いずれも最終更新 2026-02-05、`ic4.demoapp` 時代の旧版）。

> ⚠️ 注意: CLAUDE.md・BUGFIX_STANDARD.md 中の `investigation.md` / `requirements.md` の大半は**案件フォルダ内** `docs/issues/{案件}/` を指す別物。以下はルート直下ファイル「そのもの」への参照のみ。

| ファイル | 削除可否 | 根拠（実体参照） |
|---|---|---|
| `architecture.md` | △ 軽微対応で削除可 | リンク列挙のみ（`README.md:208,217`、`CLAUDE.md:66` 構成図）。README のリンク行除去で対応可 |
| `feature_design.md` | ✗ 要対応 | `docs/investigation.md` が §指定で多数実体参照。旧 bug-001/002/003・feat-007 README からリンク |
| `investigation.md` | ✗ 要対応 | `bug-001/README.md`, `bug-002/README.md` が明示参照。`feature_design.md` と相互参照 |
| `requirements.md` | ✗ 要対応 | **`docs/TECH_STACK.md`（現役）が §3.2/3.3/2.2/5.3/6 を6箇所以上で実体参照**（L15,92-96,105）。`investigation.md`/`feature_design.md` も基準文書として参照 |

### 所見

- 旧4ファイルは**相互に参照し合う1つの旧クラスタ**を成しており、単独削除は不可。
- 最大の障害は **`requirements.md` ← `TECH_STACK.md`（現役ドキュメント）の §参照**。削除するには TECH_STACK.md の根拠記述を現行アーキテクチャ基準に書き換えるか、参照先を差し替える必要がある。
- 参照元の `bug-001/002/003`, `feat-007` の README は完了済み案件で、過去ログとしての参照（リンク切れは許容範囲か要判断）。

### 削除に向けた推奨ステップ（次ステップ以降）

1. `TECH_STACK.md` の `docs/requirements.md §X` 参照を、自己完結記述 or 別の現役根拠に書き換える
2. 旧 issue README（bug-001/002/003, feat-007）のリンク切れ許容可否をユーザー確認
3. `README.md` の architecture.md リンク・構成図記載を除去
4. 上記完了後、4ファイルを一括削除し、`CLAUDE.md` 構成図の L66-68 を除去

> 本章は「削除可否の判定」まで。実削除と参照書き換えは別案件として切る方が安全。

---

## 7. 次ステップの提案（実作業フェーズ）

優先度順:

1. **【意思決定】レビュー方式 Subagent → Codex への切替可否**（CLAUDE.md 1-A-1）。これが CLAUDE.md / REVIEW_CRITERIA / BUGFIX のマージ内容を左右する最大の分岐。
2. CLAUDE.md マージ（固有情報を保持しつつ template の Codex 運用・Bash ルールを統合）
3. REVIEW_CRITERIA.md 双方向マージ（template の二層構造 + docs のドメイン観点）
4. BUGFIX_STANDARD.md マージ（docs の強化点保持 + template のテストコマンド/修正コード観点）
5. DESIGN/REQUIREMENTS_STANDARD は現状維持（作業不要）
6. 旧4ドキュメント削除は**別案件**として TECH_STACK.md 書き換えとセットで実施
