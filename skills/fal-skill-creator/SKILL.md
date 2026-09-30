---
name: fal-skill-creator
description: Get the best out of fal.ai models, and build workflows and skills around them. Researches each model's official guides into a reusable input guide (prompt templates, input rules for reference media, parameter advice), generates images, video, audio, speech and 3D through those templates, chains outputs between models, and designs multi-step workflow skills (models plus local processing) from what the user wants to make, where every model call uses the researched templates. Use this whenever the user mentions fal, fal.ai or fal.com, names a model hosted on fal (GPT Image, MiniMax H3, FLUX, Kling, Veo, Seedance, nano-banana, Ideogram, etc.), asks which fal model fits a media task, wants better results from a fal model, wants to generate or edit media through fal, asks for a skill or a repeatable pipeline for fal models, or wants to pipe one generation into another, even if they don't say "skill" or "profile". Not for local Stable Diffusion/ComfyUI or other providers' native APIs.
license: MIT
compatibility: Python 3.10+ via uv (recommended) or pip. Network access to fal.ai. A fal API key in FAL_KEY or in Bitwarden Secrets Manager (bws). The fal MCP server is optional and comes with the Claude Code plugin. Works in any agent that can run shell commands.
metadata:
  version: 1.2.0
  homepage: https://github.com/inovue/fal-skills
---

# fal skill creator

This skill has two jobs, and the second depends on the first:

1. **Give every fal model its best input.** Models differ a lot: prose versus tags, what goes first, how on-screen
   text is quoted, how reference images are named, which parameters matter, what a good reference image looks like.
   For each model, research the official guidance once and store it as an **input guide** (`prompting.md`) with
   named **templates**. Every generation renders its prompt from a template, so the model always gets the
   researched structure with only the request-specific parts filled in.
2. **Design workflows and skills around what the user wants to make.** Work out the outcome, pick a model per
   step, and connect them with local processing and human checks. Every model call in a workflow or exported skill
   goes through job 1: a step names a profile and a template, never a raw endpoint with a hand-written prompt.

| layer | what it is | where it lives |
|---|---|---|
| **Profiles** | One folder per model: schema, pinned defaults, presets, and the input guide with its templates | `~/.fal-skills/profiles/` (or `./.fal/profiles/` with `--scope project`) |
| **Workflows** | Steps (fal models, local scripts, reviews) with a template per prompted step | `~/.fal-skills/workflows/` (or `./.fal/workflows/`) |
| **Runtime** | One tested CLI (`scripts/fal.py`) that renders templates, validates against the schema, uploads, submits, waits, downloads, and writes a manifest | this skill |

Profiles and workflows are data, so adding a model or a workflow adds no code. Either can be exported as a
standalone skill.

## The fal MCP server and the CLI

The Claude Code plugin connects the official fal MCP server (`https://mcp.fal.ai/mcp`) as `plugin:fal:fal-ai`,
authenticated with the key the user enters in `/plugin` → fal → Configure options. If it shows as failed in `/mcp`,
the key is missing or wrong: see `references/auth.md`.

