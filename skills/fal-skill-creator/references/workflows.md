# Workflow skills

A workflow turns one repeatable requirement into finished assets through several steps: fal models, local
scripts, and human checks. It is the layer above model profiles. A profile gives one model its best input; a
workflow puts several of them in the right order for what the user wants to make, and every model call in it goes
through a profile's research and a template.

## Contents
1. When to build one (and when not to)
2. Designing from the user's direction
3. Files and format
4. Building one, step by step
5. Running one
6. Design rules
7. Example: sprite-sheet
8. More ideas

## 1. When to build one

Build a workflow when the user will repeat a multi-step process: "every week I need an icon set", "turn each product
photo into a 5 s ad", "make a narrated explainer from a script". Don't build one for a single chain the user needs
once; run the steps with `--from` (pipelines.md) and offer the workflow afterwards if they'll need it again.

A workflow is the right layer when the value is in the **combination**: consistency across outputs (one sheet
instead of 16 separate generations), a fixed order of cheap and expensive steps, or local processing that fal
doesn't do (splitting, cropping, compositing, ffmpeg).

## 2. Designing from the user's direction

Start from the finished asset, then work backwards to the steps. Ask, in one message, only what you can't infer:

| question | why it shapes the design |
|---|---|
| What is the finished asset, and who is it for? | decides the last step's format, size and quality bar |
| What changes between runs? | these become the skill's questions and the templates' slots |
| What must stay the same? | style, palette, character, brand: these become fixed template text, presets, or a shared reference image |
| How often, and how many at once? | a one-off chain doesn't need a workflow; many assets per run favour a sheet or a batch |
| Where does a person need to decide? | subjective choices become `review` steps |

Then propose the design as a numbered list, one line per step: its type, the model and why (from SKILL.md A1), what
it consumes and produces, and its check. Say how consistency is achieved:

- **One generation for a set** (a sheet split locally) when assets must match exactly.
- **A reference image passed to every step** (character or product consistency), when the model supports one; its
  Inputs section says how to prepare it.
- **Fixed template text plus a fixed seed** for variations of one idea.

Order steps so that the cheap, easy-to-check ones come first, and name which profiles exist, which are researched,
and which need A2–A5. Get a yes before building.

## 3. Files and format

```
<name>/                        ~/.fal-skills/workflows/ (user) or ./.fal/workflows/ (project)
├── workflow.json              the steps
├── WORKFLOW.md                what the agent does at each step, and the step templates; becomes the exported SKILL.md body
└── scripts/                   local processing for `local` steps
```

**workflow.json** (`format: fal-workflow@1`):

```jsonc
{
  "format": "fal-workflow@1",
  "name": "sprite-sheet",
  "description": "…",            // the exported skill's trigger description (≤ 1024 chars); say what it makes and when to use it
  "steps": [
    {
      "id": "sheet",             // lowercase, digits, hyphens; the run label becomes <workflow>.<id>
      "type": "fal",             // fal | local | review
      "profile": "gpt-image",    // fal steps: a profile slug, never an endpoint id
      "endpoint_hint": "openai/gpt-image-2.5/sunburst/text-to-image",  // what `workflow check` suggests for `profile init`
      "template": "sheet",       // prompted steps: a ```template in WORKFLOW.md, or else in the profile's prompting.md
      "slots": {"backdrop": "fully transparent"},  // optional: fixed or default slot values; the rest are filled per run
      "preset": "asset",         // optional: a preset of that profile
      "set": {"num_images": 1},  // optional: fixed arguments for this step
      "prompted": true,          // false for steps that take no prompt (background removal, upscaling)
      "count": 1,                // results per workflow run (the plan suggests --batch when > 1)
      "optional": false,         // true: may be skipped; later steps then need a fallback in "from" ("cutout|sheet")
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
| `{in:<step>}` | the first local file of that step's current run; `{in:<step>#image}` picks by kind or field; `{in:cutout\|sheet}` falls back to `sheet` when the optional `cutout` didn't run |
| `{files:<step>}` | all of that step's local files, space-separated (`#kind` filters) |

**Step templates.** Put a prompted step's template in WORKFLOW.md when the step needs wording of its own (a sheet
layout, a consistency constraint, what the next step needs), and write it with the profile's `prompting.md` open:
use its structure, vocabulary and syntax, and say in a line above the block which key rules it applies. Point the
step at the profile's own template instead (`"template": "product-shot"`) when that already fits. Either way the
slots are what the user's request fills; everything else is fixed, researched wording. `fal workflow check` fails
when a named template doesn't exist or `slots` names a slot the template doesn't have.

## 4. Building one

1. **Design it with the user** (section 2), and create and research every profile it needs (SKILL.md A2–A5).
2. **Do it by hand first**, on a small input, with the user watching: run each step with
   `--label <workflow>.<step>`, using the profiles' templates or a draft of the step template. Note what went wrong.
