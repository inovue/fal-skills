<!--
status: researched
researched_at: 2026-09-30
model: minimax/h3-max/text-to-video
Bundled with fal-skill-creator. Re-check the Sources and the pricing block when MiniMax or fal update the model.
-->
# Input guide: MiniMax H3 Max (text to video)

`minimax/h3-max/text-to-video` · text-to-video · fal's post-trained H3 variant, tuned for prompt adherence and
aesthetics [S3]. 5–15 s with native audio; aspect ratio from `aspect_ratio` [S2][S3]. For tight control over the
look, generate a keyframe with an image model and use image-to-video instead.

## Key rules
- Open with length, format and the core idea: "15 seconds, 16:9 landscape. …" [S2].
- Write the scene in chronological order; beyond one beat use a timed shot list `[0–3s] …` [S1][S2].
- Choose one main camera behavior per shot and name it with film language (lens, movement, exposure, stock) [S1][S2].
- Exact dialogue in quotes with the speaker, short enough for the time; describe ambience and music by instruments,
  timing and mood, not by naming songs [S1][S2].
- End with negative constraints ("no on-screen text, no watermark, no hard cuts") [S2].

## Prompt structure
Length + format + core idea → style and lighting → timed actions → camera → audio → negative constraints [S1][S2].
Write in English; dialogue may be in the speaker's language, in quotes.

## Inputs
- Text only (plus optional `target_audio_url`: ≥ 2 s, ≤ 15 MB, replaces the generated soundtrack) [S3].
- `prompt_expansion_mode`: `disabled` keeps the prompt as written; `balanced` (default, ~1 s); `quality` (up to ~30 s)
  [S3]. Use `disabled` for templated prompts with exact dialogue or timing; check `expanded_prompt` in the manifest.

## Templates

```template quick
{=duration} seconds, {=aspect_ratio}. {scene}. Camera: {camera}. Natural ambient sound. No on-screen text, no watermark, no hard cuts.
```
Light requests: 2 slots.

```template scene
{=duration} seconds, {=aspect_ratio}. {core_idea}.[[ Style: {style}.]][[ Lighting: {lighting}.]] {action}. Camera: {camera}.[[ Sound: {sound}.]][[ Dialogue: {speaker} says "{line}".]] {negatives}.
```
One continuous scene. `negatives` e.g. "No on-screen text, no watermark, no hard cuts".

```template sequence
{=duration} seconds, {=aspect_ratio}. {core_idea}.[[ Style: {style}.]]
{shot_list}
Keep {preserve} consistent across shots.[[ Sound: {sound}.]][[ Dialogue: {dialogue}.]] {negatives}.
```
Multi-beat clips. `shot_list`: one line per beat, "[0–3s] … [3–7s] …".

## Parameters that matter

| parameter | when to change | recommended |
|---|---|---|
| resolution | the price lever | `768P` for drafts; `1080P` for delivery [S3] |
| duration | length and price | 5 for tests; up to 15 |
| aspect_ratio | format | match the platform: `9:16` shorts, `16:9` landscape |
| prompt_expansion_mode | model-side rewriting | `disabled` with templates; `balanced` for short prompts |

## Pricing
Per second, by resolution. The launch promotion ended 2026-09-30; regular prices below [S3].

```pricing
per: second
count: duration
by: resolution
480P: 0.05
768P: 0.08
1080P: 0.16
checked: 2026-09-30 https://fal.ai/models/minimax/h3-max/text-to-video
```

## Limitations
- The look is less controllable than starting from a keyframe; for brand or product accuracy use image-to-video.
- Identity drifts in wide shots with small faces; keep faces large [S2].

## Examples
- "15 seconds, 16:9 landscape. Blend live-action footage of a small kitchen at dusk with hand-drawn luminous animation. The last sunset light lingers at the window. … Do not show giant eyes, split mouths, fangs, threatening behavior, lunges, sudden black frames, or jump scares." [S2]

## Sources
- [S1] MiniMax H3 Prompt Guide — https://www.rundiffusion.com/minimax-h3-prompt-guide — RunDiffusion (community, heuristic) — accessed 2026-09-30
- [S2] MiniMax H3 Prompting Guide + 44 Video Examples — https://fal.ai/learn/devs/minimax-h3-prompting-guide — fal — accessed 2026-09-30
- [S3] H3 Max Text to Video — https://fal.ai/models/minimax/h3-max/text-to-video — fal — accessed 2026-09-30