- **Use the MCP server to look things up**: `recommend_model` (candidates from a plain-language requirement),
  `search_models`, `get_model_schema`, `get_pricing`, and `search_docs` (fal's documentation, useful in research).
- **Generate only with `fal run`**, never with the MCP server's `run_model` or `submit_job`. `fal run` renders the
  template, validates against the schema, saves files locally, and writes the manifest that later steps need.
- **Without the MCP server** everything still works: `fal models search`, `fal models show` and `fal schema`.
- **Leave the account tools alone** (`delete_asset`, `delete_collection`, …) unless the user asks for exactly that.
- **Treat `recommend_model` as candidates, not answers.** Check each one's schema (A1 step 3).

## Running the CLI

`fal …` is short for `uv run <this-skill-dir>/scripts/fal.py …`. uv reads the inline dependencies, so there is no
install step. Without uv: `pip install "fal-client>=1.0,<2" httpx jsonschema`, then
`python3 <this-skill-dir>/scripts/fal.py`. Add `--json` when you parse output; progress goes to stderr.

| exit | meaning | what to do |
|---|---|---|
| 0 | success | — |
| 2 | bad arguments, schema violation, missing template slot, or a guide that fails `profile check` | read the message and fix it (`fal schema <id>`, `fal profile templates <slug>`) |
| 4 | no key, or key rejected | walk the user through `references/auth.md` |
| 5 | fal rejected the request or the job failed | read the error: usually a bad value or a content-policy block |
| 6 | timeout; the job is still running on fal | `fal fetch <run_dir>` later; don't resubmit (that bills twice) |

On first use in a session, or after exit 4, run `fal doctor`.

## Route the request

- The user asks **which model** fits, or no profile fits → **A1**, then the rest of **A**.
- The user names a model (or an endpoint id) that has no profile → **A2–A5**, then **B**. This includes one-off
  requests: `profile init` takes seconds, and a short research pass (A4, "quick") is what makes the one result good.
  Skip research only for models that take no text and have nothing to tune (a plain background remover).
- A suitable researched profile exists (`fal profile list`) → **B. Generate**.
- Several models once (image → video, TTS → lip-sync) → **C. Chain**, with a researched profile per model.
- Something the user will **repeat**, or a skill for a process or a model → **D. Design a workflow or skill**.
  A matching workflow may already exist: `fal workflow list`.

## A. Build a model profile

### A1. Choose a model from the requirement

1. **Pin down the requirement**, asking only for what's missing and matters, in one message: what goes in and comes
   out; length, resolution and aspect ratio; audio, readable text, or a consistent character or product; commercial
   use (licence); rough budget and quantity.
2. **Collect candidates**: `recommend_model` (MCP) with the requirement in plain language, and
   `fal models search <terms> -c <category> -n 10 --prices` (newest first, with unit prices; `--since 90` for recent
   models, `fal models categories` when the task type is unclear).
3. **Check the finalists' schemas** (`fal schema <id>` or `get_model_schema`): durations, resolutions, aspect ratios,
   and which image, video and audio inputs exist. Names differ between models (`tail_image_url` vs
   `end_image_url`), so read them. Drop every model that can't do what was asked.
4. **Present a numbered shortlist**: name, endpoint id, release date, price with its unit, licence, and one line on
   fit or trade-off. The catalog has no quality scores; when the user wants "the best", offer to run the top two on
   the same template and compare, since that is the only real quality check. Ask them to reply with a number.

Unattended, pick the newest active model that meets every hard requirement and say why.

### A2. Create the profile

```bash
fal profile init <endpoint_id> [--slug short-name] [--scope project]
```

It saves the compact schema, pins the schema's current defaults (so upstream changes don't silently alter results),
detects the prompt field (`prompt`, or `text` for most speech models), and writes `prompting.md`.

**Bundled guides.** For models researched in advance (`assets/guides/index.json`: GPT Image 2.5 Sunburst/Flare
text-to-image and edit, MiniMax H3 Max image-to-video and text-to-video, Ideogram Remove Background), `profile init`
copies the researched guide, its presets and a short slug (`gpt-image`, `gpt-image-edit`, `h3-max-i2v`,
`h3-max-t2v`, `remove-bg`), applies the researched defaults (e.g. GPT Image `quality=medium`, H3
`prompt_expansion_mode=disabled`) and records the real runs that validated the templates. The profile is marked
researched only if the guide still passes the check against the model's live schema. Skim its key rules and
pricing date, confirm the defaults (A3), and skip A4 and A5 unless the check or the model page says otherwise.

### A3. Confirm defaults with the user

Show only the parameters that shape results for this kind of model (size or aspect ratio, resolution, duration and
fps, quality versus speed, number of outputs, output format, voice or language, safety checker, prompt rewriting),
each with the current default, your recommendation and what it does to the price (the guide's pricing table). Model
defaults are often the expensive option: GPT Image 2.5 defaults to `high` quality, 4× the price of `medium`. Apply the answers; `set` validates against the schema:

```bash
fal profile set <slug> image_size=landscape_16_9 output_format=png
fal profile preset <slug> vertical aspect_ratio=9:16 duration=5     # named bundles for recurring use cases
```

Unattended, keep the pinned defaults. Research (A4) may change your recommendation; revisit then.

### A4. Research the input guide

This step decides output quality more than any other. Follow `references/prompt-research.md`. In short:

1. Read the official guidance: fal's model page and API docs (`search_docs` covers fal's docs), the model maker's
   prompting guide, and the model card. Prefer Exa for search when available, otherwise web search and fetch.
2. Write `prompting.md`: key rules with citations, prompt structure, **Inputs** (what reference media works:
   formats, resolution, aspect ratio, how the prompt refers to it), one ```` ```template <name> ```` block per main
   use case plus `general`, the parameters that matter (including any prompt-rewriting switch such as
   `prompt_expansion_mode`), a ```` ```pricing ```` table copied from fal's model page, limitations, verbatim
   examples, and sources.
3. `fal profile check <slug>` until it passes, then `fal profile meta <slug> --prompting-status researched`
   (refused while the check fails). The check fetches every cited source; a page that doesn't exist is an error.

