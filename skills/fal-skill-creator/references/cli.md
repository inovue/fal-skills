# CLI reference

`fal` = `uv run <skill-dir>/scripts/fal.py`. Every command accepts `--json` (machine output on stdout) and `--out DIR`
(output root). `fal <command> --help` shows the authoritative flag list.

## Contents
1. Discovery: models, pricing, schema
2. Profiles
3. Runs
4. History and export
5. File formats
6. Environment variables

## 1. Discovery

| command | purpose |
|---|---|
| `models search [terms…] [-c CATEGORY] [-n 15] [--since DAYS] [--include-training] [--include-inactive] [--refresh]` | Newest-first search. Terms are ANDed. |
| `models categories` | Categories with model counts. |
| `models show ENDPOINT` | Metadata plus the live price. |
| `pricing ENDPOINT…` | Unit prices (needs a key). |
| `schema ENDPOINT [--json [--full]]` | Parameter summary; `--full` returns the compact input and output schemas. |

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

## 4. History and export

| command | purpose |
|---|---|
| `runs list [-n 20]` | Recent completed runs from `index.jsonl`. |
| `runs show [REF]` | Print a manifest (default `last`). |
| `export P [--dest .claude/skills] [--name fal-x] [--force]` | Write a standalone skill with the runtime vendored in. |
| `doctor` | Check the environment, key source, network, and directories. |

## 5. File formats

**profile.json** (`format: fal-profile@1`): `slug`, `endpoint_id`, `display_name`, `category`, `description`,
`license_type`, `model_date`, `documentation_url`, `playground_url`, `created_at`, `schema_fetched_at`,
`runtime_version`, `pricing{unit_price,unit,currency,fetched_at}`, `cost_guard{max_usd}`, `prompting_status`, `notes`.

**schema.json**: `{endpoint_id, category, documentation_url, playground_url, input, output}`. `input` and `output`
are JSON Schemas with `$ref`s inlined, `anyOf [X, null]` collapsed to `type: [X, "null"]`, and descriptions and
examples trimmed. `x-fal-order-properties` keeps fal's display order.

**defaults.json**: a flat object of arguments merged under every call. **presets.json**: `{name: {args…}}`.

**prompting.md**: see prompt-research.md.

## 6. Environment variables

| variable | default | purpose |
|---|---|---|
| `FAL_KEY` / `FAL_KEY_ID`+`FAL_KEY_SECRET` | — | API key (see auth.md) |
| `BWS_ACCESS_TOKEN`, `FAL_BWS_SECRET_ID`, `FAL_BWS_SECRET_NAME`, `BWS_PROJECT_ID` | —, —, `FAL_KEY`, — | Bitwarden lookup |
| `FAL_OUTPUT_DIR` | `./fal-outputs` | output root |
| `FAL_SKILLS_HOME` | `~/.fal-skills` | user profiles live in `$FAL_SKILLS_HOME/profiles` |
| `FAL_PROFILES_DIR` | — | use only this profiles directory (disables the project/user lookup) |
| `FAL_MAX_COST` | `1.00` | default per-invocation cost limit in USD |
| `XDG_CACHE_HOME` | `~/.cache` | catalog, schema, and upload caches in `fal-skills/` |
| `FALKIT_DEBUG` | — | show tracebacks |
