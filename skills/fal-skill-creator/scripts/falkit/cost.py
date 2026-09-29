"""Best-effort cost estimates from fal unit pricing.

fal bills per unit (image, megapixel, second of video, request, …). We map the
unit onto the request arguments. Estimates are deliberately conservative
(round up) and carry a confidence so the guard can decide when to ask a human.
"""

from __future__ import annotations

import math
import os
import re
from typing import Any

DEFAULT_MAX_USD = 1.00
UNKNOWN_UNIT_AUTO_OK_USD = 0.05  # unknown quantity but the unit itself is cheap → just warn
GPU_SECONDS_ASSUMED = 60  # GPU-time pricing: assume up to a minute per request when checking the limit

# fal's named image sizes (width x height)
IMAGE_SIZES = {
    "square_hd": (1024, 1024),
    "square": (512, 512),
    "portrait_4_3": (768, 1024),
    "portrait_16_9": (576, 1024),
    "landscape_4_3": (1024, 768),
    "landscape_16_9": (1024, 576),
}


def _count(args: dict) -> int:
    for k in ("num_images", "num_outputs", "num_videos", "num_samples", "n", "batch_size"):
        v = args.get(k)
        if isinstance(v, int) and v > 0:
            return v
    return 1


def _seconds(args: dict, input_schema: dict) -> float | None:
    props = input_schema.get("properties") or {}
    for k in ("duration", "duration_seconds", "seconds", "num_seconds", "video_length", "length"):
        v = args.get(k, (props.get(k) or {}).get("default"))
        if v is None:
            continue
        m = re.match(r"^\s*(\d+(?:\.\d+)?)", str(v))
        if m:
            return float(m.group(1))
    if "num_frames" in args or "num_frames" in props:
        frames = args.get("num_frames", (props.get("num_frames") or {}).get("default"))
        fps = args.get("fps", (props.get("fps") or {}).get("default")) or 24
        if isinstance(frames, (int, float)) and isinstance(fps, (int, float)) and fps:
            return frames / fps
    return None


def _megapixels(args: dict, input_schema: dict) -> tuple[float, bool]:
    props = input_schema.get("properties") or {}
    size = args.get("image_size", (props.get("image_size") or {}).get("default"))
    if isinstance(size, dict) and size.get("width") and size.get("height"):
        return size["width"] * size["height"] / 1_000_000, True
    if isinstance(size, str) and size in IMAGE_SIZES:
        w, h = IMAGE_SIZES[size]
        return w * h / 1_000_000, True
    if args.get("width") and args.get("height"):
        return args["width"] * args["height"] / 1_000_000, True
    return 1.0, False


def estimate(price: dict | None, args: dict, input_schema: dict) -> dict[str, Any]:
    if not price or price.get("unit_price") is None:
        return {"usd": None, "confidence": "unknown", "reason": "no pricing available"}
    unit = str(price.get("unit", "")).lower().strip()
    unit_price = float(price["unit_price"])
    n = _count(args)
    qty: float | None
    confidence = "high"
    if "compute" in unit or "gpu" in unit:
        # Billed by GPU time, which depends on the input and the queue, not on a request argument.
        # Never map it onto `duration`: a 5 s video can take minutes of compute.
        return {
            "usd": None,
            "unit_price": unit_price,
            "unit": unit,
            "quantity": None,
            "confidence": "unknown",
            "reason": f"billed by GPU time (${unit_price} per {unit})",
            "currency": price.get("currency", "USD"),
        }
    if unit in {"image", "images"}:
        qty = n
    elif unit in {"megapixel", "megapixels", "mp"}:
        mp, known = _megapixels(args, input_schema)
        qty = round(mp, 2) * n  # fal bills fractional megapixels
        confidence = "high" if known else "medium"
    elif unit in {"second", "seconds", "sec", "s"} or "second" in unit:
        secs = _seconds(args, input_schema)
        qty = math.ceil(secs) * n if secs else None
        confidence = "high" if secs else "unknown"
    elif unit in {"minute", "minutes"}:
        secs = _seconds(args, input_schema)
        qty = math.ceil(secs / 60 * 100) / 100 * n if secs else None
        confidence = "medium" if secs else "unknown"
    elif unit in {
        "video",
        "videos",
        "request",
        "requests",
        "call",
        "calls",
        "generation",
        "generations",
        "unit",
        "units",
        "run",
        "runs",
    }:
        qty = n
    else:
        qty = None
        confidence = "unknown"
    usd = round(unit_price * qty, 4) if qty is not None else None
    return {
        "usd": usd,
        "unit_price": unit_price,
        "unit": unit,
        "quantity": qty,
        "confidence": confidence,
        "currency": price.get("currency", "USD"),
    }


def max_usd(cli_value: float | None, profile: dict | None) -> float:
    if cli_value is not None:
        return cli_value
    prof_val = ((profile or {}).get("cost_guard") or {}).get("max_usd")
    if prof_val is not None:
        return float(prof_val)
    env = os.environ.get("FAL_MAX_COST")
    if env:
        return float(env)
    return DEFAULT_MAX_USD


def guard(total: dict, limit: float) -> tuple[bool, str]:
    """Return (ok, reason). ok=False means: stop and ask the human."""
    usd = total.get("usd")
    if usd is None:
        unit_price = total.get("unit_price")
        unit = str(total.get("unit") or "")
        if unit_price is not None and ("compute" in unit or "gpu" in unit):
            items = total.get("items") or 1
            worst = unit_price * GPU_SECONDS_ASSUMED * items
            if worst <= limit:
                return True, f"billed by GPU time; up to ~${worst:.4f} for {items} request(s) at {GPU_SECONDS_ASSUMED}s each"
            return False, (
                f"billed by GPU time (${unit_price} per {unit}); {items} request(s) could reach ~${worst:.2f} "
                f"at {GPU_SECONDS_ASSUMED}s each, above the ${limit:g} limit"
            )
        if unit_price is not None and unit_price <= UNKNOWN_UNIT_AUTO_OK_USD:
            return True, f"quantity unknown for unit {total.get('unit')!r}; unit price ${unit_price} is small"
        return False, (
            "cost could not be estimated"
            + (f" (unit {total.get('unit')!r} @ ${unit_price})" if unit_price is not None else "")
        )
    if usd > limit:
        return False, f"estimated ${usd:.4f} exceeds the ${limit:g} limit"
    return True, f"estimated ${usd:.4f} ≤ ${limit:g} limit"


def combine(estimates: list[dict]) -> dict:
    if not estimates:
        return {"usd": 0.0, "confidence": "high"}
    if any(e.get("usd") is None for e in estimates):
        first = estimates[0]
        return {
            "usd": None,
            "confidence": "unknown",
            "unit": first.get("unit"),
            "unit_price": first.get("unit_price"),
            "items": len(estimates),
        }
    order = ["high", "medium", "low", "unknown"]
    worst = max((e.get("confidence", "high") for e in estimates), key=order.index)
    return {
        "usd": round(sum(e["usd"] for e in estimates), 4),
        "confidence": worst,
        "unit": estimates[0].get("unit"),
        "unit_price": estimates[0].get("unit_price"),
        "items": len(estimates),
    }
