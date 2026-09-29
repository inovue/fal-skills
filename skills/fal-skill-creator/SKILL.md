---
name: fal-skill-creator
description: Turn any fal.ai model into a reliable, reusable generator. Search 1,500+ fal models newest-first, pull an endpoint's OpenAPI schema into a profile with pinned defaults, research the model's official prompting guidance into templates, then generate images, video, audio, speech or 3D with a cost guard, and chain outputs between models. Can export a profile as a standalone skill. Use this whenever the user mentions fal, fal.ai or fal.com, names a model hosted on fal (FLUX, Kling, Veo, Seedance, Hunyuan, Recraft, Ideogram, ElevenLabs on fal, etc.), wants to generate or edit media through an API, wants to find the latest fal model for a task, asks to make a skill for a fal model, or wants to pipe one generation into another (image → video → upscale), even if they don't say "skill" or "profile". Not for local Stable Diffusion/ComfyUI or other providers' native APIs.
license: MIT
compatibility: Python 3.10+ via uv (recommended) or pip. Network access to fal.ai. A fal API key in FAL_KEY or in Bitwarden Secrets Manager (bws). Works in any agent that can run shell commands.
metadata:
  version: 1.0.0
  homepage: https://github.com/OWNER/fal-skills
---

# fal skill creator

This skill turns a fal model into something you can call reliably, then uses it. There are two kinds of pieces:

- **Profile** (data). This is one folder per model: its schema, pinned defaults, presets, a price snapshot, and
  `prompting.md` (researched prompt templates). Profiles live in `~/.fal-skills/profiles/`, or in `./.fal/profiles/`
  when created with `--scope project`.
- **Runtime** (code). This is `scripts/fal.py`, one tested CLI that searches models, validates inputs, uploads files,
  checks cost, submits to fal's queue, waits, downloads, and writes a manifest.

Keeping models as data and the runtime as shared code is deliberate. The same tested code path then serves every
model, and adding a model never adds new code that could break. A profile can still be exported as a standalone
skill (Workflow D) when the user wants one skill per model.

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

- The user wants media and a suitable profile exists (`fal profile list`) → **B. Generate**.
- The user names a model or a task but no profile fits → **A. Create a profile**, then **B**.
- The user wants "a skill for model X" → **A**, then **D. Export**.
- The user wants several steps (image → video, video → upscale, TTS → lipsync) → **C. Pipelines**.
- The user names an exact endpoint id for a one-off job and hasn't asked for reuse → skip profile creation and
  research. Run `fal schema <id>`, then `fal run -e <id> …`. This works with no profile: the schema is fetched and
  cached, and validation and the cost guard still apply. Afterwards, offer to turn the model into a profile if it
  looks like something the user will use again. Building profiles and doing research for a one-off job roughly
  doubles the time for no benefit.

## A. Create a profile (search → schema → defaults → research)

### A1. Find the model, newest first

```bash
fal models categories                      # when the task type is unclear
fal models search <terms> -c <category> -n 10 --prices   # --prices adds unit prices in one batched call
fal models show <endpoint_id>              # description, license, price
```

Search terms are combined with AND and matched against the id, name, tags and description. Results are strictly
newest first because the catalog is crawled and sorted locally (fal's API has no sort parameter). Use `--since 90`
when the user wants recent models.

Show the user a numbered shortlist of 5–10 models with name, endpoint id, date, and price when available. Ask them
to reply with a number. A plain numbered message works better than a multiple-choice widget here, because those
widgets usually allow only a few options. Skip the question when the user already gave an exact endpoint id. If you
are running unattended, pick the newest active model that fits the task and say which one you picked and why.

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
   prompting guide). Prefer Exa search if it is available, otherwise web search and fetch.
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
profile's `max_usd`, then `$FAL_MAX_COST`, then $1.00. A run is also blocked when its cost can't be estimated and
the unit price is above $0.05. The guard exists so that a video batch never runs up a bill silently. When it trips,
tell the user the estimate and the reason, and add `--yes` only after they approve. Never add `--yes` pre-emptively.

## C. Pipelines (chaining models)

Each run writes `<out>/<date>/<run_id>/` containing the media files, `result.json` and `manifest.json`, and appends
a line to `<out>/index.jsonl`. The manifest is the contract between steps and between skills. Any fal-* skill, or
any other tool, can consume it.

```bash
fal run -p flux-dev --prompt "…" --label keyframe
fal run -p kling-i2v --from last --prompt "slow dolly-in …"         # auto-fills image_url from last run's image
fal run -p upscaler --set video_url=from:last#video                  # explicit: first video output of last run
fal run -p lipsync --set video_url=from:last~1 --set audio_url=from:<run_id>#audio
```

With `--from REF`, empty media inputs are filled by matching media kind (image, video, audio), required fields
first. Every link it makes is printed as `wired: …`, so check those lines. Values you pass explicitly with `--set`
always win. A REF is `last`, `last~N`, a run id, a run directory, or a manifest path. `#sel` picks one output: an
index, a kind, a field, or `*` for all. A hosted URL is reused when it still resolves; otherwise the saved local
copy is re-uploaded.

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

## Maintenance

- **Schema drift.** When a run fails validation on a profile that used to work, or every few weeks:
  `fal profile refresh <slug>` reports added and removed parameters and any pinned defaults that no longer validate.
- **Stale prompting.** When a model family gets a new version, set `--prompting-status stale` and redo A4.
- **History.** `fal runs list` and `fal runs show last`. `fal status` and `fal cancel` handle in-flight jobs.

## Storage and safety conventions

- Outputs go to `./fal-outputs/` by default (override with `--out` or `$FAL_OUTPUT_DIR`). Media can be large;
  suggest adding `fal-outputs/` to `.gitignore` when working inside a git repo.
- The API key comes from `FAL_KEY`, or from bws (`BWS_ACCESS_TOKEN` plus a secret named `FAL_KEY`, or set
  `FAL_BWS_SECRET_ID`). The runtime never prints the key, never passes it as a command-line argument, and never
  writes it to disk. Don't echo it, write it into files, or paste it into commands yourself. `fal doctor` confirms
  where it was found.
- Uploaded inputs and generated outputs are stored on fal's CDN at unguessable but public URLs. Only upload
  (`@path`) files the user pointed you to, and check with the user before uploading anything that looks private
  (faces of real people, documents). Uploads happen only after the cost guard passes.
- Price units differ between models (per image, per megapixel, per second, per "unit"). When comparing models, say
  what the unit is. When a price is quoted per opaque "units", the cost guard treats the estimate as uncertain.

## Reference files

- `references/cli.md`: every command and flag, the profile file formats, and environment variables.
- `references/prompt-research.md`: how to research and write `prompting.md` (step A4).
- `references/pipelines.md`: the manifest contract, REF syntax, multi-step recipes, and use from other tools.
- `references/auth.md`: FAL_KEY and Bitwarden setup, and key rotation.
- `references/troubleshooting.md`: common failures by exit code.
