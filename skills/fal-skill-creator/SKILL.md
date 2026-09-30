---
name: fal-skill-creator
description: Generate images, video, audio, speech and 3D with fal.ai models within budget, and package what works as skills. Picks the right model for a requirement (fal MCP recommendations plus a newest-first catalog search), turns it into a profile with pinned defaults and researched prompt templates, runs it behind a cost guard, chains outputs between models, and builds workflow skills that combine several models with local processing (e.g. sprite sheet → background removal → split into assets). Use this whenever the user mentions fal, fal.ai or fal.com, names a model hosted on fal (FLUX, Kling, Veo, Seedance, nano-banana, Recraft, Ideogram, etc.), asks which model is best or cheapest for a media task, wants to generate or edit media through an API, asks for a skill for a fal model or for a multi-step media pipeline, or wants to pipe one generation into another, even if they don't say "skill" or "profile". Not for local Stable Diffusion/ComfyUI or other providers' native APIs.
license: MIT
compatibility: Python 3.10+ via uv (recommended) or pip. Network access to fal.ai. A fal API key in FAL_KEY or in Bitwarden Secrets Manager (bws). The fal MCP server is optional and comes with the Claude Code plugin. Works in any agent that can run shell commands.
metadata:
  version: 1.1.1
  homepage: https://github.com/inovue/fal-skills
---

# fal skill creator

This skill makes fal models reliable to use, one model at a time or several together. It works in three layers:

| layer | what it is | where it lives |
|---|---|---|
| **Discovery** | Finding and comparing models: the fal MCP server (`recommend_model`, `search_models`, `get_model_schema`, `get_pricing`, `search_docs`) and this skill's `fal models …` commands | MCP server `fal-ai`; `scripts/fal.py` |
| **Model profiles** | One folder per model: schema, pinned defaults, presets, price snapshot, researched `prompting.md` | `~/.fal-skills/profiles/` (or `./.fal/profiles/` with `--scope project`) |
| **Workflows** | Several steps (fal models plus local scripts) that turn one requirement into finished assets | `~/.fal-skills/workflows/` (or `./.fal/workflows/`) |

Profiles and workflows are data. One tested runtime (`scripts/fal.py`) validates inputs, uploads files, checks cost,
submits to fal's queue, waits, downloads, and writes a manifest for every model, so adding a model or a workflow
never adds code that could break. Either one can be exported as a standalone skill.

## The fal MCP server and the CLI: who does what

The Claude Code plugin connects the official fal MCP server (`https://mcp.fal.ai/mcp`) as `plugin:fal:fal-ai`. It
authenticates with the fal API key the user enters in the plugin's options (`/plugin` → fal → Configure options). If
the server shows as failed in `/mcp`, the key is missing or wrong: point the user there, or to the user-scope setup
in `references/auth.md`. Other agents can add the server by hand.

- **Use the MCP server to look things up**: `recommend_model` for candidates from a plain-language requirement,
  `search_models`, `get_model_schema` and `get_pricing` for details, and `search_docs` for fal's documentation.
- **Generate only with `fal run`**, never with the MCP server's `run_model` or `submit_job`. `fal run` is what
  checks the cost limit before paying, validates arguments against the schema, saves files locally, and writes the
  manifest that later steps need. Use the MCP execution tools only when the user explicitly asks for them.
- **Without the MCP server** everything still works: `fal models search`, `fal models show` and `fal schema` cover
  discovery. Mention once that the plugin adds `recommend_model`, then carry on.
- **Leave the account tools alone.** The server also manages the user's fal assets, collections and entities
  (`delete_asset`, `delete_collection`, …). Don't call them unless the user asks for exactly that.
- **Treat `recommend_model` as candidates, not answers.** It can suggest models of the wrong modality (a video tool
  for an image task), so check every candidate's schema (A1 step 3).

## Running the CLI

Every command below is `fal …`, which is short for:

```bash
uv run <this-skill-dir>/scripts/fal.py …
```

uv reads the inline dependency block, so no install step is needed. Without uv, run
`pip install "fal-client>=1.0,<2" httpx jsonschema` and use `python3 <this-skill-dir>/scripts/fal.py` instead.
Add `--json` whenever you parse the output. Progress goes to stderr, so stdout stays clean JSON.

Exit codes tell you what to do next:

