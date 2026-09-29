# fal-skills

**Turn any of fal.ai's 1,500+ models into a reliable, reusable generator for your coding agent.**

`fal-skill-creator` is an [Agent Skill](https://agentskills.io) for Claude Code, Codex, Cursor, and any agent that
can run shell commands. It finds the newest model for a task, builds a validated profile from the model's API schema,
researches how that model should be prompted, then generates images, video, audio, speech, or 3D. A cost guard runs
before every request, and each output is saved in a form the next step can pick up.

```
"find the newest image-to-video model and animate the fox from my last run, 5s, vertical"
   → models search (newest first) → profile init → you confirm defaults → prompt research
   → fal run --from last … → ./fal-outputs/2026-09-29/<run>/video.mp4 + manifest.json
```

[日本語 README](README.ja.md)

## Why

Calling fal from an agent usually means guessing parameter names, burning retries on 422 errors, prompting a
video model the way you'd prompt an image model, and losing track of which file came from which request. This skill
fixes that with a small amount of structure:

| | |
|---|---|
| **Newest-first model search** | The whole catalog is crawled and sorted locally (the API has no sort), cached for 6 hours, and filterable by category, age, and keywords. |
| **Schema-validated profiles** | Each model's OpenAPI schema is compacted (refs inlined) and used to validate every call *before* you pay. Defaults are pinned so upstream changes don't silently change your results. |
| **Researched prompt templates** | For each model, the agent reads the official docs and writes a `prompting.md` with prompt structure, `{slot}` templates, parameter advice, and limitations, all with cited sources. |
| **Cost guard** | Each run is priced from fal's unit pricing. Anything over your limit stops and asks a human. |
| **Pipelines** | Every run writes `manifest.json`. `--from last` wires the previous output into the next model's matching input (image → video → upscale). |
| **Production behavior** | Queue-based with resume (`fetch`), retries with backoff, atomic writes, uploads cached by hash, batch runs with concurrency, stable exit codes, `--json` everywhere, `--dry-run` and `--mock`. |
| **Standalone export** | `fal export <profile>` produces a self-contained `fal-<model>` skill you can share or publish. |

## Install

```bash
# any agent, via the skills CLI
npx skills add OWNER/fal-skills

# Claude Code plugin marketplace
/plugin marketplace add OWNER/fal-skills
/plugin install fal@fal-skills
```

Or copy `skills/fal-skill-creator` into `~/.claude/skills/` (or your agent's skills directory).

**Requirements:** Python 3.10+ and [uv](https://docs.astral.sh/uv/). With uv, dependencies install automatically on
first run. pip also works.

## Set up your key

```bash
export FAL_KEY="…"                     # from https://fal.ai/dashboard/keys
# or keep it in Bitwarden Secrets Manager:
export BWS_ACCESS_TOKEN="…"            # the runtime reads the secret named FAL_KEY via `bws`
```

Then ask your agent to "run fal doctor", or run it yourself:
`uv run skills/fal-skill-creator/scripts/fal.py doctor`. See [auth.md](skills/fal-skill-creator/references/auth.md).

## Use it

Talk to your agent:

- "What are the newest text-to-video models on fal?"
- "Set up FLUX dev as a profile. I mostly need 16:9 blog headers."
- "Generate 4 product shots of a matte black water bottle with the recraft profile."
- "Make a skill for Kling 2.1 image-to-video so my team can use it."
- "Take the last image and turn it into a 5s vertical clip, then upscale it."

Or use the CLI directly (`fal` = `uv run skills/fal-skill-creator/scripts/fal.py`):

```bash
fal models search kling -c image-to-video -n 5
fal profile init fal-ai/flux/dev
fal profile set flux-dev image_size=landscape_16_9 output_format=png
fal run -p flux-dev --prompt "a red fox in fresh snow, watercolor" --dry-run
fal run -p flux-dev --prompt "a red fox in fresh snow, watercolor" --label fox
fal run -e fal-ai/kling-video/v2.1/standard/image-to-video --from last --prompt "the fox turns its head"
fal runs list
fal export flux-dev --dest ~/.claude/skills
```

Exit codes: `0` ok · `2` fix the arguments · `3` cost needs approval (`--yes`) · `4` auth · `5` fal error ·
`6` still running (`fal fetch`).

## How it works

```
skills/fal-skill-creator/
├── SKILL.md                  # workflow the agent follows (search → profile → research → generate → chain)
├── scripts/fal.py            # single CLI entry (PEP 723 inline deps, runs with `uv run`)
│   └── falkit/               # catalog · schema · profiles · cost · runner · export
├── references/               # loaded on demand: cli, prompt-research, pipelines, auth, troubleshooting
└── assets/                   # prompting.md template, exported-skill template

~/.fal-skills/profiles/<slug>/     # per-model data (or ./.fal/profiles with --scope project)
  profile.json schema.json openapi.json defaults.json presets.json prompting.md

./fal-outputs/                     # runs: media + request.json + result.json + manifest.json, and index.jsonl
```

Models are **data** (profiles), and the **code** is one tested runtime. Adding the 50th model adds no new code and
no new failure modes. Profiles become separate skills only when you export them.

## Development

```bash
make test        # offline tests: no key, no network, no cost
make test-live   # plus one real flux/schnell call (~$0.003)
make lint validate
```

Contributions are welcome, especially cost-unit mappings for new pricing units, media-kind heuristics for unusual
input names, and fixes where a model's schema breaks compaction (please attach the endpoint id).

## License

MIT
