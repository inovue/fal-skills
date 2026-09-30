# Sprite sheet → separate transparent assets

Drawing every asset in one image keeps the style, palette and lighting identical across the set. It also costs one
generation instead of one per asset. The trade-off is resolution: a 1024 px sheet with 4×4 assets gives pieces of
roughly 200 px. When the user needs larger assets, use fewer per sheet (2×2 or 3×3) or run several sheets.

## 1. Ask first (one message, only what's missing)

- **What they're for**: game inventory, sticker pack, app icons… (goes into `{use}`).
- **What assets**: a list ("sword, shield, potion…") or a theme and a count ("12 fantasy items").
- **Style**: pixel art, flat vector, 3D clay, hand-drawn… and a palette, if they have one.
- **Size needed per asset**: this decides how many fit on one sheet (above).
- **Layout**: pick rows × columns yourself from the count. Leave cells empty rather than cramming.

## 2. `sheet`: draw the sheet

The plan's command uses this template (`--template …#sheet`) with the profile's `asset` preset (transparent PNG).
Fill the slots from the user's answers. The spacing and "no text" parts stay even when the user doesn't mention
them: they are what makes the split work. The wording follows the GPT Image 2.5 guide: intended use first, then
layout, then constraints, and an explicit transparent background with clean alpha edges.

```template sheet
A sprite sheet for {use}: {count} {style} {theme} assets arranged in a {rows} by {cols} grid, in reading order: {item_list}.
Each asset is centered in its own cell with wide empty space around it; no asset touches another asset or the edge of the image.
Background: {backdrop}. No grid lines, no text, no labels, no cast shadows on the background.
Consistent style, palette and lighting across all assets, same scale, front view. Clean alpha edges, no halo or fringing.
```

- `{use}`: "a mobile RPG inventory screen", "a sticker pack"…
- `{count}`, `{rows}`, `{cols}`: the number of assets and the grid you chose (leave cells empty rather than cram).
- `{style}`: "16-bit pixel art", "flat vector", "glossy 3D"… with the palette if the user gave one. `{theme}`: "fantasy item".
- `{item_list}`: the assets in reading order, comma-separated, in English.
- `{backdrop}`: fixed by the workflow to a transparent background. With a model that can't make transparency, pass
  `--slot backdrop="plain flat pure white"` (pure black for light assets) and run `cutout`.
- Size: the profile's default is 1024×768; for 3×3 or 4×4 use `--set image_size=square_hd`, and fewer assets per
  sheet when each asset must be large.
- Check (see `check` in workflow.json). Regenerating this step is cheap; everything after it is not.

## 3. `cutout` (optional): remove the background

Skip it when the sheet is already transparent and clean (the usual case with GPT Image 2.5 and the `asset` preset):
go straight to `split`, which then reads the sheet. Run it when the sheet came back with a backdrop, a drawn
checkerboard or a fringe. No prompt; the plan's `--from label:<workflow>.sheet` wires the sheet in.

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

List the files with their sizes, the runs used (`fal runs list`), and anything that went wrong. Offer to redo single
assets: generate just that one with the profile's `asset` template, `--preset asset`.
