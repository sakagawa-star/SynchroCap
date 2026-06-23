# Ubuntu 24系で `codex exec` を使うときの bwrap サンドボックス対策

## 対象環境
- Ubuntu 24.04 系（非特権 user namespace 制限が有効なバージョン）
- Codex CLI（確認時 0.139.0）

## 症状
`codex exec` 実行時、または以下の最小再現コマンドで次のエラーが出る。

```
bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
```

最小再現コマンド:

```bash
bwrap --dev-bind / / --unshare-net echo ok
```

## 原因
Ubuntu 23.10 以降は `kernel.apparmor_restrict_unprivileged_userns=1` をデフォルトで設定し、非特権プロセスによる user namespace（ユーザー名前空間）の作成を AppArmor がブロックする。bwrap はサンドボックスのループバック設定に user namespace を必要とするため、`RTM_NEWADDR`（ネットワークインタフェースへのアドレス割り当て要求）が `EPERM`（Operation not permitted）で失敗する。Codex のバグではなくホスト側の制限。

## 対策（採用）
bwrap に限って user namespace 作成を許可する AppArmor プロファイルを追加する。

プロファイル作成と読み込み:

```bash
sudo tee /etc/apparmor.d/bwrap > /dev/null <<'EOF'
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
EOF
sudo apparmor_parser -r /etc/apparmor.d/bwrap
```

`apparmor_parser -r` は指定したプロファイル1つだけを再読み込みする（AppArmor 全体は触らない）。

## 確認
```bash
bwrap --dev-bind / / --unshare-net echo ok                  # → ok が出れば成功
codex exec "シェルで pwd を実行し、その出力だけを返して"   # エラーなく実行されれば完了
```

## 元に戻す
```bash
sudo apparmor_parser -R /etc/apparmor.d/bwrap && sudo rm /etc/apparmor.d/bwrap
```

`-R` で追加したプロファイルをアンロードし、ファイルを削除する。bwrap は Ubuntu 既定の制限状態（user namespace ブロック）に戻り、再び `RTM_NEWADDR` エラーが出る状態になる。

## 補足
- プロファイルは `/etc/apparmor.d/` 配下にあり、再起動後も AppArmor が起動時に自動で読み込む。永続する。
- セキュリティ影響: user namespace 作成を `/usr/bin/bwrap` に限って再許可する。`sysctl kernel.apparmor_restrict_unprivileged_userns=0`（システム全体で緩和）より対象範囲が狭い。Ubuntu が flatpak / chrome 向けに配布するプロファイルと同じ形。
- 代替の `use_legacy_landlock = true`（Landlock フォールバック強制）でも回避できるが、Codex 側で非推奨・近く削除予定のため恒久策には不向き。一時的な回避としては有効。
