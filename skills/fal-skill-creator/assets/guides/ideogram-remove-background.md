<!--
status: researched
researched_at: 2026-09-30
model: fal-ai/ideogram/remove-background
Bundled with fal-skill-creator. Re-check the Sources and the pricing block when Ideogram or fal update the model.
-->
# Input guide: Ideogram Remove Background

`fal-ai/ideogram/remove-background` · image-to-image · returns a transparent PNG of the subject [S1]. No prompt:
the input image is the whole input, so its preparation is what decides the result.

## Key rules
- One clear subject with a visible outline gives the cleanest cut; crop away other objects first [S1] (heuristic).
- Check the alpha on hair, glass, glow and shadows before using the result; these edges fail first (heuristic).
- If an image model can make the asset transparent itself (GPT Image 2.5 `background=transparent`), that is one
  step fewer; use this model for photos and for images that came out with a backdrop [S2].

## Inputs
- `image_url`: jpg, png, webp, gif, avif, heic [S1]. A plain, contrasting background helps (heuristic).
- A sheet of several assets works; split it afterwards (the sprite-sheet workflow's `split_sprites.py`).
- From an earlier run: `--from <run>` (first image) or `--from <run>#<index>`.

## Parameters that matter

| parameter | when to change | recommended |
|---|---|---|
| sync_mode | never | leave unset (the runtime asks for URLs) |

## Pricing

```pricing
per: request
*: 0.01
checked: 2026-09-30 https://fal.ai/models/fal-ai/ideogram/remove-background
```

## Limitations
- Semi-transparent material (glass, smoke) and soft shadows may be cut or kept unpredictably (heuristic).

## Sources
- [S1] Ideogram Remove Background — https://fal.ai/models/fal-ai/ideogram/remove-background — fal — accessed 2026-09-30
- [S2] Image prompting (GPT Image 2.5): transparent backgrounds — https://developers.openai.com/api/docs/guides/image-prompting — OpenAI (official) — accessed 2026-09-30
