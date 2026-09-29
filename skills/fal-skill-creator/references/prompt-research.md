# Researching how to prompt a fal model (workflow step A4)

The goal is a `prompting.md` inside the profile. It should let any agent write a strong prompt for this model on
the first try without redoing the research. It is built from official sources, cites them, and is short enough to
read before every generation (aim for under 150 lines).

## Contents
1. Where to look (source priority)
2. Search procedure
3. What to extract
4. Writing prompting.md
5. Quality bar and checklist

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
- Otherwise use **web search, then fetch** each promising page and read it in full. Search snippets alone are not
  enough.
- Always fetch the fal model page (`playground_url`). It often includes example prompts that are known to work
  on fal's deployment.

When a subagent tool is available, delegate this step. Give it the endpoint id, both fal URLs, and this file's
sections 3–5, and ask for the finished `prompting.md` content back. The research reads 5–15 pages that don't need
to stay in the main context.

Stop when the key sections below are covered by tier-1 or tier-2 sources, or after about 10 pages with nothing
new. Don't fill gaps with guesses dressed as facts. Write `unknown — not documented` instead.

## 3. What to extract

Capture only what changes how you would write a prompt or set a parameter:

- **Structure**: the order of components the model follows best, plus whether it wants prose or comma-separated
  tags, the ideal length, token or character limits, and language support (does a Japanese prompt work, or
  should you translate?).
- **Special syntax**: quoted text for typography, reference tokens (`@image1`, `<ref>`), weights, speaker tags,
  timestamps and shot lists (video), SSML or emotion tags (TTS), and style or LoRA trigger words.
- **Camera and motion vocabulary** (video): which terms the docs say work (dolly, pan, orbit, handheld), how to
  describe motion intensity, and whether multi-shot prompts are supported.
- **What not to do**: whether negative prompts are supported or ignored, instructions the model misreads (e.g.
  "no X" producing X), and known weak spots (hands, text, counting, fast motion).
- **Parameters**: which ones matter for quality and cost, recommended values per use case, and interactions
  (e.g. guidance scale ranges, steps vs acceleration, duration vs cost).
- **Examples**: 2–4 prompts copied verbatim from official sources, each with its source.

## 4. Writing prompting.md

Fill in the stub that `profile init` created (its structure comes from `assets/prompting.template.md`). Guidelines:

- **Key rules first.** Write 3–6 bullets an agent can apply without reading further, each with a citation like
  `[S1]`.
- **Templates are the core deliverable.** Write one `general` template plus one per main use case: for example
  `product-shot`, `portrait`, and `typography` for image models; `establishing-shot`, `character-action`, and
  `product-orbit` for video; `narration` and `dialogue` for TTS. Use `{snake_case}` slots, and after each template
  add one line on when to use it. The agent fills the slots from the user's request, so the slot names should say
  what goes in them.
- **Suggest presets** for recurring parameter bundles, and mention them in the parameters table. The agent (or the
  user during A3) can create them with `fal profile preset`.
- **Date it.** Update the HTML comment header: set `status: researched` and `researched_at: YYYY-MM-DD`. Models
  change, and the date tells a future agent how far to trust the file.
- **Keep it short.** This file is read before every generation. Link to the sources for depth instead of copying
  whole guides.

Then:

```bash
fal profile meta <slug> --prompting-status researched
```

If the user wants to, suggest presets from the research and create them after they agree.

## 5. Quality bar and checklist

- [ ] Every key rule and every parameter recommendation is backed by a cited source or marked `heuristic`.
- [ ] At least one tier-1 source (fal page or model maker) is cited.
- [ ] Templates cover the use cases the user mentioned while setting up the profile.
- [ ] Examples are verbatim and attributed, not invented.
- [ ] Limitations list what the model can't do, so the agent can warn the user instead of burning retries.
- [ ] `researched_at` is set and `prompting_status` is `researched`.

Optional validation: generate one image or clip with the `general` template on a simple subject and check that
the result follows the prompt. If it doesn't, revise the templates before telling the user the profile is ready.
