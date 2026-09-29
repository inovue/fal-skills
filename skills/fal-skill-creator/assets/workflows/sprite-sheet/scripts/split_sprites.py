#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow>=10"]
# ///
"""Split a sprite sheet into one image per asset.

Generated sheets are rarely a clean grid (assets are staggered, rows overlap), so
by default this finds each asset as a connected region of the alpha channel,
merging parts closer than --min-gap (a sparkle next to a sword). Each piece is
cut out with its own mask, so a neighbor inside its bounding box never bleeds
in, then trimmed and padded.

    uv run split_sprites.py sheet.png --out sprites/ --expect 16 --pad 8
    uv run split_sprites.py sheet.png --out sprites/ --grid 4x4     # fixed cells, then trim

Without transparency (no background-removal step), the background is keyed out
by the corner color (`--bg color`). Prints a JSON summary on stdout; a count
that differs from --expect is reported as a warning and exits 3.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

Box = tuple[int, int, int, int]


def content_mask(img: Image.Image, bg: str, alpha_threshold: int, tolerance: int) -> tuple[Image.Image, str]:
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    has_alpha = alpha.getextrema()[0] < 255
    if bg == "alpha" or (bg == "auto" and has_alpha):
        return alpha.point(lambda a: 255 if a > alpha_threshold else 0), "alpha"
    rgb = rgba.convert("RGB")
    w, h = rgb.size
    corners = [rgb.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    key = tuple(sorted(c[i] for c in corners)[1] for i in range(3))  # robust to one odd corner
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, key))
    r, g, b = diff.split()
    return ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda d: 255 if d > tolerance else 0), "color"


def components(mask: Image.Image, min_gap: int, work_size: int = 512) -> list[tuple[Box, Image.Image, int]]:
    """Connected regions of the mask, as (bbox, region mask at full size, approximate pixel count).

    Labeling runs on a reduced copy (at most work_size on the long side) for speed. Any content pixel keeps
    its reduced cell on, and a dilation by min_gap merges parts that belong together.
    """
    w, h = mask.size
    f = max(1, -(-max(w, h) // work_size))
    small = mask.reduce(f) if f > 1 else mask
    small = small.point(lambda v: 255 if v > 0 else 0)
    r = max(0, -(-min_gap // f))
    grown = small.filter(ImageFilter.MaxFilter(2 * r + 1)) if r else small
    sw, sh = grown.size
    on = grown.tobytes()
    ink = small.tobytes()
    labels = [0] * (sw * sh)
    out = []
    for start in range(sw * sh):
        if not on[start] or labels[start]:
            continue
        n = len(out) + 1
        labels[start] = n
        queue, cells, count = deque([start]), [], 0
        x0, y0, x1, y1 = sw, sh, 0, 0
        while queue:
            i = queue.popleft()
            cells.append(i)
            y, x = divmod(i, sw)
            if ink[i]:
                count += 1
                x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x + 1), max(y1, y + 1)
            for dy in (-1, 0, 1):
                ny = y + dy
                if not 0 <= ny < sh:
                    continue
                for dx in (-1, 0, 1):
                    nx = x + dx
                    j = ny * sw + nx
                    if 0 <= nx < sw and on[j] and not labels[j]:
                        labels[j] = n
                        queue.append(j)
        region = bytearray(sw * sh)
        for i in cells:
            region[i] = 255
        full = Image.frombytes("L", (sw, sh), bytes(region)).resize((sw * f, sh * f), Image.NEAREST).crop((0, 0, w, h))
        full = ImageChops.multiply(full, mask)
        bbox = full.getbbox() or (x0 * f, y0 * f, min(w, x1 * f), min(h, y1 * f))
        out.append((bbox, full, count * f * f))
    return out


def grid_cut(mask: Image.Image, rows: int, cols: int) -> list[Box]:
    w, h = mask.size
    out = []
    for r in range(rows):
        for c in range(cols):
            cell = (c * w // cols, r * h // rows, (c + 1) * w // cols, (r + 1) * h // rows)
            bbox = mask.crop(cell).getbbox()
            if bbox:
                out.append((cell[0] + bbox[0], cell[1] + bbox[1], cell[0] + bbox[2], cell[1] + bbox[3]))
    return out


def reading_order(boxes: list[Box]) -> list[Box]:
    """Top-to-bottom rows (boxes whose vertical centers overlap a row), left to right within each."""
    rows: list[list[Box]] = []
    for b in sorted(boxes, key=lambda b: (b[1] + b[3]) / 2):
        cy = (b[1] + b[3]) / 2
        if rows and rows[-1][0][1] <= cy <= rows[-1][0][3]:
            rows[-1].append(b)
        else:
            rows.append([b])
    return [b for row in rows for b in sorted(row, key=lambda b: b[0])]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input")
    p.add_argument("--out", required=True, help="directory for the pieces (created)")
    p.add_argument("--grid", metavar="RxC", help="cut fixed cells (e.g. 4x4) instead of following gaps")
    p.add_argument("--expect", type=int, help="number of assets expected; a mismatch exits 3")
    p.add_argument("--bg", choices=["auto", "alpha", "color"], default="auto")
    p.add_argument("--alpha-threshold", type=int, default=16, help="alpha above this counts as content")
    p.add_argument("--tolerance", type=int, default=28, help="--bg color: channel difference that counts as content")
    p.add_argument("--min-gap", type=int, default=8, help="parts closer than this many pixels count as one asset")
    p.add_argument("--min-area", type=float, default=0.001, help="drop specks smaller than this fraction of the sheet")
    p.add_argument("--pad", type=int, default=8, help="transparent margin around each piece")
    p.add_argument("--square", action="store_true", help="pad each piece to a square canvas")
    p.add_argument("--prefix", default="sprite")
    a = p.parse_args(argv)

    img = Image.open(a.input)
    mask, mode = content_mask(img, a.bg, a.alpha_threshold, a.tolerance)
    area = mask.size[0] * mask.size[1]
    if a.grid:
        r, _, c = a.grid.lower().partition("x")
        found = [(b, None, (b[2] - b[0]) * (b[3] - b[1])) for b in grid_cut(mask, int(r), int(c))]
    else:
        found = components(mask, a.min_gap)
    specks = [x for x in found if x[2] < a.min_area * area]
    kept = [x for x in found if x[2] >= a.min_area * area]
    order = reading_order([x[0] for x in kept])
    kept.sort(key=lambda x: order.index(x[0]))

    src = img.convert("RGBA")
    if mode == "color":  # make the keyed background transparent in the pieces too
        src.putalpha(ImageChops.multiply(src.getchannel("A"), mask))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pieces = []
    for i, (b, region, _) in enumerate(kept, 1):
        piece = src.crop(b)
        if region is not None:  # keep only this asset, even where a neighbor enters its bounding box
            piece.putalpha(ImageChops.multiply(piece.getchannel("A"), region.crop(b)))
        w, h = piece.size
        cw, ch = w + 2 * a.pad, h + 2 * a.pad
        if a.square:
            cw = ch = max(cw, ch)
        canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        canvas.paste(piece, ((cw - w) // 2, (ch - h) // 2))
        path = out / f"{a.prefix}-{i:02d}.png"
        canvas.save(path)
        pieces.append({"file": str(path.resolve()), "box": list(b), "size": [cw, ch]})

    summary: dict = {"input": str(Path(a.input).resolve()), "mode": mode, "count": len(pieces), "pieces": pieces}
    if specks:
        summary["dropped_specks"] = len(specks)
    code = 0
    if a.expect is not None and a.expect != len(pieces):
        summary["warning"] = (
            f"expected {a.expect} assets, found {len(pieces)}. Fewer: two assets touch or sit closer than --min-gap "
            "(lower it, or regenerate with more spacing). More: detached parts or specks (raise --min-gap or "
            "--min-area)."
        )
        code = 3
    print(json.dumps(summary, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
