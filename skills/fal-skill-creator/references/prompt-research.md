# Researching a model's input guide (step A4)

The goal is a `prompting.md` inside the profile that lets any agent give this model its best input on the first
try, without redoing the research: how to write the prompt, what reference media to pass and how, which parameters
to set, and what the model can't do. Its templates are what `fal run --template` renders, so they are the part that
reaches the model on every run. It is built from official sources, cites them, and stays short enough to read
before every generation (aim for under 150 lines).

## Contents
1. Where to look (source priority)
2. Search procedure, quick and full
3. What to extract
4. Writing prompting.md
5. Templates: syntax and design
6. Check, mark, validate

## 1. Where to look

Rank sources by authority. Only cite a lower tier when the higher tiers are silent.

| tier | source | how to find it |
|---|---|---|
| 1 | The fal model page and its API tab | `profile.json` → `playground_url`, `documentation_url` |
| 1 | The model maker's official prompting guide (e.g. Black Forest Labs docs, Google's Veo/Imagen guides, Kling's user guide, Runway docs, ElevenLabs docs, ByteDance Seed pages, Alibaba Wan/Qwen repos) | search `"<model family> prompt guide" site:<vendor domain>` |
| 1 | The official model card or README on GitHub or Hugging Face | search `<model name> github` / `huggingface` |
| 2 | fal's blog and learn pages about this model or family | the fal MCP server's `search_docs`, or search `site:fal.ai <model name> prompt` / `blog.fal.ai` |
| 2 | The description and examples in the schema (`schema.json` → `examples`, parameter descriptions) | already on disk |
| 3 | Well-regarded community write-ups (high-signal technical posts only, not SEO listicles) | only to fill gaps; mark claims as `heuristic` |

## 2. Search procedure

Use the best search tool you have:

- **Exa**, if its MCP tools or a skill are available. It is good at finding official docs pages. Search for
  `"<model display name>" prompting guide`, `"<endpoint family>" prompt best practices`, and
  `<vendor> <model> prompt structure`.
- Otherwise use **web search, then fetch** each promising page and read it in full. Snippets are not enough.
- Always fetch the fal model page (`playground_url`). It often shows example prompts known to work on fal's
  deployment, and the input constraints of that deployment.

**Quick pass** (a one-off request): the fal model page plus the maker's prompting guide. Enough to write key rules,
the Inputs section, a `general` template and one for the request's use case, and to pass `profile check`.

**Full pass** (a profile that will be reused, exported, or used in a workflow): 5–15 pages until every section below
is covered by tier-1 or tier-2 sources, or about 10 pages turn up nothing new. When a subagent tool is available,
delegate it: give the endpoint id, both fal URLs, the use cases the user mentioned, and sections 3–5 of this file,
and ask for the finished `prompting.md` back.

Either way: don't fill gaps with guesses dressed as facts. Write `unknown — not documented` instead.

## 3. What to extract

Capture only what changes how you would write a prompt, prepare an input, or set a parameter:

- **Structure**: the order of components the model follows best; prose or comma-separated tags; ideal length and
  hard limits; language support (does a Japanese prompt work, or should you translate?).
- **Special syntax**: quoted text for typography, reference tokens (`@image1`, `<ref>`), weights, speaker tags,
  timestamps and shot lists (video), SSML or emotion tags (TTS), style or LoRA trigger words.
- **Inputs**: for every media input in the schema (image, reference images, start and end frames, masks, audio,
  video): accepted formats, the resolution and aspect ratio that work best, size, length and count limits, what
  makes a good reference (one clear subject, clean background, matching aspect ratio, a neutral pose), and how the
  prompt should refer to each input. For text-only models: what to strip (markdown, emoji), and how to mark pauses
  or emphasis.
- **Camera and motion vocabulary** (video): which terms the docs say work (dolly, pan, orbit, handheld), how to
  describe motion intensity, whether multi-shot prompts are supported.
- **What not to do**: whether negative prompts are supported or ignored, instructions the model misreads ("no X"
  producing X), known weak spots (hands, text, counting, fast motion).
- **Parameters**: which ones matter for quality and which for cost, recommended values per use case, and
  interactions (guidance scale ranges, steps versus acceleration, duration versus price).
- **Prompt rewriting**: switches through which the model rewrites or extends your prompt (`prompt_expansion_mode`,
  `enhance_prompt`, `prompt_optimizer`…). They can undo a researched prompt. Say how to set them for templated
  prompts (usually off) and where the rewritten prompt shows up (e.g. `expanded_prompt` in the result). The check
  fails while such a parameter isn't mentioned.
- **Pricing**: the price table from fal's model page, by the arguments that change it (resolution, quality, size,
  duration), with any promotion and its end date. The API's unit price is often the cheapest tier or an opaque
  "$1 per unit"; the check fails without a table when the unit is opaque.
- **Measured facts**: what the docs leave open and a cheap run answers (the pixel size each size preset really
  produces, whether a size is rounded). Measure at the lowest quality and write the result with its date.
- **Examples**: 2–4 prompts copied verbatim from official sources, each with its source.

## 4. Writing prompting.md

Fill in the stub that `profile init` created (from `assets/prompting.template.md`):

