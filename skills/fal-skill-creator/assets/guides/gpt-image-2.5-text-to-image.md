<!--
status: researched
researched_at: 2026-09-30
model: openai/gpt-image-2.5/sunburst/text-to-image (also flare/text-to-image: same prompting, same prices)
Bundled with fal-skill-creator. Re-check the Sources and the pricing block when OpenAI or fal update the model.
-->
# Input guide: GPT Image 2.5 (text to image)

`openai/gpt-image-2.5/sunburst/text-to-image` · text-to-image · Sunburst = the quality model; Flare = up to ~50%
faster, quality comparable to GPT Image 2, **same price** [S1][S3]. Start with Sunburst when quality matters; try Flare
with the same prompt when latency does [S1].

## Key rules
- Define the result first: subject, intended use (product photo, poster, diagram…), composition, aspect ratio and
  placement. For complex requests use short labeled sections in this order: scene → subject → details → constraints [S1][S2].
- Describe what is visible: materials, lighting, colors, medium. Say "photorealistic" / "real photograph" when you
  want a photo; camera terms are appearance cues, not guarantees [S1].
- Exact text goes in quotation marks with its position and typography ("bold sans-serif, centered"); spell unusual
  words letter by letter, say how many times it appears, and add "no extra text" [S1][S4].
- People: state framing, scale, gaze and interaction ("full body visible, feet included") [S1].
- There is no special syntax: prose, labeled blocks or JSON-like structure all work; pick what's easy to maintain [S1].
- Iterate one change at a time and restate the critical constraints each round [S1].

## Prompt structure
Scene/background → subject → key details (materials, light, color, style) → constraints (text, exclusions). Put the
intended use in the first sentence. Keep one idea per prompt; split two changes into two runs [S2][S4].

**Language.** Write the prompt in English. Translate the user's Japanese descriptions into the slots; keep only text
that must appear in the image verbatim (e.g. a Japanese headline) in its original script, in quotes, and check it
in the output.

## Inputs
Text only. `image_size` is decided before the run, not fixed afterwards [S4]. Preset sizes on fal (measured
2026-09-30): `square_hd` 1024×1024, `square` 816×816, `landscape_4_3` 1024×768, `portrait_4_3` 768×1024,
`landscape_16_9` **1088×608**, `portrait_16_9` **608×1088**. For real 16:9 or 9:16 output (heroes, video keyframes)
pass a custom size: `image_size={"width":1920,"height":1088}` (edges must be multiples of 16: a requested 1920×1080
comes back as 1920×1072; measured 2026-09-30). Custom sizes: both edges multiples of 16, long edge
≤ 3840, ratio ≤ 3:1, 655,360–8,294,400 pixels; above 3,686,400 pixels is experimental [S1][S2].
Transparent output: `background=transparent` with `png` or `webp` (never jpeg), and say so in the prompt [S1][S2].

## Templates

```template quick
{intended_use} of {subject}.[[ Style: {style}.]] One clear focal subject, balanced composition, natural light, true-to-life detail. No added text, no watermark.
```
Light requests ("a cat illustration", "an icon of a rocket"): 2 slots. `intended_use` e.g. "A watercolor illustration".

```template general
{intended_use}: {subject}.[[ Details: {details}.]][[ Setting: {setting}.]][[ Style: {style}.]][[ Lighting: {lighting}.]][[ Composition: {composition}.]][[ Exclude: {exclude}.]]
```
When the request has several specifics but no dedicated template fits. `intended_use` e.g. "Editorial blog header image".

```template product-shot
Photorealistic product photograph for {use}. {product}, placed on {surface}, {angle}. Lighting: {lighting}. Background: {backdrop}.[[ Sharp focus on {focus_detail}.]] Natural reflections and true-to-life materials.[[ Props: {props}.]] No text, no logos other than those on the product, no watermark.
```
E-commerce and ad images. `angle` e.g. "three-quarter view at eye level"; `lighting` e.g. "large softbox from the left, soft shadow".

```template text-graphic
{format} for {use}. Headline: "{headline}" in {typography}, placed {headline_position}.[[ Secondary text: "{secondary_text}" in {secondary_typography}, {secondary_position}.]] Visual: {visual}. Palette: {palette}. All text is real, legible and correctly spelled; each text appears exactly once; no extra text.
```
Posters, banners, thumbnails, slides. Use quality `medium` or `high` for small text [S1].

```template asset
A single {asset} as an isolated {style} asset for {use}, centered, fully visible with a small margin, on a fully transparent background. No scenery, no solid backdrop, no checkerboard, no ground shadow. Clean alpha edges, no halo or fringing.[[ Details: {details}.]]
```
Icons, stickers, cut-out objects. Run with `background=transparent`, `output_format=png` (preset `asset`) [S1][S2].

```template keyframe
First frame of a video shot for {use}. {subject} in {setting}.[[ {pose_or_state}.]] Composition: {composition}, leaving room for {planned_motion}.[[ Lighting: {lighting}.]] Photorealistic, cinematic, no text, no watermark.
```
A still that an image-to-video model (e.g. H3 Max) will animate. Use a custom 16:9/9:16 size that matches the video.

## Parameters that matter

| parameter | when to change | recommended |
|---|---|---|
| quality | the main cost and detail lever; fal's default is `high` | `medium` for most work; `high` for small/dense text, close-up faces; `low` for drafts; `xhigh`/`max` only when high fails [S1] |
| image_size | aspect ratio and cost | custom `{"width":1920,"height":1088}` / `{"width":1088,"height":1920}` instead of the 16:9 presets |
| background | cut-out assets | `transparent` + png (preset `asset`) |
| num_images | variations | 1–4; each is billed |
| output_format | size vs alpha | `png` (alpha), `webp` + `output_compression` for web delivery |

Suggested presets: `hero` (`image_size={"width":1920,"height":1088}`), `vertical` (`{"width":1088,"height":1920}`),
`asset` (`background=transparent output_format=png`).

## Pricing
Per image, by size and quality; prompt length and complexity add a little (token billing) [S3]. Sizes not in fal's
table are estimated at the 1024×1024 price. `quality=auto` can't be estimated.

```pricing
per: image
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
checked: 2026-09-30 https://fal.ai/models/openai/gpt-image-2.5/sunburst/text-to-image
```

## Limitations
- A higher quality setting doesn't guarantee a better result for every prompt; compare `medium` and `high` [S1].
- Transparent backgrounds: check the alpha on hair, glass, shadows and edges; the feature was in preview [S1][S2].
- Dense diagrams need white space; verify every label and fact, not just the look [S1].
- Repeated edits drift; for a series, restate the constraints each time [S1].

## Examples
- "35mm film photograph, medium close-up at eye level, using a 50mm lens. Soft coastal daylight, shallow depth of field, subtle film grain, natural color balance." [S1]
- "Create a realistic mobile app UI mockup for a local farmers market. Show today's market with a simple header, a short list of vendors…" [S2]

## Sources
- [S1] Image prompting (GPT Image 2.5) — https://developers.openai.com/api/docs/guides/image-prompting — OpenAI (official) — accessed 2026-09-30
- [S2] GPT Image Generation Models Prompting Guide — https://developers.openai.com/cookbook/examples/multimodal/image-gen-models-prompting-guide — OpenAI (official) — accessed 2026-09-30
- [S3] GPT Image 2.5 Sunburst Text to Image — https://fal.ai/models/openai/gpt-image-2.5/sunburst/text-to-image — fal — accessed 2026-09-30
- [S4] How To Use GPT Image 2.5 — https://fal.ai/learn/tools/how-to-use-gpt-image-2-5 — fal — accessed 2026-09-30
