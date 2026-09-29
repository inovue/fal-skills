# fal-skills

**Turn any of fal.ai's 1,500+ models into a reliable, reusable generator for your coding agent, then combine
several models into workflow skills.**

`fal-skill-creator` is an [Agent Skill](https://agentskills.io) for Claude Code, Codex, Cursor, and any agent that
can run shell commands. It picks the right model for a requirement, builds a validated profile from the model's API
schema, researches how that model should be prompted, then generates images, video, audio, speech, or 3D. A cost
guard runs before every request, each output is saved in a form the next step can pick up, and multi-step processes
(generate → remove background → split into assets) can be packaged as their own skills.

```
"find the best image-to-video model for a 5s vertical clip, then animate the fox from my last run"
   → requirements → fal MCP recommend_model + newest-first search → schema check → you pick
   → profile init → you confirm defaults → prompt research
   → fal run --from last … → ./fal-outputs/2026-09-29/<run>/video.mp4 + manifest.json
```

[日本語 README](README.ja.md)

## Why

Calling fal from an agent usually means guessing parameter names, burning retries on 422 errors, prompting a
video model the way you'd prompt an image model, and losing track of which file came from which request. This skill
fixes that with a small amount of structure:

| | |
|---|---|
| **Model choice from requirements** | The bundled fal MCP server's `recommend_model` plus a newest-first catalog search (crawled and sorted locally, since the API has no sort), then each finalist's schema is checked against the hard requirements (durations, resolutions, inputs). |
| **Schema-validated profiles** | Each model's OpenAPI schema is compacted (refs inlined) and used to validate every call *before* you pay. Defaults are pinned so upstream changes don't silently change your results. |
| **Researched prompt templates** | For each model, the agent reads the official docs and writes a `prompting.md` with prompt structure, `{slot}` templates, parameter advice, and limitations, all with cited sources. |
| **Cost guard** | Each run is priced from fal's unit pricing. Anything over your limit stops and asks a human. |
| **Pipelines** | Every run writes `manifest.json`. `--from last` wires the previous output into the next model's matching input (image → video → upscale). |
| **Production behavior** | Queue-based with resume (`fetch`), retries with backoff, atomic writes, uploads cached by hash, batch runs with concurrency, stable exit codes, `--json` everywhere, `--dry-run` and `--mock`. |
| **Workflow skills** | Combine fal models and local scripts into one repeatable process. `fal workflow plan` prints each step's exact command with earlier outputs filled in, tracks which steps are current, and `fal workflow export` bundles the workflow, its profiles and scripts into one skill. Ships with a sprite-sheet example (one sheet → background removal → one transparent PNG per asset). |
| **Standalone export** | `fal export <profile>` produces a self-contained `fal-<model>` skill you can share or publish. |

## Install

```bash
# any agent, via the skills CLI
npx skills add inovue/fal-skills

# Claude Code plugin marketplace
/plugin marketplace add inovue/fal-skills
/plugin install fal@fal-skills
```

Or copy `skills/fal-skill-creator` into `~/.claude/skills/` (or your agent's skills directory).

The Claude Code plugin also connects the official [fal MCP server](https://fal.ai/docs/documentation/setting-up/mcp)
for model discovery. Enter your fal API key when the plugin asks (or later in `/plugin` → fal → Configure options);
it is kept in the OS credential store. Generation always goes through the skill's runtime, so the cost guard and
manifests apply. Other agents can add the server by
hand ([auth.md](skills/fal-skill-creator/references/auth.md)); the skill works without it.

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
- "Which fal model can do a 1080p video with a start and an end frame, under $0.50?"
- "Make me 12 matching fantasy item icons as separate transparent PNGs." (sprite-sheet workflow)
- "Turn what we just did into a workflow skill the team can reuse."

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

fal workflow init my-icons --example sprite-sheet
fal workflow check my-icons            # missing profiles (with the command to create them), cost of one run
fal workflow plan my-icons             # the next step's exact command
fal workflow export my-icons --dest ~/.claude/skills
```

Exit codes: `0` ok · `2` fix the arguments · `3` cost needs approval (`--yes`) · `4` auth · `5` fal error ·
`6` still running (`fal fetch`).

## How it works

```
skills/fal-skill-creator/
├── SKILL.md                  # workflow the agent follows (search → profile → research → generate → chain)
├── scripts/fal.py            # single CLI entry (PEP 723 inline deps, runs with `uv run`)
│   └── falkit/               # catalog · schema · profiles · cost · runner · export
│   └── mcp_headers.py        # optional key-based auth helper for the fal MCP server at user scope
├── references/               # loaded on demand: cli, prompt-research, pipelines, workflows, auth, troubleshooting
└── assets/                   # templates, and workflows/sprite-sheet (example workflow)

~/.fal-skills/profiles/<slug>/     # per-model data (or ./.fal/profiles with --scope project)
  profile.json schema.json openapi.json defaults.json presets.json prompting.md
~/.fal-skills/workflows/<name>/    # multi-step processes (or ./.fal/workflows)
  workflow.json WORKFLOW.md scripts/

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

Contributions are welcome, especially cost-unit mappings for new pricing units, media-kind heuristics for unusual
input names, and fixes where a model's schema breaks compaction (please attach the endpoint id).

## License

MIT
