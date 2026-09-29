# fal-skills（日本語）

**fal.ai の 1,500 以上のモデルを、コーディングエージェントから安定して使い回せる生成器にし、さらに複数のモデルを組み合わせた「ワークフロー skill」まで作れる Agent Skill です。**

`fal-skill-creator` は 3 つの層で動きます。

| 層 | 役割 |
|---|---|
| **探す** | 同梱の fal MCP サーバー（`recommend_model` など）と、最新順のモデル検索で候補を集め、schema で要件（秒数・解像度・入力の種類）を満たすか確かめる |
| **1 モデルを最適に使う（プロファイル）** | schema から既定値を固定し、公式ドキュメントを調べてプロンプトのテンプレートを作る。費用の上限チェック付きで生成する |
| **複数モデルを組み合わせる（ワークフロー）** | fal のモデルとローカルのスクリプトを順番につなぎ、1 つの要件から完成品を作る。そのまま skill として書き出せる |

できることは次のとおりです。

1. **要件からモデルを選ぶ**：入出力、長さ、解像度、音声の有無、商用利用、予算を確認し、MCP の `recommend_model` と最新順の検索で候補を集めます。各候補の schema を見て条件を満たさないものを外し、番号付きの候補一覧を出します。
2. **スキーマからプロファイルを作る**：`$ref` を展開した `schema.json` を作り、既定値を `defaults.json` に固定します。
3. **既定値の確認（人が確認する工程）**：出力を左右するパラメータだけを見せて確認します。
4. **プロンプト調査**：公式ドキュメント（MCP の `search_docs`、Exa、Web）を調べ、`{slot}` 付きテンプレートを出典付きで `prompting.md` にまとめます。
5. **生成**：スキーマ検証、費用見積もり（上限を超えたら人に確認。GPU 時間課金のモデルは 1 リクエスト最大 60 秒と仮定）、キュー投入、待機、保存。結果は `manifest.json` に記録されます。
6. **パイプライン**：`--from last` や `--from label:タグ` で、前の出力を次のモデルの入力に自動でつなぎます。ローカルで加工したファイルも `fal ingest` で記録すれば同じようにつなげます。
7. **ワークフロー**：`fal workflow init / check / plan / export`。`plan` は各ステップの実行コマンドを、前のステップの出力ファイルを埋めた形で出し、次にやるステップを示します。サンプルとして「1 枚のシートにアセットをグリッド配置して生成 → 背景透過 → 1 つずつ透過 PNG に分割」する `sprite-sheet` を同梱しています。
8. **Export**：プロファイルもワークフローも、単体で動く skill として書き出せます（npx skills で配布可能）。

## インストール

必要なもの：fal のアカウントと API キー（https://fal.ai/dashboard/keys ）、[uv](https://docs.astral.sh/uv/)（`curl -LsSf https://astral.sh/uv/install.sh | sh`）。Python の依存パッケージは初回実行時に自動で入ります。

### Claude Code（おすすめ）

**1. plugin を入れる**（skill と fal MCP サーバーが入っています）

```
/plugin marketplace add inovue/fal-skills
/plugin install fal@fal-skills
```

**2. skill にキーを渡す**。skill は、Claude Code を起動したシェルの環境変数 `FAL_KEY` を読みます。

```bash
export FAL_KEY="…"          # シェルの設定ファイル、または gitignore した .envrc に
```

Bitwarden Secrets Manager を使っている場合は `FAL_KEY` は不要です。下の「[Bitwarden を使っている場合](#bitwarden-を使っている場合)」を見てください。

**3. fal MCP サーバーをつなぐ**（任意。モデルのおすすめ機能に使います）。plugin が「fal API key」を聞いてきたら貼り付けてください。キーは `settings.json` ではなく OS の安全な保管場所に保存されます。後からでも `/plugin` → Installed → fal → Configure options で設定できます。設定したら `/mcp` で `plugin:fal:fal-ai` が接続済みか確認します。Bitwarden を使っている場合は空欄のままにして、下の手順に進んでください。

**4. 確認する**。Claude Code を再起動（または `/reload-plugins`）して「fal doctor を実行して」と頼みます。キーがどこで見つかったか（キー自体は表示しません）、fal がキーを受け付けるか、出力先はどこかが表示されます。

### ほかのエージェント（Codex、Cursor など）

```bash
npx skills add inovue/fal-skills
```

または `skills/fal-skill-creator` をエージェントの skills フォルダーにコピーします。キーは手順 2（または下の Bitwarden）と同じように設定します。fal MCP サーバーは任意です。使う場合は、クライアントの MCP 設定に `https://mcp.fal.ai/mcp` と `Authorization: Bearer <キー>` ヘッダーを追加してください（[auth.md](skills/fal-skill-creator/references/auth.md)）。

### Bitwarden を使っている場合

[Bitwarden Secrets Manager](https://bitwarden.com/products/secrets-manager/) で秘密情報を管理していれば、キーを Bitwarden の外に出す必要はありません。

```bash
bws secret create FAL_KEY "<fal のキー>" <project_id>    # 最初に1回だけ
export BWS_ACCESS_TOKEN="…"      # Claude Code を起動するシェルに設定しておく
export FAL_BWS_SECRET_ID="…"     # 任意：シークレットの ID。検索が速くなる（FAL_KEY という名前が2つある場合は必須）
```

skill は `bws` CLI で `FAL_KEY` という名前のシークレットを探します。`fal doctor` で `fal key: bws secret 'FAL_KEY'` と出れば OK です。

plugin 側の MCP サーバーは bws を使えません。Claude Code が `BWS_ACCESS_TOKEN` などの秘密情報の環境変数を plugin から見えなくしているためです。代わりに、同梱のヘルパーを使ってユーザー単位でサーバーを追加してください。ヘルパーは接続のたびに bws からキーを読みます。

```bash
claude mcp add-json --scope user fal '{"type":"http","url":"https://mcp.fal.ai/mcp","headersHelper":"python3 ~/.claude/plugins/marketplaces/fal-skills/skills/fal-skill-creator/scripts/mcp_headers.py"}'
```

そのあと `/mcp` で `plugin:fal:fal-ai` を Disable にし（キーがないので失敗し続けるため）、`fal` が接続済みになっていることを確認します。ヘルパーのパスは plugin の marketplace のコピーを指しているので、plugin を更新しても動き続けます。

### 更新・削除

```
/plugin marketplace update fal-skills     # そのあと /plugin → fal → Update now を選び、再起動
/plugin uninstall fal@fal-skills          # ユーザー単位のサーバーを追加した場合は claude mcp remove --scope user fal も
```

## 使い方の例

- 「fal で 1080p・開始と終了フレーム指定ができる動画モデルを、1 本 0.5 ドル以内で探して」
- 「FLUX dev をプロファイル化して。16:9 のブログヘッダーが主な用途」
- 「さっきの画像を 5 秒の縦動画にして、そのあとアップスケールして」
- 「ファンタジー系のアイテムアイコンを 12 個、同じ画風で、透過 PNG で作って」（sprite-sheet ワークフロー）
- 「今の手順をワークフロー skill にしてチームに配りたい」

保存先は `./fal-outputs/<日付>/<run_id>/` です（`FAL_OUTPUT_DIR` で変更できます）。履歴は `index.jsonl` に残ります。

詳しくは [README.md](README.md) と [SKILL.md](skills/fal-skill-creator/SKILL.md) を見てください。