**Depth.** A *full* pass reads 5–15 pages and covers every section; do it for profiles that will be reused or
exported. A *quick* pass (fal's model page plus the maker's guide) is enough for a one-off, as long as the check
passes. Measure what the docs don't say when it matters and it's cheap (e.g. which pixel size each `image_size`
preset really produces, at the lowest quality), and write the finding into the guide with its date. Delegate a full pass to a subagent when one is available; its reading doesn't need to stay in your context.

### A5. Validate with one real run

```bash
fal run -p <slug> -t general --slot subject="…" --slot … --dry-run     # the rendered prompt and final arguments
```

Then one real run with the user's OK. Look at the output: if it doesn't follow the prompt, fix the template or the
key rules, not just this one prompt. When it works, record it: `fal profile meta <slug> --validated-with <run_id>`.

## B. Generate

1. **Read the profile's `prompting.md`** (`fal profile path <slug>`): key rules, Inputs, limitations. If the request
   hits a limitation (text rendering, counting, long durations), tell the user now instead of paying for retries.
2. **Pick a template** (`fal profile templates <slug>` lists them with required and optional slots). For a light
   request ("a cat illustration", "make the cup blue") use `quick`: 1–3 slots. Otherwise pick the template for the
   use case and fill every required slot from the request; invent only what the user left open, following the key
   rules. Optional parts (`[[ … ]]`) are left out by not passing their slots; a required slot can't be empty.
   `{=duration}`-style parts come from the request's parameters, so set those with `--set`. An unknown slot is an
   error, so a typo never silently drops what you meant. If no template fits, write the prompt by hand following the guide, and add the
   new template to `prompting.md` if the use case will recur.
   **Language:** write slot values in the template's language (usually English), translating the user's Japanese;
   keep only text that must appear verbatim (on-screen copy, dialogue) in its original script, in quotes. The run
   warns when Japanese slips into an English template.
3. **Prepare inputs** the way the Inputs section says (crop or resize references, pick the right frame), then pass
   them: `--set image_url=@./ref.png`, or `from:REF` / `--from` for earlier outputs (C).
4. **Confirm first** when the request is vague, the output is video or 3D, it's a batch, or it's the profile's
   first run: show the filled prompt, key settings and the price from `--dry-run` in one message. The price comes
   from the guide's researched table (by resolution, quality, size, duration), not from the API's unit price, which
   is often only the cheapest tier ("$1 per unit" says nothing). For a clear, cheap image request, just run it.
5. **Run:**
   ```bash
   fal run -p <slug> -t <template> --slot key=value … [--preset name] [--set key=value …] [--label short-tag]
   ```
   - `--set` values are JSON, coerced to the schema's type (`duration=10` becomes `"10"` when the schema wants a
     string); dotted keys set nested values (`image_size.width=768`).
   - Variations: `--batch requests.jsonl --concurrency 3`, one JSON object per line (arguments, and
     `"$slots": {...}` to vary slots per line).
   - Long jobs (video, 3D): `--no-wait`, then `fal fetch <run_dir>`.
   - `--prompt "<text>"` instead of `-t` sends a finished prompt as is; use it only when no template applies.
6. **Check the output yourself** against the request: open images; for video and audio, read `duration`, `width`,
   `height`, `has_audio` in the manifest (measured locally when ffprobe is installed), and look at a few frames
   (`ffmpeg -ss 2 -i video.mp4 -frames:v 1 f.png`). If the model rewrites prompts, compare `text.expanded_prompt`.
   If it misses, change slots or the template using the guide, keep the seed (`--set seed=<manifest seed>`) to
   isolate the change, and offer a rerun.
7. **Report**: file paths, run id, the template used, and anything notable.

## C. Chain models

Each run writes `<out>/<date>/<run_id>/` with the media, `result.json` and `manifest.json` (arguments, template and
slots, lineage, outputs), and appends to `<out>/index.jsonl`. The manifest is the contract between steps and skills.

```bash
fal run -p flux-dev -t product --slot … --label keyframe
fal run -p kling-i2v --from label:keyframe -t camera-move --slot …     # auto-fills image_url
fal run -p upscaler --set video_url=from:last#video                      # explicit: first video of the last run
```

Each `--from REF` fills **one** empty media input, by media kind, required inputs first, and prints `wired: …`:
check those lines. It takes the run's first fitting output; `--from REF#1` picks another, `#*` passes all of a run's
outputs into a list input (edit references). One run never spills into a second input, so a two-variant image run
can't become a start frame and an end frame; give a second `--from` (or `--set end_image_url=from:REF`) for that.
Explicit `--set` wins. REF is `last`, `last~N`, `label:TAG`, a run id, a run directory, or a manifest path. Record files you process locally with
`fal ingest <files-or-dir> --label <tag> --parent <REF>` so they chain the same way. Run steps one at a time and
check each result before paying for the next, more expensive one. Details: `references/pipelines.md`.

