"""Model catalog: search the fal model list, newest first, plus pricing.

The fal models API has no sort parameter and returns ~1500 models over ~16
pages, so we crawl the whole catalog once, cache it, and filter/sort locally.
That makes "newest first" exact and repeated searches instant.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .core import FalkitError, cache_dir, http_json, log, resolve_key, write_json

MODELS_URL = "https://api.fal.ai/v1/models"
PRICING_URL = "https://api.fal.ai/v1/models/pricing"
ESTIMATE_URL = "https://api.fal.ai/v1/models/pricing/estimate"
CACHE_TTL_S = 6 * 3600


def _normalize(m: dict) -> dict:
    md = m.get("metadata") or {}
    return {
        "endpoint_id": m["endpoint_id"],
        "display_name": md.get("display_name") or m["endpoint_id"],
        "category": md.get("category") or "unknown",
        "kind": md.get("kind") or "inference",
        "status": md.get("status") or "active",
        "date": md.get("date") or md.get("updated_at") or "",
        "updated_at": md.get("updated_at") or "",
        "license_type": md.get("license_type"),
        "tags": md.get("tags") or [],
        "description": md.get("description") or "",
        "playground_url": f"https://fal.ai/models/{m['endpoint_id']}",
    }


def _crawl() -> list[dict]:
    key = resolve_key(required=False)  # auth is optional but raises rate limits
    models: list[dict] = []
    cursor = None
    for _ in range(200):  # hard stop; the catalog is ~16 pages today
        params: dict[str, Any] = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        page = http_json("GET", MODELS_URL, params=params, key=key, retries=6)
        models.extend(_normalize(m) for m in page.get("models", []))
        cursor = page.get("next_cursor")
        if not page.get("has_more") or not cursor:
            break
    return models


def load_catalog(refresh: bool = False) -> list[dict]:
    path = cache_dir() / "models.json"
    if not refresh and path.exists():
        try:
            cached = json.loads(path.read_text())
            if time.time() - cached["fetched_at"] < CACHE_TTL_S:
                return cached["models"]
        except (json.JSONDecodeError, KeyError):
            pass
    log("Fetching fal model catalog (cached for 6h)…")
    models = _crawl()
    write_json(path, {"fetched_at": time.time(), "models": models})
    return models


def search(
    query: str | None = None,
    category: str | None = None,
    since_days: int | None = None,
    include_training: bool = False,
    include_inactive: bool = False,
    refresh: bool = False,
    models: list[dict] | None = None,
) -> list[dict]:
    """Filter the catalog and return it newest-first.

    `query` terms are ANDed and matched case-insensitively against endpoint id,
    display name, tags, category and description — so "kling i2v" style
    queries narrow quickly.
    """
    models = models if models is not None else load_catalog(refresh)
    terms = [t.lower() for t in (query or "").split() if t]
    cutoff = None
    if since_days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()

    def keep(m: dict) -> bool:
        if not include_training and (m["kind"] == "training" or m["category"] == "training"):
            return False
        if not include_inactive and m["status"] != "active":
            return False
        if category and m["category"] != category:
            return False
        if cutoff and m["date"] < cutoff:
            return False
        hay = " ".join(
            [m["endpoint_id"], m["display_name"], m["category"], " ".join(m["tags"]), m["description"]]
        ).lower()
        return all(t in hay for t in terms)

    hits = [m for m in models if keep(m)]
    # Strictly newest-first: predictable ordering beats relevance heuristics here.
    hits.sort(key=lambda m: m["date"], reverse=True)
    return hits


def categories(models: list[dict] | None = None) -> list[tuple[str, int]]:
    models = models if models is not None else load_catalog()
    counts: dict[str, int] = {}
    for m in models:
        if m["kind"] != "training":
            counts[m["category"]] = counts.get(m["category"], 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def get_model(endpoint_id: str) -> dict | None:
    for m in load_catalog():
        if m["endpoint_id"] == endpoint_id:
            return m
    # Brand-new models may postdate the cache; ask the API directly.
    page = http_json("GET", MODELS_URL, params={"endpoint_id": endpoint_id}, key=resolve_key(required=False))
    models = page.get("models") or []
    return _normalize(models[0]) if models else None


def get_prices(endpoint_ids: list[str]) -> dict[str, dict]:
    """Unit prices per endpoint (batched). Requires a key; returns {} if none is available."""
    key = resolve_key(required=False)
    if not key or not endpoint_ids:
        return {}
    out: dict[str, dict] = {}
    for i in range(0, len(endpoint_ids), 50):
        params = [("endpoint_id", e) for e in endpoint_ids[i : i + 50]]
        try:
            data = http_json("GET", PRICING_URL, params=params, key=key)
        except FalkitError as e:
            log(f"warning: pricing lookup failed: {e}")
            continue
        out.update({p["endpoint_id"]: p for p in data.get("prices", [])})
    return out


def format_table(models: list[dict], limit: int) -> str:
    rows = []
    for i, m in enumerate(models[:limit], 1):
        rows.append(
            f"{i:>3}. {m['endpoint_id']}\n"
            f"     {m['display_name']} · {m['category']} · {m['date'][:10]}"
            + (f" · {m['license_type']}" if m.get("license_type") else "")
            + (f" · ${m['price']['unit_price']}/{m['price']['unit']}" if m.get("price") else "")
        )
    more = len(models) - limit
    if more > 0:
        rows.append(f"     … {more} more (raise --limit or narrow the query)")
    return "\n".join(rows) if rows else "No models matched."
