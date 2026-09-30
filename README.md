# fal-skills

**Give every fal.ai model its best input, then design workflows and skills around what you want to make.**

`fal-skill-creator` is an [Agent Skill](https://agentskills.io) for Claude Code, Codex, Cursor, and any agent that
can run shell commands. It is built on two ideas:

1. **Every model gets its best input.** For each model, the agent researches the official guides once and writes an
   input guide: prompt structure and rules, what reference media works, the parameters that matter, limitations, and
   named `{slot}` **templates**. Every generation renders its prompt from a template, so the model always receives
   the researched structure with only the request-specific parts filled in.
2. **Workflows and skills are designed from what you want to make.** The agent works out the finished asset, what
   varies and what stays fixed, and where a person decides, then picks a model per step and connects them with
   local processing. Each step names a profile and a template, so every model call inside a workflow or an exported
   skill gets the quality of idea 1.

```
"make 12 matching fantasy item icons as transparent PNGs, and a skill so we can do it again"
   → direction: assets, style, size, repeat use → design: sheet → background removal → split
   → nano-banana + birefnet profiles, prompting guides researched from official docs
   → fal workflow plan: fal run -p nano-banana --template …/WORKFLOW.md#sheet --slot item_list=… …
   → 12 PNGs + manifests → fal workflow export → .claude/skills/fal-item-icons/
```

[日本語 README](README.ja.md)

## Why

Calling fal from an agent usually means prompting a video model the way you'd prompt an image model, guessing
parameter names, burning retries on 422 errors, and losing track of which file came from which request. This skill
fixes that with a small amount of structure:

| | |
|---|---|
| **Bundled research** | GPT Image 2.5 (Sunburst/Flare, text-to-image and edit), MiniMax H3 Max (image-to-video, text-to-video) and Ideogram Remove Background ship with researched guides: templates, input rules, real price tables and measured facts (the 16:9 size presets on GPT Image 2.5 give only 1088×608; ask for 1920×1088). `profile init` starts from them. |
| **Researched input guides** | For each model, the agent reads the official docs and writes `prompting.md`: key rules with citations, prompt structure, input media rules, parameter advice, limitations, sources. `fal profile check` enforces a minimum standard; a profile can't be marked researched until it passes. |
| **Templates, not ad-hoc prompts** | `fal run -t product-shot --slot product=… --slot surface=…` renders a researched template into the model's prompt field (`prompt`, or `text` for speech). Missing or misspelled slots fail before anything is sent, optional parts drop cleanly, Japanese slipped into an English template is flagged, and the manifest records the template and values. |
| **Real prices** | Each guide carries the model page's price table (by resolution, quality, size, duration), so every run and `--dry-run` prints what it will actually cost, e.g. H3 Max 1080P × 10 s ≈ $1.60 where the API reports only "$0.025 per second". Information only; nothing is blocked. |
| **Model choice from requirements** | The bundled fal MCP server's `recommend_model` plus a newest-first catalog search, then each finalist's schema is checked against the hard requirements (durations, resolutions, inputs). |
| **Schema-validated profiles** | Each model's OpenAPI schema is compacted and used to validate every call before it is sent. Defaults are pinned so upstream changes don't silently change your results. |
| **Workflow design** | Workflows combine fal models, local scripts and review steps. Each prompted step names a template; `workflow check` verifies them, `workflow plan` prints each step's command with the slots to fill and earlier outputs wired in, and `workflow export` refuses steps whose model hasn't been researched. Optional steps with fallbacks (skip background removal when the image already came back transparent). Bundled examples: `sprite-sheet` and `keyframe-to-video` (GPT Image 2.5 → approval → H3 Max). |
| **Pipelines** | Every run writes `manifest.json` (with duration, size and audio measured locally). `--from last` wires the previous output into one matching input of the next model (image → video → upscale); a two-variant run never becomes both a start and an end frame. |
| **Production behavior** | Queue-based with resume (`fetch`), retries with backoff, atomic writes, uploads cached by hash and only after every request validates, batch runs with concurrency, stable exit codes, `--json` everywhere, `--dry-run` and `--mock`. |
| **Standalone export** | `fal export <profile> --description "<your use case>"` or `fal workflow export` produces a self-contained skill you can share or publish. |

There is no automatic spending limit (the cost guard was removed in 1.2): the agent confirms video, 3D and batch runs
with you, showing the unit price, and runs multi-step work one step at a time.

## Install

You need a fal account and an API key (https://fal.ai/dashboard/keys), plus
[uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`). The skill's Python
dependencies install automatically on first run.

### Claude Code (recommended)

**1. Install the plugin.** It contains the skill and the fal MCP server.

```
/plugin marketplace add inovue/fal-skills
/plugin install fal@fal-skills
```

**2. Give the skill your key.** The skill reads `FAL_KEY` from the environment Claude Code was started in:

```bash
export FAL_KEY="…"          # in your shell profile, or a gitignored .envrc
```

Using Bitwarden Secrets Manager instead? Skip `FAL_KEY`: see [Bitwarden users](#bitwarden-users) below.

**3. Connect the fal MCP server** (optional, for model recommendations). When the plugin asks for a
"fal API key", paste your key; it goes to the OS credential store, not to `settings.json`. You can also set it
later in `/plugin` → Installed → fal → Configure options. Then check `plugin:fal:fal-ai` in `/mcp`.
Bitwarden users: leave it empty and follow the section below.

**4. Check.** Restart Claude Code (or run `/reload-plugins`) and ask: *"run fal doctor"*. It shows where the key
was found (never the key itself), whether fal accepts it, and where outputs go.

### Other agents (Codex, Cursor, …)

```bash
npx skills add inovue/fal-skills
```

Or copy `skills/fal-skill-creator` into your agent's skills directory. Set `FAL_KEY` (or Bitwarden, below) as in
step 2. The fal MCP server is optional: add `https://mcp.fal.ai/mcp` with an `Authorization: Bearer <key>` header
in your client's MCP settings ([auth.md](skills/fal-skill-creator/references/auth.md)).

### Bitwarden users

If you keep secrets in [Bitwarden Secrets Manager](https://bitwarden.com/products/secrets-manager/), the key never
needs to leave it:

```bash
bws secret create FAL_KEY "<your fal key>" <project_id>    # once
export BWS_ACCESS_TOKEN="…"      # must be set in the shell that starts Claude Code
export FAL_BWS_SECRET_ID="…"     # optional: the secret's id, a faster lookup (needed if two secrets are named FAL_KEY)
```

The skill finds the secret named `FAL_KEY` through the `bws` CLI; `fal doctor` should report
`fal key: bws secret 'FAL_KEY'`.

The plugin's MCP server can't use bws: Claude Code hides credential variables such as `BWS_ACCESS_TOKEN` from
plugins. Instead, add the server at user scope with the bundled helper, which reads the key from bws each time it
connects:

```bash
claude mcp add-json --scope user fal '{"type":"http","url":"https://mcp.fal.ai/mcp","headersHelper":"python3 ~/.claude/plugins/marketplaces/fal-skills/skills/fal-skill-creator/scripts/mcp_headers.py"}'
```

Then, in `/mcp`, disable `plugin:fal:fal-ai` (it has no key and would keep failing), and check that `fal` shows as
connected. The helper path points at the plugin's marketplace copy, so it keeps working when the plugin updates.

### Update or remove

```
/plugin marketplace update fal-skills     # then /plugin → fal → Update now, and restart
/plugin uninstall fal@fal-skills          # plus `claude mcp remove --scope user fal` if you added it
```

## Use it

Talk to your agent:

- "What are the newest text-to-video models on fal?"
- "Set up FLUX dev as a profile and research how to prompt it. I mostly need 16:9 blog headers."
- "Generate 4 product shots of a matte black water bottle with the recraft profile."
- "Make a skill for Kling 2.1 image-to-video so my team can use it."
- "Take the last image and turn it into a 5s vertical clip, then upscale it."
- "Which fal model can do a 1080p video with a start and an end frame, under $0.50?"
- "Make me 12 matching fantasy item icons as separate transparent PNGs." (sprite-sheet workflow)
- "Every week I turn product photos into 5 s ads. Make that a skill." (workflow design)
- "Turn what we just did into a workflow skill the team can reuse."

Or use the CLI directly (`fal` = `uv run skills/fal-skill-creator/scripts/fal.py`):

```bash
fal models search kling -c image-to-video -n 5
fal profile init fal-ai/flux/dev
fal profile set flux-dev image_size=landscape_16_9 output_format=png
# (the agent researches prompting.md here)
fal profile check flux-dev && fal profile meta flux-dev --prompting-status researched
fal profile templates flux-dev
fal run -p flux-dev -t general --slot subject="a red fox" --slot action="curled up asleep" \
  --slot setting="in fresh snow" --slot style="watercolor" --slot composition_or_camera= --slot lighting= --dry-run
fal run -p flux-dev -t general --slot … --label fox
fal run -p kling-i2v --from last -t camera-move --slot … --label fox-video
fal runs list
fal export flux-dev --dest ~/.claude/skills --description "16:9 blog header images in our watercolor house style"

fal workflow init my-icons --example sprite-sheet
fal workflow check my-icons            # missing profiles (with the command to create them), templates, research status
fal workflow plan my-icons             # the next step's exact command, with its template and the slots to fill
fal workflow export my-icons --dest ~/.claude/skills
```

Exit codes: `0` ok · `2` fix the arguments, a missing slot, or a guide that fails its check · `4` auth ·
`5` fal error · `6` still running (`fal fetch`).

## How it works

```
skills/fal-skill-creator/
├── SKILL.md                  # what the agent follows (choose → profile → research → generate → chain → design)
├── scripts/fal.py            # single CLI entry (PEP 723 inline deps, runs with `uv run`)
│   └── falkit/               # catalog · schema · profiles · templates · runner · workflows · export
│   └── mcp_headers.py        # optional key-based auth helper for the fal MCP server at user scope
├── references/               # loaded on demand: cli, prompt-research, pipelines, workflows, auth, troubleshooting
└── assets/                   # templates, and workflows/sprite-sheet (example workflow)

~/.fal-skills/profiles/<slug>/     # per-model data (or ./.fal/profiles with --scope project)
  profile.json schema.json openapi.json defaults.json presets.json prompting.md (input guide + templates)
~/.fal-skills/workflows/<name>/    # multi-step processes (or ./.fal/workflows)
  workflow.json WORKFLOW.md (step templates) scripts/

./fal-outputs/                     # runs: media + request.json + result.json + manifest.json, and index.jsonl
```

Models (profiles) and processes (workflows) are **data**, and the **code** is one tested runtime. Adding the 50th
model or the 10th workflow adds no new runtime code and no new failure modes. Either becomes a separate skill only
when you export it.

## Development

```bash
make test        # offline tests: no key, no network, no cost
make test-live   # plus one real flux/schnell call (~$0.003)
make lint validate
```

Contributions are welcome, especially bundled workflow examples, media-kind heuristics for unusual input names,
prompt-field names for models that don't use `prompt`, and fixes where a model's schema breaks compaction (please
attach the endpoint id).

## License

MIT
