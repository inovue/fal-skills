<!--
status: researched
researched_at: 2026-09-30
model: openai/gpt-image-2.5/sunburst/edit (also flare/edit: same prompting, same prices)
Bundled with fal-skill-creator. Re-check the Sources and the pricing block when OpenAI or fal update the model.
-->
# Input guide: GPT Image 2.5 Edit

`openai/gpt-image-2.5/sunburst/edit` · image-to-image · edits scoped to the instruction, with subject and composition
preserved across rounds [S3]. Flare/edit: faster, same price [S1][S4].

## Key rules
- Say what changes, then what stays: "Change only X. Keep Y, Z unchanged." List identity, geometry, layout, lighting
  and labels to preserve, and repeat that list on every round [S1][S2].
- Give every input image a number and a job: "Image 1: the product photo (subject). Image 2: style reference."
  Then say how they combine ("apply Image 2's style to Image 1") [S1][S2].
- One change per run: an instruction with two changes costs more retries than two passes [S4].
- Exact text: in quotes, with position and typography; add "no extra text" [S1].
- When a region must stay pixel-identical, composite the approved edit over the original instead of trusting the
  prompt; use `mask_url` to limit where changes may happen [S1][S4].

## Prompt structure
`Image 1: … Image 2: …` (roles) → the one change → the preserve list → exclusions. Write in English; keep text that
must appear verbatim (e.g. Japanese copy) in its original script, in quotes.

## Inputs
- `image_urls` (required, 1–16): numbered in the order given, as Image 1, Image 2… [S3][S4]. Put the image being
  edited first. Formats: jpg, png, webp, gif, avif, heic [S3]. Crop references to the relevant part; a cluttered
  reference leaks unwanted elements.
- `mask_url` (optional): same size as Image 1; transparent where the edit is allowed [S4].
- `image_size`: `auto` (default) follows the input; set it only to change the canvas [S3].
- Input images are billed as image tokens on top of the output price [S3].
- From an earlier run: `--from <run>` fills `image_urls` with that run's first image; `--from <run>#*` passes all of
  them; a second `--from` adds nothing (one run fills one input), so use `--set image_urls='["…","…"]'` or
  `from:` values to combine several runs.

## Templates

```template quick
Image 1: the image to edit. Change only this: {change}. Keep everything else exactly as in Image 1: subject, identity, layout, colors and lighting. No extra text, no watermark.
```
Light single edits ("make the cup blue", "remove the person on the left"): 1 slot.

```template edit
Image 1: {image1_role}.[[ Image 2: {image2_role}.]] Change only this: {change}. Keep {preserve} exactly as in Image 1: same identity, geometry, layout and lighting.[[ Exclude: {exclude}.]] No extra text, no watermark.
```
Any single change. `preserve` e.g. "the bottle's shape, label text and the camera angle".

```template background-swap
Image 1: product photo. Replace only the background with {new_background}. Keep the product exactly as in Image 1: shape, colors, label text, reflections and position. Match the lighting to the new background: {lighting}. Add a natural contact shadow. No extra text.
```
Product photos into scenes (ads, listings).

```template style-transfer
Image 1: the subject. Image 2: the style reference. Redraw Image 1 in the style of Image 2 ({style_notes}). Keep the subject's pose, proportions and composition from Image 1.[[ Keep text "{keep_text}" legible.]] No extra text.
```
Consistent visual style across a set.

```template text-replace
Image 1: {image1_role}. Replace the text "{old_text}" with "{new_text}", keeping the same font, size, color, position and perspective. Change nothing else. Each text appears exactly once; no extra text.
```
Localizing banners and packaging. Quality `medium` or `high` for small text [S1].

## Parameters that matter

| parameter | when to change | recommended |
|---|---|---|
| quality | cost and detail; fal's default is `high` | `medium` for most edits; `high` for faces, small text, identity-sensitive edits [S2] |
| image_size | only to change the canvas | `auto` |
| background | cut-outs from a photo | `transparent` + png, and say "isolated on a fully transparent background" [S2] |
| num_images | variations | 1–2; each is billed |

## Pricing
Output priced per image like text-to-image; input images add image-token cost, so treat these numbers as a lower
bound [S3]. Sizes not in the table are estimated at the 1024×1024 price; `image_size=auto` too.

```pricing
per: image
bound: lower                # input images add image-token cost on top
count: num_images
by: image_size
columns: quality = low, medium, high, xhigh, max
landscape_4_3|portrait_4_3|1024x768|768x1024: 0.00402 0.00903 0.03612 0.06420 0.14445
square_hd|1024x1024: 0.00588 0.01317 0.05268 0.09366 0.21072
1024x1536|1536x1024: 0.00474 0.01029 0.04116 0.07377 0.16464
1920x1080|1080x1920|1920x1088|1088x1920|1920x1072|1072x1920: 0.00441 0.01029 0.03960 0.07041 0.15840
2560x1440|1440x2560: 0.00615 0.01434 0.05529 0.09828 0.22110
3840x2160|2160x3840: 0.01113 0.02595 0.10008 0.17790 0.40026
*: 0.00588 0.01317 0.05268 0.09366 0.21072
checked: 2026-09-30 https://fal.ai/models/openai/gpt-image-2.5/sunburst/edit
```

## Limitations
- Repeated edits can still shift details you meant to keep: restate the preserve list, inspect each result [S1].
- Faces and small text are the first things to drift; compare against Image 1 before reporting [S2].

## Examples
- "Replace her clothing with Gen-z fancy clothing" [S3]
- "Do not change her face, facial features, skin tone, body shape, pose, or identity in any way. Preserve her exact likeness, expression, hairstyle, and proportions." [S2]

## Sources
- [S1] Image prompting (GPT Image 2.5) — https://developers.openai.com/api/docs/guides/image-prompting — OpenAI (official) — accessed 2026-09-30
- [S2] GPT Image Generation Models Prompting Guide — https://developers.openai.com/cookbook/examples/multimodal/image-gen-models-prompting-guide — OpenAI (official) — accessed 2026-09-30
- [S3] GPT Image 2.5 Sunburst Edit — https://fal.ai/models/openai/gpt-image-2.5/sunburst/edit — fal — accessed 2026-09-30
- [S4] How To Use GPT Image 2.5 — https://fal.ai/learn/tools/how-to-use-gpt-image-2-5 — fal — accessed 2026-09-30