| code | meaning | what to do |
|---|---|---|
| 0 | success | — |
| 2 | bad arguments or schema violation | read the message, fix the arguments (`fal schema <id>` helps) |
| 3 | the cost guard needs approval | show the user the estimate; rerun with `--yes` only after they agree |
| 4 | no key, or key rejected | walk the user through `references/auth.md` |
| 5 | fal rejected the request or the job failed | read the error; usually a bad argument value or a content-policy block |
| 6 | timeout; the job is still running on fal | `fal fetch <run_dir>` later, and don't resubmit (resubmitting bills twice) |

On first use in a session, or after any code 4, run `fal doctor`. It checks the key (without printing it),
the network, and the output folders.

## Pick the workflow

- The user asks **which model** fits a task, or no profile fits their request → **A1. Choose a model**.
- The user wants media and a suitable profile exists (`fal profile list`) → **B. Generate**.
- The user names a model or a task but no profile fits → **A. Create a profile**, then **B**.
- The user wants "a skill for model X" → **A**, then **D. Export**.
- The user wants several steps once (image → video, video → upscale, TTS → lipsync) → **C. Pipelines**.
- The user wants a **repeatable multi-step process** ("make icon sets", "turn product photos into ads"), or a skill
  for one → **E. Workflow skills**. A matching workflow may already exist: `fal workflow list`.
- The user names an exact endpoint id for a one-off job and hasn't asked for reuse → skip profile creation and
  research. Run `fal schema <id>`, then `fal run -e <id> …`. Validation and the cost guard still apply. Afterwards,
  offer to turn the model into a profile if the user seems likely to use it again. Building profiles and doing
  research for a one-off job roughly doubles the time for no benefit.

## A. Create a profile (choose → schema → defaults → research)

### A1. Choose a model from the requirement

1. **Pin down the requirement.** Ask only for what's missing and matters for the choice, in one message:
   - what goes in and comes out (text → image, start image → video, start + end frame, audio → lip-sync…)
   - length, resolution and aspect ratio
   - whether it needs audio, readable text in the image, or a consistent character or product
   - whether it's for commercial use (licence)
   - budget per result, and how many results
2. **Collect candidates**, using both sources when you have them:
   - `recommend_model` (MCP) with the requirement in plain language. It knows fal's own view of fitness.
   - `fal models search <terms> -c <category> -n 10 --prices` for a strict newest-first list with unit prices.
     Terms are ANDed over id, name, tags and description. Use `--since 90` for recent models and
     `fal models categories` when the task type is unclear.
3. **Check the finalists against the hard requirements.** For the top 3–5, read the parameters with
   `fal schema <id>` or `get_model_schema`: supported durations, resolutions and aspect ratios, and which image,
   video and audio inputs exist. Parameter names differ between models (`duration` "5" vs "5s", `tail_image_url` vs
   `end_image_url`), so read them rather than guess. Drop every model that can't do what was asked.
4. **Present a numbered shortlist**: name, endpoint id, release date, price with its unit, and one line on why it
   fits or what it trades off. Neither fal's catalog nor schemas carry quality scores, so say so when the user
   asks for "the best". Order by fit, then recency, then price. Offer to run the top two once on the same prompt
   (`--dry-run` first for the cost) and compare the results. That comparison is the only reliable quality check.
   Ask the user to reply with a number. A plain numbered message works better than a multiple-choice widget,
   which usually allows only a few options.

Skip the question when the user already gave an exact endpoint id. If you are running unattended, pick the newest
active model that meets every hard requirement, and say which one you picked and why.

### A2. Create the profile from the schema

```bash
fal profile init <endpoint_id> [--slug short-name] [--scope project]
```

This fetches `https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<id>` and inlines every `$ref`. It saves
`schema.json` (the compact version), `openapi.json` (raw, for jq), and `defaults.json`, which pins the schema's
current defaults so that later upstream changes don't silently alter results. It also stubs `prompting.md`.

### A3. Confirm defaults with the user (human in the loop)

The printed parameter list is long; most of it doesn't matter to the user. In one message, show only the
parameters that shape results for this kind of model:

- size or aspect ratio, and resolution
- duration and fps (video and audio)
- quality versus speed (steps, acceleration, model tier)
- number of outputs
- output format
- voice or language (speech)
- the safety checker

Give the current default for each and your recommendation, then apply their answers:

```bash
fal profile set <slug> image_size=landscape_16_9 output_format=png
fal profile preset <slug> vertical aspect_ratio=9:16 duration=5     # named bundles for recurring use cases
fal profile meta <slug> --max-usd 2.00                               # per-profile cost limit
```

