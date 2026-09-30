# CLI reference

`fal` = `uv run <skill-dir>/scripts/fal.py`. Every command accepts `--json` (machine output on stdout) and `--out DIR`
(output root). `fal <command> --help` shows the authoritative flag list.

## Contents
1. Discovery: models, pricing, schema
2. Profiles
3. Runs
4. History, local files, and export
5. Workflows
6. File formats
7. Environment variables

## 1. Discovery

| command | purpose |
|---|---|
| `models search [terms…] [-c CATEGORY] [-n 15] [--since DAYS] [--include-training] [--include-inactive] [--refresh]` | Newest-first search. Terms are ANDed. |
| `models categories` | Categories with model counts. |
| `models show ENDPOINT` | Metadata plus the live price. |
| `pricing ENDPOINT…` | Unit prices (needs a key). |
| `schema ENDPOINT [--json [--full]]` | Parameter summary; `--full` returns the compact input and output schemas. |

The fal MCP server (bundled with the Claude Code plugin) adds `recommend_model`, `search_models`,
`get_model_schema`, `get_pricing` and `search_docs`. Use them for discovery only; generate with `fal run`.

For ad-hoc exploration with jq, the raw OpenAPI document is saved as each profile's `openapi.json`:
```bash
jq '.components.schemas | keys' "$(fal profile path <slug>)/openapi.json"
jq '.input.properties | to_entries[] | {k:.key, d:.value.default, e:.value.enum}' "$(fal profile path <slug>)/schema.json"
```

## 2. Profiles

| command | purpose |
|---|---|
| `profile init ENDPOINT [--slug S] [--scope user\|project] [--force]` | Create a profile from the schema. |
| `profile list` / `profile show P` / `profile path P` | Inspect profiles. `P` can be a slug, an endpoint id, or a directory. |
| `profile set P key=value… [--unset KEY]` | Pin defaults (validated against the schema). |
| `profile preset P NAME key=value… [--delete]` | Named argument bundles, used with `run --preset NAME`. |
| `profile meta P [--max-usd X] [--prompting-status researched\|stale\|unresearched] [--notes TEXT]` | Cost guard and research status. |
| `profile refresh P` | Re-fetch the schema and pricing, then report drift and broken defaults. |
| `profile remove P` | Delete the profile directory. |

## 3. Runs

```
run (-p PROFILE | -e ENDPOINT)
    [--prompt TEXT] [--set k=v]… [--input JSON] [--input-file F] [--preset NAME]
    [--from REF]… [--batch F.jsonl --concurrency 3] [--label TAG]
    [--max-cost USD] [--yes] [--dry-run] [--no-wait] [--timeout 1800] [--no-download] [--mock RESULT.json]
```

- Merge order, where later wins: profile defaults < preset < `--input` / `--input-file` < `--set` < `--prompt`.
- Special values: `@path` uploads a local file. `from:REF[#sel]` uses an earlier run's output (see pipelines.md).
- `--dry-run` resolves everything except uploads, validates, prices, and prints the result. Nothing is billed.
- `--mock` treats a JSON file as fal's result and runs the whole save path (for tests and demos).
- `fetch RUN`, `status RUN`, `cancel RUN`: `RUN` is a run directory, a run id, or `last` (the newest of any status).
- REF (for `--from`, `from:REF`, `runs show`, `runs files`): `last`, `last~N`, `label:TAG`, `label:TAG~N`, a run id,
  a run directory, or a manifest path.
- Pricing units: per image, megapixel, second of output, request, or compute second (GPU time). GPU-time prices
  can't be estimated from the arguments; the guard assumes up to 60 s per request.

## 4. History, local files, and export

| command | purpose |
|---|---|
| `runs list [-n 20]` | Recent completed runs from `index.jsonl`. |
| `runs show [REF]` | Print a manifest (default `last`). |
| `runs files [REF] [--kind image\|video\|audio\|3d\|file]` | A run's files, one path per line. |
| `ingest PATH… [--label TAG] [--parent REF]… [--note TEXT] [--move]` | Record local files (a local step's output) as a run with a manifest, so `--from` can use them. Directories are expanded; `--move` deletes the sources after copying. |
| `export P [--dest .claude/skills] [--name fal-x] [--force]` | Write a standalone skill with the runtime vendored in. |
| `doctor` | Check the environment, key source, network, MCP sign-in mode, and directories. |

## 5. Workflows

| command | purpose |
|---|---|
| `workflow init NAME [--example sprite-sheet] [--scope user\|project] [--force]` | Scaffold a workflow, or copy a bundled example. |
| `workflow list` | Workflows and bundled examples. |
| `workflow show [W]` / `workflow path [W]` | Print `workflow.json` / the directory. |
| `workflow check [W]` | Validate steps, profiles, presets, scripts and placeholders; estimate one run's cost. Exits 2 on errors. |
| `workflow plan [W]` | Each step's command with earlier outputs filled in, the next step, and what each step waits for. |
| `workflow export [W] [--dest .claude/skills] [--name fal-x] [--force]` | Bundle the workflow, its profiles, its scripts and the runtime as a standalone skill. |

`W` is a name or a directory; omit it inside an exported workflow skill. See workflows.md.

## 6. File formats

**profile.json** (`format: fal-profile@1`): `slug`, `endpoint_id`, `display_name`, `category`, `description`,
`license_type`, `model_date`, `documentation_url`, `playground_url`, `created_at`, `schema_fetched_at`,
`runtime_version`, `pricing{unit_price,unit,currency,fetched_at}`, `cost_guard{max_usd}`, `prompting_status`, `notes`.

**schema.json**: `{endpoint_id, category, documentation_url, playground_url, input, output}`. `input` and `output`
are JSON Schemas with `$ref`s inlined, `anyOf [X, null]` collapsed to `type: [X, "null"]`, and descriptions and
examples trimmed. `x-fal-order-properties` keeps fal's display order.

**defaults.json**: a flat object of arguments merged under every call. **presets.json**: `{name: {args…}}`.

**prompting.md**: see prompt-research.md.

**workflow.json** (`format: fal-workflow@1`) and **WORKFLOW.md**: see workflows.md.

## 7. Environment variables

| variable | default | purpose |
|---|---|---|
| `FAL_KEY` / `FAL_KEY_ID`+`FAL_KEY_SECRET` | — | API key (see auth.md) |
| `BWS_ACCESS_TOKEN` or `BWS_ACCESS_TOKEN_FILE`, `FAL_BWS_SECRET_ID`, `FAL_BWS_SECRET_NAME`, `BWS_PROJECT_ID` | —, —, `FAL_KEY`, — | Bitwarden lookup (the `_FILE` form keeps the token out of process environments) |
| `FAL_OUTPUT_DIR` | `./fal-outputs` | output root |
| `FAL_SKILLS_HOME` | `~/.fal-skills` | user profiles and workflows live in `$FAL_SKILLS_HOME/profiles` and `/workflows` |
| `FAL_PROFILES_DIR` | — | use only this profiles directory (disables the project/user lookup; an exported workflow skill's bundled profiles still come first) |
| `FAL_MAX_COST` | `1.00` | default per-invocation cost limit in USD |
| `XDG_CACHE_HOME` | `~/.cache` | catalog, schema, and upload caches in `fal-skills/` |
| `FALKIT_DEBUG` | — | show tracebacks |
