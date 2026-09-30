<!--
status: researched
researched_at: 2026-09-30
model: minimax/h3-max/image-to-video
Bundled with fal-skill-creator. Re-check the Sources and the pricing block when MiniMax or fal update the model.
-->
# Input guide: MiniMax H3 Max (image to video)

`minimax/h3-max/image-to-video` · image-to-video · fal's post-trained H3 variant, tuned for prompt adherence and
aesthetics [S3]. 5–15 s, native audio (dialogue, ambience, music), first and/or last frame [S2][S3].

## Key rules
- The image is a constraint, not a description: don't redescribe what's in the frame; write the motion, camera and
  sound that happen *from* it ("animate …, preserving …") [S2].
- Choose one main camera behavior per shot and name it (lens, movement, speed only when it helps) [S1][S2]; for a
  still camera say so ("locked off, static shot, no push in") (heuristic).
- Longer than one beat → a timed shot list: `[0–3s] …`, `[3–6s] …` [S2].
- Direct the sound: exact dialogue in quotes with who says it, short enough for the time available [S1]; ambience
  and music by instrument and timing; describe music by mood and structure, never by naming an existing song [S2].
- End with negative constraints: "no cuts, no on-screen text, no watermark, no morphing" as needed [S2].
- With first **and** last frame: say which is which and describe the motion that connects them [S2].

## Prompt structure
Core idea (one sentence: what happens, mood, format) → timed actions → camera (lens, movement, exposure) →
identity/details to keep stable → audio (dialogue, ambience, music) → negative constraints [S2]. Write in English;
dialogue may be in the language the character speaks, in quotes.

## Inputs
- `image_url` (first frame) and/or `end_image_url` (last frame); the output canvas follows the given frame [S3].
  jpg, png, webp, gif, avif, heic [S3]. Match the video: a 16:9 video needs a 16:9 still (from GPT Image 2.5 use
  `image_size={"width":1920,"height":1088}` (preset `hero`), not the 1088×608 preset). Leave space in the still for the planned motion.
- Wire one run per frame: `--from <keyframe run>` fills `image_url`; add the last frame explicitly with
  `--set end_image_url=from:<run>`. A second variant of the same run is never used as the last frame.
- `target_audio_url` (optional): ≥ 2 s, ≤ 15 MB; replaces the generated soundtrack, trimmed to the duration [S3].
- `prompt_expansion_mode` rewrites the prompt before generation: `disabled` keeps it as written, `balanced` (default,
  ~1 s), `quality` (up to ~30 s, richer) [S3]. Use `disabled` when the prompt comes from a researched template and
  exact wording matters (dialogue, timing); keep `balanced` for short prompts. Read `expanded_prompt` in the
  manifest (`fal runs show`) to see what the model actually received.

## Templates

```template quick
Animate this frame: {action}. Camera: {camera}. Keep the subject and composition of the frame stable. Natural ambient sound. No cuts, no on-screen text, no watermark, no morphing.
```
Light requests ("make it move a little", "slow zoom"): 2 slots.

```template animate
Animate this frame: {action}. Camera: {camera}. Keep {preserve} stable throughout.[[ Sound: {sound}.]][[ Dialogue: {speaker} says "{line}".]] {negatives}.
```
One continuous shot from a keyframe. `camera` e.g. "slow push in, 35 mm, shallow depth of field" or "locked off, static".
`negatives` e.g. "No cuts, no on-screen text, no watermark, no morphing".

```template product-reveal
{=duration}-second product video. The {product} stays exactly as in the frame: shape, colors, label text. {motion}. Camera: {camera}.[[ Lighting: {lighting}.]][[ Sound: {sound}.]] No cuts, no added text or logos, no morphing of the product.
```
Ads and listings from a product still. `motion` e.g. "the bottle rotates slowly a quarter turn".

```template sequence
{core_idea}.
{shot_list}
Camera: {camera}. Keep {preserve} consistent across all shots.[[ Dialogue: {dialogue}.]][[ Sound: {sound}.]] {negatives}.
```
Multi-beat clips. `shot_list` is one line per beat: "[0–3s] … [3–6s] …".

```template first-last
Transition from the first frame to the last frame: {transition}. Camera: {camera}.[[ Sound: {sound}.]] Keep {preserve} consistent between the two frames. No hard cuts, no dissolves.
```
With both `image_url` and `end_image_url`.

## Parameters that matter

| parameter | when to change | recommended |
|---|---|---|
| resolution | the price lever (per second) | `768P` for drafts and review; `1080P` for delivery (refined from 768P) [S3] |
| duration | length and price | 5 for tests; up to 15 [S3] |
| prompt_expansion_mode | model-side rewriting | `disabled` with templates and dialogue; `balanced` for short prompts [S3] |
| enable_safety_checker | keep on | `true` |
| seed | reproduce a take | the manifest's seed |

## Pricing
Per second of output, by resolution. fal's launch promotion (50% off) ended 2026-09-30; these are the regular
prices [S3]. The pricing API reports only the 480P rate.

```pricing
per: second
count: duration
by: resolution
480P: 0.05
768P: 0.08
1080P: 0.16
checked: 2026-09-30 https://fal.ai/models/minimax/h3-max/image-to-video
```

## Limitations
- Identity drifts in wide shots with small faces; keep faces large or use reference-to-video with a feature list [S2].
- Camera motion you didn't ask for happens; name the camera behavior for every shot (heuristic).
- The soundtrack is generated unless `target_audio_url` is given; check the manifest's video and listen before delivery.

## Examples
- "Animate the source artwork as a motion poster while preserving its white gallery border, inner frame, red/white/black palette, 3D collectible-figure look, and original layout. Add a light, playful type-on sound whenever text appears." [S2]
- "[0–2 seconds] High-angle overhead shot. The character sits, looks up. [2–4 seconds] Smoothly push in to her right arm." [S2]

## Sources
- [S1] MiniMax H3 Prompt Guide — https://www.rundiffusion.com/minimax-h3-prompt-guide — RunDiffusion (community, heuristic) — accessed 2026-09-30
- [S2] MiniMax H3 Prompting Guide + 44 Video Examples — https://fal.ai/learn/devs/minimax-h3-prompting-guide — fal — accessed 2026-09-30
- [S3] H3 Max Image to Video — https://fal.ai/models/minimax/h3-max/image-to-video — fal — accessed 2026-09-30