`profile set` validates against the schema, so a bad value fails right away instead of at generation time.
Mention the unit price (`profile show`) so the user knows what a run costs. Unattended, keep the pinned defaults.

### A4. Research how to prompt this model

Follow `references/prompt-research.md`. In short:

1. Collect official guidance (the fal model page and API docs, fal's blog and learn pages, the model maker's own
   prompting guide). The MCP server's `search_docs` covers fal's docs. For the rest, prefer Exa search if it is
   available, otherwise web search and fetch.
2. Distill it into the profile's `prompting.md`: key rules, prompt structure, named templates with `{slots}`,
   which parameters matter, limitations, verbatim examples, and cited sources with access dates.
3. Run `fal profile meta <slug> --prompting-status researched`.

This step matters most for output quality: models differ a lot (prose versus tags, camera language, quoted
on-screen text, reference tokens), and one generic prompt style wastes money. Delegate the research to a subagent
when one is available, since it reads many pages that don't need to stay in your context.

### A5. Smoke test

`fal run -p <slug> --prompt "<template-filled prompt>" --dry-run` shows the final arguments and the cost. Then do
one real run with the user's OK, look at the output, and adjust defaults or templates if something is off.

## B. Generate

1. **Read the profile's `prompting.md`**. Find it with `fal profile path <slug>`. Choose the template that fits the
   request, fill every slot from what the user asked for, and invent only what the user left open.
2. **Decide whether to confirm first.** If the request is vague, the run is expensive, or it is the first run of a
   new profile, show the final prompt and key settings in one line and ask. For a clear, cheap request, just run it.
3. **Run it:**
   ```bash
   fal run -p <slug> --prompt "<final prompt>" [--preset name] [--set key=value …] [--label short-tag]
   ```
   - `--set` values are parsed as JSON, then coerced to the schema's type (`duration=10` becomes `"10"` when the
     schema wants a string). Use dotted keys for nested values: `image_size.width=768`.
   - To upload a local file, write `@path` (`--set image_url=@./ref.png`). To reuse an earlier output, write
     `from:REF` (see C).
   - For variations, use `--batch requests.jsonl --concurrency 3`, one JSON overlay per line. The cost guard
     checks the total.
   - For long jobs (video, 3D), use `--no-wait` to return right away, then `fal fetch <run_dir>`.
4. **Check the output yourself before reporting.** Open image files with your file or image viewer and compare
   them against the request: subject, count, text, composition. For video and audio, check the manifest's
   duration and size. If the output misses the request, adjust the prompt using `prompting.md` and offer a rerun.
   Pass `--set seed=<manifest seed>` to change only the prompt.
5. **Report back**: the local file paths, the run id, the estimated cost, and a note on anything notable.

### The cost guard

Every run is priced before it is submitted, using fal's unit pricing (per image, megapixel, second, and so on).
The run is blocked with exit code 3 when the estimate exceeds the limit. The limit comes from `--max-cost`, then the
profile's `max_usd`, then `$FAL_MAX_COST`, then $1.00. When the cost can't be estimated, the run is blocked unless
the unit price is at most $0.05. For models billed by GPU time ("compute seconds"), the guard assumes up to a minute
per request. The guard exists so that a video batch never runs up a bill silently. When it trips, tell the user the
estimate and the reason, and add `--yes` only after they approve. Never add `--yes` pre-emptively.

## C. Pipelines (chaining models)

Each run writes `<out>/<date>/<run_id>/` containing the media files, `result.json` and `manifest.json`, and appends
a line to `<out>/index.jsonl`. The manifest is the contract between steps and between skills. Any fal-* skill, or
any other tool, can consume it.

```bash
fal run -p flux-dev --prompt "…" --label keyframe
fal run -p kling-i2v --from label:keyframe --prompt "slow dolly-in …"   # auto-fills image_url
fal run -p upscaler --set video_url=from:last#video                     # explicit: first video of last run
fal run -p lipsync --set video_url=from:last~1 --set audio_url=from:<run_id>#audio
```

With `--from REF`, empty media inputs are filled by matching media kind (image, video, audio), required fields
first. Every link it makes is printed as `wired: …`, so check those lines. Values you pass explicitly with `--set`
always win. A REF is `last`, `last~N`, `label:TAG` (the newest run with that `--label`), a run id, a run directory,
or a manifest path. `#sel` picks one output: an index, a kind, a field, or `*` for all.

