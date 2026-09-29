# Workflow skills

A workflow turns one repeatable requirement into finished assets through several steps: fal models, local
scripts, and human checks. It is the layer above model profiles. A profile makes one model reliable; a workflow
makes a whole process reliable and shareable.

## Contents
1. When to build one (and when not to)
2. Files and format
3. Building one, step by step
4. Running one
5. Design rules
6. Example: sprite-sheet
7. More ideas

## 1. When to build one

Build a workflow when the user will repeat a multi-step process: "every week I need an icon set", "turn each product
photo into a 5 s ad", "make a narrated explainer from a script". Don't build one for a single chain the user needs
once; run the steps with `--from` (pipelines.md) and offer the workflow afterwards if they'll need it again.

A workflow is the right layer when the value is in the **combination**: consistency across outputs (one sheet
instead of 16 separate generations), a fixed order of cheap and expensive steps, or local processing that fal
doesn't do (splitting, cropping, compositing, ffmpeg).

## 2. Files and format

```
<name>/                        ~/.fal-skills/workflows/ (user) or ./.fal/workflows/ (project)
├── workflow.json              the steps
├── WORKFLOW.md                what the agent does at each step; becomes the exported SKILL.md body
└── scripts/                   local processing for `local` steps
```

**workflow.json** (`format: fal-workflow@1`):

```jsonc
{
  "format": "fal-workflow@1",
  "name": "sprite-sheet",
  "description": "…",            // the exported skill's trigger description (≤ 1024 chars); say what it makes and when to use it
  "max_usd": 0.5,                // warn when one full run is estimated above this
  "steps": [
    {
      "id": "sheet",             // lowercase, digits, hyphens; the run label becomes <workflow>.<id>
      "type": "fal",             // fal | local | review
      "profile": "nano-banana",  // fal steps: a profile slug, never an endpoint id
      "endpoint_hint": "fal-ai/nano-banana",  // what `workflow check` suggests for `profile init` when it's missing
      "preset": "square",        // optional: a preset of that profile
      "set": {"num_images": 1},  // optional: fixed arguments for this step
      "prompted": true,          // false for steps that take no prompt (background removal, upscaling)
      "count": 1,                // results per workflow run, for the cost estimate
      "from": [],                // earlier steps whose outputs feed this one (auto-wired by media kind)
      "purpose": "…",            // one line, shown in the plan and the exported skill
      "check": "…",              // what to verify before moving on
      "checkpoint": true         // default true for fal and review steps, false for local steps
    },
    {
      "id": "split",
      "type": "local",
      "command": "uv run {skill}/scripts/split_sprites.py {in:cutout#image} --out {out} --pad 8",
      "from": ["cutout"]
    }
  ]
}
```

Placeholders in a local step's `command`:

| placeholder | becomes |
|---|---|
| `{skill}` | the workflow directory (or the exported skill's directory) |
| `{out}` | a scratch directory for this step's output: `<output root>/_work/<workflow>/<step>` |
| `{in:<step>}` | the first local file of that step's current run; `{in:<step>#image}` picks by kind or field |
| `{files:<step>}` | all of that step's local files, space-separated (`#kind` filters) |

## 3. Building one

1. **Do it by hand first**, on a small input, with the user watching: choose each model (SKILL.md A1), create
   and research its profile (A2–A4), and run each step with `--label <workflow>.<step>`. Note what went wrong.
2. `fal workflow init <name>` (or `--example sprite-sheet` to adapt the example). Fill in `workflow.json` from
   the steps you ran, and write each local step's script into `scripts/`. Scripts should use PEP 723 inline
   dependencies (`# /// script`) so `uv run` works with no install, print a JSON summary on stdout, and exit
   non-zero when their own sanity check fails (like `split_sprites.py --expect`).
3. Write `WORKFLOW.md` for an agent that has never seen this workflow: what to ask the user first, the prompt
   template for each prompted step, what a bad result looks like at each check, and how to recover. Leave
   model-specific prompting to each profile's `prompting.md`.
4. `fal workflow check <name>`: fix every error, and read the cost estimate for one run.
5. Run it once more end to end from `fal workflow plan`, as the exported skill would.
6. `fal workflow export <name> --dest .claude/skills` (or `~/.claude/skills`, or a repo's `skills/`).

## 4. Running one

```bash
fal workflow plan <name>
```

The plan lists every step's exact command, with `{in:…}` and `{out}` filled in from the steps that have already run
in this pass, and names the next step. A step counts as done only when its run was made from the current run of
the step before it, so rerunning an early step (a retry, or a new request) marks everything after it as pending
again, and later steps never pick up files from an older pass.

For each step: run the command (for prompted fal steps, write the prompt from WORKFLOW.md first), run the local
step's `then` line (`fal ingest … --move`) to record its files, look at the result, and run the plan again.

Inside an exported workflow skill, `fal workflow plan` needs no name, and the skill's bundled profiles take
precedence over same-named profiles on the machine, so the skill behaves the same everywhere.

## 5. Design rules

- **Name profiles, not endpoints.** Upgrading a model is then one `profile init` plus re-pointing, and prompting
  advice stays next to the model it belongs to.
- **Keep workflow-specific code in the workflow.** The runtime stays generic; `scripts/` travels with the skill.
- **Put cheap, checkable steps first**, and check before every paid step. Background removal on a bad sheet, or a
  video from a bad keyframe, is wasted money.
- **Use the manifest as the interface.** Local steps read files from the plan's placeholders and record results
  with `fal ingest`, so lineage (`parents`) stays complete and `--from` keeps working.
- **Fail loudly in scripts.** A script that silently produces the wrong number of files turns a clear problem into
  a confusing one three steps later.
- **Don't automate taste.** Where the choice is subjective (which variant, which crop), make it a `review` step.

## 6. Example: sprite-sheet

`fal workflow init my-icons --example sprite-sheet` copies the bundled example:

1. `sheet` (nano-banana): all assets on one sheet, in a grid with wide gaps, on a plain background. One
   generation keeps style, palette and lighting identical across the set.
2. `cutout` (birefnet v2): background removal, auto-wired from `sheet`.
3. `split` (local, `scripts/split_sprites.py`): finds each asset as a connected region of the alpha channel,
   merging parts closer than `--min-gap`, because generated "grids" are rarely exact (in live tests the model
   staggered the items so that no empty row or column separated them). Each piece is cut with its own mask, so a
   neighbor inside its bounding box never bleeds in. It trims, pads, drops specks, orders pieces row by row, and
   exits 3 when the count differs from `--expect`. Without a cutout step it keys out the plain background color
   (`--bg color`); `--grid RxC` forces fixed cells.

Create its profiles with `fal profile init fal-ai/nano-banana` and `fal profile init fal-ai/birefnet/v2` (the check
prints these commands), or point the steps at other profiles.

## 7. More ideas

- **Product ad**: product photo → background replacement → image-to-video → upscale → local ffmpeg to add a logo
  end card.
- **Narrated explainer**: script → TTS per scene → keyframe per scene → image-to-video per scene → local ffmpeg
  concat with the audio.
- **Character set**: one reference character → the same character in N poses (a model with reference-image input)
  → cutout → split or crop.
- **Thumbnail A/B**: N variations with `count` → `review` step where the user picks → upscale the chosen one.