- **Key rules first**: 3–6 bullets an agent can apply without reading further, each citing a source like `[S1]`.
- **Inputs**: required whenever the model takes media (the check enforces this).
- **Templates**: see section 5. They are the core deliverable.
- **Parameters that matter**: a table; suggest presets for recurring bundles (the agent or the user creates them
  with `fal profile preset`).
- **Pricing**: a ```` ```pricing ```` block (format below), with a `checked:` date and the model page URL.
- **Limitations**: what to warn the user about instead of burning retries.
- **Sources**: `[S1] Title — URL — publisher (official/fal/community) — accessed YYYY-MM-DD`. Include at least one
  tier-1 source.
- **Short**: link to sources for depth instead of copying whole guides. Delete the stub's HTML comments and its
  "Not researched yet" notice.

## 5. Templates: syntax and design

A template is a fenced block whose info string is `template <name>`:

````markdown
```template product-shot
{product} on {surface}, three-quarter view. Studio softbox lighting from the left, soft shadow. {background}
background. Sharp focus on the label, shallow depth of field. {style}.
```
Product photos for listings and ads.
````

- `fal run -p <slug> -t product-shot --slot product="a matte black bottle" --slot surface=slate …` renders it into the
  model's prompt field. Required slots need a non-empty value. `{{` and `}}` are literal braces.
- **Ship a `quick` template** with 1–3 slots for light requests, with the research in its fixed wording. It's what
  the agent reaches for first when a request is one line.
- **Encode the research, not just placeholders.** The fixed words carry the model's key rules: its preferred order,
  its camera or lighting vocabulary, its way of quoting text or naming references. The slots carry only what
  changes per request. A template that is just `{subject}, {style}` wastes the research.
- **Name slots for what goes in them** (`{product}`, `{camera_move}`, `{on_screen_text}`), in `snake_case`.
- **One template per main use case**, plus `general`. For image models, e.g. `product-shot`, `portrait`,
  `typography`; for video, `establishing-shot`, `character-action`, `product-orbit`; for TTS, `narration`,
  `dialogue`. Add the use cases the user mentioned during A1–A3.
- After each block, one line on when to use it.
- **Optional parts** go in `[[ … ]]`: `…lighting.[[ Camera: {camera_move}.]] No text.` keeps the part only when all
  its slots are given, and drops it whole otherwise, so no dangling "Camera:". Slots outside groups are required.
- **A parameter's value in the prompt** is written `{=duration}`, `{=aspect_ratio}`: the request's own value goes
  there, so the prompt and the request can't disagree. A plain `{name}` that is also a parameter name is an error
  (`{background}` in a GPT Image template would be ambiguous with the `background` parameter; call the slot
  `{backdrop}`).
- **The check renders every template twice**, with only the required slots and with all of them, and rejects
  broken text (a label with nothing after it, an empty quote, stray punctuation). Put every labeled, skippable part
  in `[[ … ]]`.
- **Verbatim text** (on-screen copy, dialogue) goes in quotes in the template (`"{headline}"`), so it may stay in
  the user's language; everything else should be written in the template's language.
- Workflow templates follow the same syntax in WORKFLOW.md (see workflows.md).

### Pricing block

````markdown
```pricing
per: second                 # what one price buys: image | second | request
count: duration             # arguments multiplied into the quantity; missing ones use the schema default
by: resolution              # arguments whose values pick the row; `*` matches anything, `a|b` either
480P: 0.05
768P: 0.08
1080P: 0.16
checked: 2026-09-30 https://fal.ai/models/minimax/h3-max/image-to-video
```
````

Text billed by length (speech, some LLM-backed models): `count: chars(text)/1000` with `per: 1000 characters`.

A second dimension goes in columns, as on fal's size × quality tables:
`columns: quality = low, medium, high` then rows like `square_hd|1024x1024: 0.00588 0.01317 0.05268`. Custom
`{width, height}` sizes match rows written `1920x1088`. Every run prints the estimate and records it in the manifest;
it never blocks a run. The check warns when `checked` is older than 30 days (promotions end, prices change).

`fal profile templates <slug>` lists the templates and slots as the runtime parses them.

## 6. Check, mark, validate

```bash
fal profile check <slug>                                  # errors must be fixed; warnings are advice
fal profile meta <slug> --prompting-status researched     # refused while the check has errors
```

The check requires: the stub notice removed; at least 3 key rules, citing sources; at least one template for models
that take text, whose fixed wording carries the research (for image and video models, a template that is almost only
slots fails); an Inputs section for models that take media; any prompt-rewriting parameter addressed; a pricing
table when the API's unit is opaque; fal's model page among the sources; and, online (the default), every cited
source reachable. It warns about slot-less templates, slots named after parameters, inputs the Inputs section
doesn't mention, an empty parameters table, a single source, stale prices (30 days) or research (180 days), more
than 200 lines, and a guide not yet validated. Marking it researched also stamps `status` and `researched_at` in the
file's header.

Then validate (A5): render the `general` template (or the one for the user's use case) with a simple subject,
`--dry-run` to read the final prompt and price, run it once, and check that the result follows the prompt. If it doesn't,
fix the template or the rules before telling the user the profile is ready. Record the run:
`fal profile meta <slug> --validated-with <run_id>`.