3. `fal workflow init <name>` (or `--example sprite-sheet` to adapt the example). Fill in `workflow.json` from
   the steps you ran, and write each local step's script into `scripts/`. Scripts should use PEP 723 inline
   dependencies (`# /// script`) so `uv run` works with no install, print a JSON summary on stdout, and exit
   non-zero when their own sanity check fails (like `split_sprites.py --expect`).
4. Write `WORKFLOW.md` for an agent that has never seen this workflow: what to ask the user first, each prompted
   step's template with what each slot means and its default, what a bad result looks like at each check, and how to
   recover. Leave model-specific rules in each profile's `prompting.md`; keep here what this workflow adds.
5. `fal workflow check <name>`: fix every error, and every warning marked "blocks export".
6. Run it once more end to end from `fal workflow plan`, as the exported skill would.
7. `fal workflow export <name> --dest .claude/skills` (or `~/.claude/skills`, or a repo's `skills/`). Export refuses
   prompted steps without a template or with an unresearched profile, so the skill never prompts a model blind.

## 5. Running one

```bash
fal workflow plan <name>
```

The plan lists every step's exact command, with `{in:…}` and `{out}` filled in from the steps that have already run
in this pass, and names the next step. A step counts as done only when its run was made from the current run of
the step before it, so rerunning an early step (a retry, or a new request) marks everything after it as pending
again, and later steps never pick up files from an older pass.

An optional step is offered as the next step with the step after it (`next: cutout (optional; or skip it and run
split)`); running the later step marks it skipped. If the optional step runs after all, the steps that fall back past
it become pending again and use its output.

For each step: run the command (for prompted fal steps, replace each `<slot>` placeholder with a value from the
request; the plan lists them under `fill`), run the local step's `then` line (`fal ingest … --move`) to record its
files, look at the result, and run the plan again.

Inside an exported workflow skill, `fal workflow plan` needs no name, and the skill's bundled profiles take
precedence over same-named profiles on the machine, so the skill behaves the same everywhere.

## 6. Design rules

- **Name profiles, not endpoints.** Upgrading a model is then one `profile init` plus re-pointing, and prompting
  advice stays next to the model it belongs to.
- **Name templates, not prompts.** A step's fixed wording is researched once and reviewed in WORKFLOW.md; only the
  slots change per run, and each manifest records the template and slot values that produced it.
- **Keep workflow-specific code in the workflow.** The runtime stays generic; `scripts/` travels with the skill.
- **Put cheap, checkable steps first**, and check before every paid step. Background removal on a bad sheet, or a
  video from a bad keyframe, is wasted money.
- **Use the manifest as the interface.** Local steps read files from the plan's placeholders and record results
  with `fal ingest`, so lineage (`parents`) stays complete and `--from` keeps working.
- **Fail loudly in scripts.** A script that silently produces the wrong number of files turns a clear problem into
  a confusing one three steps later.
- **Don't automate taste.** Where the choice is subjective (which variant, which crop), make it a `review` step.

## 7. Examples

`fal workflow init my-icons --example sprite-sheet` copies the sprite-sheet example:

1. `sheet` (GPT Image 2.5, preset `asset`, template `sheet` in WORKFLOW.md): all assets on one transparent sheet, in
   a grid with wide gaps. One generation keeps style, palette and lighting identical across the set.
2. `cutout` (Ideogram Remove Background, optional): only when the sheet came back with a backdrop or a fringe.
3. `split` (local, `scripts/split_sprites.py`): finds each asset as a connected region of the alpha channel,
   merging parts closer than `--min-gap`, because generated "grids" are rarely exact (in live tests the model
   staggered the items so that no empty row or column separated them). Each piece is cut with its own mask, so a
   neighbor inside its bounding box never bleeds in. It trims, pads, drops specks, orders pieces row by row, and
   exits 3 when the count differs from `--expect`. Without a cutout step it keys out the plain background color
   (`--bg color`); `--grid RxC` forces fixed cells.

Create its profiles with `fal profile init openai/gpt-image-2.5/sunburst/text-to-image` and
`fal profile init fal-ai/ideogram/remove-background` (the check prints these commands; both start from bundled
guides), or point the steps at other profiles.

`fal workflow init my-ad --example keyframe-to-video`: `keyframe` (GPT Image 2.5, preset `hero` 1920×1088, the
profile's `keyframe` template) → `approve` (review: the user sees the still, motion plan and video price) → `video`
(MiniMax H3 Max image-to-video, preset `draft` 768P, the profile's `animate` template). Rerun `video` with
`--preset final --set seed=<draft seed>` for 1080P delivery.

## 8. More ideas

- **Product ad**: product photo → background replacement → image-to-video → upscale → local ffmpeg to add a logo
  end card.
- **Narrated explainer**: script → TTS per scene → keyframe per scene → image-to-video per scene → local ffmpeg
  concat with the audio.
- **Character set**: one reference character → the same character in N poses (a model with reference-image input)
  → cutout → split or crop.
- **Thumbnail A/B**: N variations with `count` → `review` step where the user picks → upscale the chosen one.
