# Sprite sheet → separate transparent assets

Drawing every asset in one image keeps the style, palette and lighting identical across the set. It also costs one
generation instead of one per asset. The trade-off is resolution: a 1024 px sheet with 4×4 assets gives pieces of
roughly 200 px. When the user needs larger assets, use fewer per sheet (2×2 or 3×3) or run several sheets.

## 1. Ask first (one message, only what's missing)

- **What assets**: a list ("sword, shield, potion…") or a theme and a count ("12 fantasy items").
- **Style**: pixel art, flat vector, 3D clay, hand-drawn… and a palette, if they have one.
- **Size needed per asset**: this decides how many fit on one sheet (above).
- **Layout**: pick rows × columns yourself from the count. Leave cells empty rather than cramming.

## 2. `sheet`: draw the sheet

Fill this template. Keep the spacing and "no text" parts even when the user doesn't mention them; they are what
makes the split work.

```
A sprite sheet of {count} {style} {theme} assets arranged in a {rows} by {cols} grid: {item_list}.
Each asset is centered in its own cell with wide empty space around it; no asset touches another or the edge.
Plain flat {background} background, no grid lines, no text, no labels, no shadows on the background.
Consistent style, palette and lighting across all assets, same scale, front view.
```

- `{background}`: pure white by default. Use pure black for white or very light assets.
- The profile's own `prompting.md` may add model-specific advice; follow it.
- Check (see `check` in workflow.json). Regenerating this step is cheap; everything after it is not.

## 3. `cutout`: remove the background

No prompt. The `--from label:<workflow>.sheet` in the plan wires the sheet into `image_url`. Look at the result: fine details such as
thin swords, hair and glows are where background removal fails. If important parts are gone, try the profile's
higher-resolution setting or skip this step and let the split key out the plain background (`--bg color`).

## 4. `split`: cut into pieces

Run the command from `fal workflow plan`, adding `--expect <count>`. The script finds each asset as a connected
region, so staggered or uneven layouts are fine. Exit code 3 means the count didn't match:

- **Fewer pieces** than expected: two assets touch, or sit closer than `--min-gap` (default 8 px). Lower
  `--min-gap`, or regenerate the sheet with more spacing. `--grid RxC` cuts fixed cells when the sheet is a clean
  grid.
- **More pieces**: detached parts (sparkles, a separate shadow) or specks. Raise `--min-gap` so nearby parts merge,
  or raise `--min-area` (default 0.001 of the sheet) to drop specks.
- Useful options: `--square` for icon sets, `--pad N` for margins, `--prefix name`.

Then record the pieces with the `then` command from the plan (`fal ingest … --move`), so they have a manifest and can
feed later steps (upscaling each piece, for example, with `--set image_url=from:label:<workflow>.split#<n>`).

## 5. Report

List the files with their sizes, the total cost (`fal runs list`), and anything that went wrong. Offer to redo single
assets: generate just that one with the sheet profile and a matching prompt, then run `cutout` on it.