## D. Design a workflow or skill

Start from what the user wants to make, not from the models. Read `references/workflows.md` before building.

1. **Understand the direction** (one message, only what's missing): the finished asset and who it's for; what varies
   between runs (the inputs the skill will ask for) and what stays fixed (style, format, brand); the quality bar;
   how often it will run; where a human must decide (picking a variant, approving a keyframe).
2. **Sketch the design and get a yes**: a numbered list of steps. For each: model step (which model and why, from
   A1), local step (what the script does), or review step. Put cheap, checkable steps before expensive ones.
   Choose the consistency strategy (one sheet for a matching set, a reference image passed to every step, a fixed
   seed). Say which profiles exist and which need research.
3. **Make every model step research-backed**: create and research each missing profile (A2–A5).
4. **Run it once by hand** on a small input with `--label <workflow>.<step>`, checking each result with the user.
5. **Write it down**: `fal workflow init <name> [--example sprite-sheet|keyframe-to-video]`. In `workflow.json`,
   each prompted fal step names its `profile` and a `template`, with fixed values in `slots`. Put step-specific
   templates in WORKFLOW.md, written with the profile's key rules applied; use the profile's own template when it
   already fits. A step that's only sometimes needed (background removal when the image model already returned
   transparency) is `"optional": true`, and later steps name a fallback: `"from": ["cutout|sheet"]`. Local scripts
   go in the workflow's `scripts/`.
6. **Verify and ship**:
   ```bash
   fal workflow check <name>     # structure, templates and slots, research status, each step's price at its settings
   fal workflow plan <name>      # each step's command with its template, slots to fill, and earlier outputs wired in
   fal workflow export <name> --dest .claude/skills
   ```
   Run it once more end to end from `plan`, as the exported skill would. Export refuses steps whose profile isn't
   researched or that have no template.

**A skill for one model**: research the profile fully (A4–A5), then
`fal export <slug> --dest .claude/skills --description "<what the user makes with it, and when to use it>"`. Write
the description from the user's use case ("16:9 blog header images in our house style"), not the model's category.
Export refuses an unresearched profile.

Rules that keep workflows good: steps name profiles, never endpoints; templates, never hand-written prompts;
workflow-specific code stays in the workflow's `scripts/`; one step at a time with a check after each paid step;
subjective choices are `review` steps; build a workflow only for something the user will repeat (otherwise, C).

## Maintenance

- **Schema drift**: when a working profile starts failing validation, or every few weeks, `fal profile refresh
  <slug>` reports added and removed parameters and pinned defaults that no longer validate.
- **Stale guides**: `profile check` warns when research is over 180 days old. When a model family gets a new
  version, set `--prompting-status stale` and redo A4.
- **History**: `fal runs list` (with the template of each run) and `fal runs show last`. `fal status` and
  `fal cancel` handle in-flight jobs.

## Storage, spending and safety

- Outputs go to `./fal-outputs/` (override with `--out` or `$FAL_OUTPUT_DIR`); suggest adding it to `.gitignore`.
- Every run costs money, and there is no automatic spending limit: the confirmation in B4 and the one-step-at-a-time
  rule are the safeguards. Every run prints `price: ≈ $…` from the guide's researched table, and the manifest keeps
  it (`price_estimate`); quote that, with its basis, and the date the prices were checked. Without a table, only the
  API's unit price is known: say so, and say when it can't be known in advance (GPU time, token billing).
- The API key comes from `FAL_KEY` or bws (`BWS_ACCESS_TOKEN` plus a secret named `FAL_KEY`, or
  `FAL_BWS_SECRET_ID`). The runtime never prints it, passes it as an argument, or writes it to disk. Don't echo it,
  write it into files, or paste it into commands, and don't run `scripts/mcp_headers.py` (it prints the key).
- Uploads and outputs are stored on fal's CDN at unguessable but public URLs. Upload (`@path`) only files the user
  pointed you to, and ask before uploading anything that looks private (faces of real people, documents).

## Reference files

- `references/prompt-research.md`: researching and writing an input guide and its templates (A4).
- `references/workflows.md`: designing and building workflow skills (D), and the sprite-sheet example.
- `references/pipelines.md`: the manifest contract, REF syntax, local steps, multi-step recipes.
- `references/cli.md`: every command and flag, file formats, environment variables.
- `references/auth.md`: FAL_KEY and Bitwarden setup, connecting the MCP server, key rotation.
- `references/troubleshooting.md`: common failures by exit code.
