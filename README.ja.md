# fal-skills（日本語）

**fal.ai の 1,500 以上のモデルを、コーディングエージェントから安定して使い回せる生成器にする Agent Skill です。**

`fal-skill-creator` がやることは次のとおりです。

1. **最新順のモデル検索**：fal のモデル一覧 API には並び替えの指定がありません。そこで全件を取得してローカルで日付順に並べ、6 時間キャッシュします。
2. **スキーマからプロファイルを作る**：`openapi.json?endpoint_id=…` を取得して `$ref` を展開し、`schema.json` にまとめます。既定値は `defaults.json` に固定します。
3. **既定値の確認（人が確認する工程）**：出力を左右するパラメータだけを見せて、ユーザーに確認します。
4. **プロンプト調査**：公式ドキュメントを Exa か Web で調べ、テンプレート（`{slot}` 付き）と方針を出典付きで `prompting.md` にまとめます。
5. **生成**：スキーマ検証、費用見積もり（上限を超えたら人に確認）、キュー投入、待機、保存を行います。結果は `manifest.json` に記録されます。
6. **パイプライン**：`--from last` で、直前の出力を次のモデルの入力（image_url など）に自動でつなぎます。
7. **Export**：プロファイルを、単体で動く `fal-<model>` skill として書き出せます（npx skills で配布可能）。

## インストール

```bash
npx skills add OWNER/fal-skills
# Claude Code プラグインとして
/plugin marketplace add OWNER/fal-skills
/plugin install fal@fal-skills
```

## キーの設定

`FAL_KEY` 環境変数を使うか、Bitwarden Secrets Manager を使います。後者は `BWS_ACCESS_TOKEN` を設定し、名前が `FAL_KEY` のシークレットを置いてください（`FAL_BWS_SECRET_ID` で ID を直接指定することもできます）。キーを表示したり、コマンドライン引数やディスクに出したりすることはありません。

## 使い方の例

- 「fal で一番新しい text-to-video モデルを教えて」
- 「FLUX dev をプロファイル化して。16:9 のブログヘッダーが主な用途」
- 「さっきの画像を 5 秒の縦動画にして、そのあとアップスケールして」
- 「Kling の image-to-video を skill にしてチームに配りたい」

保存先は `./fal-outputs/<日付>/<run_id>/` です（`FAL_OUTPUT_DIR` で変更できます）。履歴は `index.jsonl` に残ります。

詳しくは [README.md](README.md) と [SKILL.md](skills/fal-skill-creator/SKILL.md) を見てください。