**Local steps.** When you process files yourself between models (crop, split, ffmpeg), record the results with
`fal ingest <files-or-dir> --label <tag> --parent <REF>`. They then get a manifest, and `--from label:<tag>` works
on them like any other run. `fal runs files <REF>` prints a run's files, one per line, for the next local command.

For a multi-step request, run the steps one at a time and look at each intermediate result before paying for the
next, more expensive step. The full manifest schema and recipes are in `references/pipelines.md`.

## D. Export a profile as a standalone skill

```bash
fal export <slug> --dest .claude/skills          # or ~/.claude/skills, or <repo>/skills/ to publish via npx skills
```

This writes `fal-<slug>/` containing SKILL.md (with a trigger description for that model), the profile, and a
vendored copy of this runtime. It runs on its own and can be installed with `npx skills add`. Research the profile
before exporting, because the exported skill is only as good as its `prompting.md`. After updating this skill,
re-export with `--force` to refresh the vendored runtime.

## E. Workflow skills (several models, one requirement)

A workflow turns a repeatable requirement into finished assets through several steps: `fal` steps (each names a
profile), `local` steps (a script in the workflow), and `review` steps (a human decision). Read
`references/workflows.md` before building one. The short version:

```bash
fal workflow init <name> [--example sprite-sheet]   # scaffold, or start from a bundled example
# edit workflow.json (steps) and WORKFLOW.md (what the agent does and checks at each step)
fal workflow check <name>     # structure, missing profiles (with the `profile init` command), cost of one run
fal workflow plan <name>      # the exact command for each step, with earlier outputs filled in; names the next step
fal workflow export <name> --dest .claude/skills     # workflow + its profiles + scripts + runtime → one skill
```

Build it the way you'd build it by hand: run the steps once with the user on a small input, checking each result,
then write down what worked in `WORKFLOW.md`. Rules that keep workflows robust:

- **Steps name profiles, never endpoints.** Upgrading a model then means re-pointing one profile.
- **Workflow-specific processing stays in the workflow's `scripts/`**, not in this runtime.
- **One step at a time, with a check after each paid step.** A bad first image makes every later step wasted money.
- **Make a workflow only for something the user will repeat.** For a one-off chain, use C.

The bundled `sprite-sheet` example draws a set of matching assets on one sheet, removes the background, and splits
the sheet into one transparent PNG per asset.

## Maintenance

- **Schema drift.** When a run fails validation on a profile that used to work, or every few weeks:
  `fal profile refresh <slug>` reports added and removed parameters and any pinned defaults that no longer validate.
- **Stale prompting.** When a model family gets a new version, set `--prompting-status stale` and redo A4.
- **History.** `fal runs list` and `fal runs show last`. `fal status` and `fal cancel` handle in-flight jobs.

## Storage and safety conventions

- Outputs go to `./fal-outputs/` by default (override with `--out` or `$FAL_OUTPUT_DIR`). Media can be large;
  suggest adding `fal-outputs/` to `.gitignore` when working inside a git repo.
- The API key comes from `FAL_KEY`, or from bws (`BWS_ACCESS_TOKEN` or `BWS_ACCESS_TOKEN_FILE`, plus a secret named `FAL_KEY`, or set
  `FAL_BWS_SECRET_ID`). The runtime never prints the key, never passes it as a command-line argument, and never
  writes it to disk. Don't echo it, write it into files, or paste it into commands yourself, and don't run
  `scripts/mcp_headers.py` (an optional MCP auth helper that prints the key). `fal doctor` confirms where the key
  was found.
- Uploaded inputs and generated outputs are stored on fal's CDN at unguessable but public URLs. Only upload
  (`@path`) files the user pointed you to, and check with the user before uploading anything that looks private
  (faces of real people, documents). Uploads happen only after the cost guard passes.
- Price units differ between models (per image, per megapixel, per second, per compute second, per "unit"). When
  comparing models, say what the unit is. GPU-time and opaque "unit" prices can't be estimated exactly.

## Reference files

- `references/cli.md`: every command and flag, the profile and workflow file formats, and environment variables.
- `references/prompt-research.md`: how to research and write `prompting.md` (step A4).
- `references/pipelines.md`: the manifest contract, REF syntax, local steps, and multi-step recipes.
- `references/workflows.md`: building workflow skills: format, design rules, and the sprite-sheet example.
- `references/auth.md`: FAL_KEY and Bitwarden setup, connecting the MCP server, and key rotation.
- `references/troubleshooting.md`: common failures by exit code.
