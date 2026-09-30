# fal-skills（日本語）

**fal.ai のどのモデルにも「そのモデルにとって最良の入力」を渡し、その上で、作りたいものに合わせたワークフローや skill を設計する Agent Skill です。**

`fal-skill-creator` の考え方は 2 つです。

1. **各モデルに最良の入力を渡す**：モデルごとに、公式ドキュメントや関連情報を調べて「入力ガイド」（`prompting.md`）にまとめます。中身は、プロンプトの構造と守るべきルール、参照画像や音声など入力メディアの条件、効くパラメータ、苦手なこと、そして `{slot}` 付きの**テンプレート**です。生成は必ずテンプレートから組み立てるので、モデルには調査済みの書き方で、依頼ごとに変わる部分だけを差し込んだプロンプトが届きます。
2. **作りたいものに合わせてワークフローや skill を設計する**：完成物、毎回変わる部分と固定する部分、人が判断すべき箇所を確認し、ステップごとにモデルとローカル処理を組み合わせます。ワークフローの各ステップは「プロファイル＋テンプレート」を指定するので、ワークフローや書き出した skill の中でも、モデル呼び出しは常に 1 の品質で行われます。

| 層 | 役割 |
|---|---|
| **プロファイル（1 モデル）** | schema・固定した既定値・プリセット・入力ガイドとテンプレート |
| **ワークフロー（複数モデル）** | fal のモデル・ローカルのスクリプト・人の確認を順につなぐ。プロンプトを渡すステップはテンプレートを指定する |
| **実行コード（1 つ）** | テンプレートの展開、schema 検証、アップロード、実行、保存、`manifest.json` の記録 |

できることは次のとおりです。

1. **要件からモデルを選ぶ**：MCP の `recommend_model` と最新順の検索で候補を集め、schema で条件を満たさないものを外し、番号付きの候補一覧を出します。
2. **プロファイルを作る**：`$ref` を展開した `schema.json`、固定した既定値、プロンプトを入れるフィールド（多くは `prompt`、音声合成なら `text`）を自動で用意します。
3. **入力ガイドを調べて書く**：公式ドキュメント（MCP の `search_docs`、Exa、Web）を調べ、出典付きでまとめます。`fal profile check` が最低限の基準（ルール、テンプレート、入力メディアの条件、出典）を確認し、通るまでは「調査済み」にできません。
4. **テンプレートで生成する**：`fal run -p <profile> -t <テンプレート> --slot 名前=値 …`。どのテンプレートにどの値を入れたかが `manifest.json` に残ります。
5. **パイプライン**：`--from last` や `--from label:タグ` で前の出力を次のモデルの入力につなぎます。ローカルで加工したファイルも `fal ingest` で記録すれば同じようにつなげます。
6. **ワークフロー**：`fal workflow init / check / plan / export`。`plan` は各ステップのコマンドを、テンプレート名と埋めるべきスロット、前のステップの出力ファイル込みで出します。サンプルとして `sprite-sheet`（GPT Image 2.5 で透過シートを生成 → 必要なときだけ背景除去 → 1 つずつ透過 PNG に分割）と `keyframe-to-video`（GPT Image 2.5 でキーフレーム → 承認 → H3 Max で動画化）を同梱しています。
7. **Export**：プロファイルもワークフローも単体で動く skill として書き出せます。調査が済んでいないプロファイルや、テンプレートのないステップがあると書き出しは止まります。

**調査済みガイドを同梱**：GPT Image 2.5（Sunburst／Flare、生成と編集）、MiniMax H3 Max（画像→動画、テキスト→動画）、Ideogram Remove Background は、テンプレート・入力ルール・実際の価格表・実測した事実（GPT Image 2.5 の 16:9 プリセットは 1088×608 しか出ないので 1920×1088 を指定する、など）をまとめたガイド付きです。`fal profile init` するとそこから始まります。

**実際の価格を表示**：ガイドにモデルページの価格表（解像度・品質・サイズ・秒数別）を持たせているので、実行時と `--dry-run` で実際の金額が出ます（例：H3 Max 1080P × 10 秒 ≈ $1.60。API の単価表示は「$0.025/秒」だけ）。表示のみで、実行は止めません。

費用の自動ブロック（コストガード）は 1.2 で廃止しました。動画・3D・バッチは実行前に単価を示してユーザーに確認し、1 ステップずつ結果を見てから次に進む、という運用で守ります。

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
export BWS_ACCESS_TOKEN_FILE=~/.config/bws/token   # トークンだけを書いたファイル（chmod 600）。または:
# export BWS_ACCESS_TOKEN="…"   # トークンそのもの。このシェルから起動した全プロセスから見える
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
- 「FLUX dev をプロファイル化して、公式の書き方を調べてテンプレートにして。16:9 のブログヘッダーが主な用途」
- 「nano-banana で商品写真を作りたい。いい結果が出る書き方で」
- 「さっきの画像を 5 秒の縦動画にして、そのあとアップスケールして」
- 「ファンタジー系のアイテムアイコンを 12 個、同じ画風で、透過 PNG で作って」（sprite-sheet ワークフロー）
- 「毎週、商品写真から 5 秒の広告動画を作っている。これを skill にしたい」（ワークフロー設計）
- 「今の手順をワークフロー skill にしてチームに配りたい」

保存先は `./fal-outputs/<日付>/<run_id>/` です（`FAL_OUTPUT_DIR` で変更できます）。履歴は `index.jsonl` に残ります。

詳しくは [README.md](README.md) と [SKILL.md](skills/fal-skill-creator/SKILL.md) を見てください。
