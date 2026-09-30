# Keyframe → video

A video model animates whatever it's given, flaws included, and video costs 10–30× more than an image. So the look
is designed and approved as a still first (GPT Image 2.5, cheap and controllable), and only then animated (H3 Max).

## 1. Ask first (one message, only what's missing)

- **What it's for** and **where it runs**: product ad, social post, website hero… This decides the aspect ratio
  (16:9 → preset `hero`; 9:16 → `--preset vertical` on the keyframe) and the length.
- **Subject and setting**: the product or scene, and any reference photo (then use `gpt-image-edit` for the keyframe).
- **Motion and camera**: what moves, and one camera behavior (push in, orbit, static…).
- **Sound**: ambience, music mood, dialogue (exact words and who says them), or a track to use (`target_audio_url`).
- **Delivery**: length (5–15 s) and resolution. Draft at 768P; 1080P costs twice as much per second.

## 2. `keyframe`: design the first frame

The plan uses the profile's `keyframe` template (from the GPT Image 2.5 guide) with the `hero` preset
(1920×1088; edges must be multiples of 16). Fill `use`, `subject`, `setting`, `composition` and `planned_motion`
in English, and the optional `pose_or_state` and `lighting` when the request says something about them. `planned_motion` matters: it makes the model leave room for the camera
move (a push-in needs a subject that isn't already filling the frame).

## 3. `approve`: show it before paying for video

Show the keyframe, and in one message: the motion, camera, sound, duration, resolution and the price from
`--dry-run` of the video step (H3 Max bills per second by resolution). Continue only on a yes. If they want changes,
rerun `keyframe` (with `gpt-image-edit` for small fixes: "change only …").

## 4. `video`: animate it

The plan's command uses the profile's `animate` template (H3 Max guide) with the `draft` preset and wires the
keyframe into `image_url`. Fill `action` (what moves), `camera`, `preserve` (what must stay stable), and the
optional `sound` and `speaker`/`line` for dialogue; `negatives` e.g. "No cuts, no on-screen text, no watermark,
no morphing". The profile keeps `prompt_expansion_mode=disabled` so the model gets exactly this prompt.

For a product, use the `product-reveal` template instead (`--template product-reveal`). For a clip ending on a
specific frame, generate that frame too and add `--set end_image_url=from:<run>` with the `first-last` template.

Check the result (frames, and `duration` / `has_audio` in the manifest). For delivery, rerun with `--preset final`
(1080P) and `--set seed=<the draft's seed>` to keep the take.

## Report

The video path, its duration and resolution, the runs used (`fal runs list`), and the prices of the steps.
