"""Price estimates from the pricing table researched into prompting.md. Information only; never blocks a run.

fal's pricing API gives one unit price per endpoint, which is often not what a request costs: video models
charge more per second at higher resolutions, and token-billed image models report "$1 per unit". The model
page has the real table, so research copies it into prompting.md as a block:

    ```pricing
    per: second                 # what one price buys: image | second | request
    bound: lower                # optional: the table misses some costs (e.g. input tokens); shown as "≥ $…"
    count: duration             # arguments multiplied into the quantity (comma-separated); default 1;
                                # chars(text)/1000 counts thousands of characters of a text argument
    by: resolution              # arguments whose values select the price (comma-separated); optional
    480P: 0.05
    768P: 0.08
    1080P: 0.16                 # a row per combination of `by` values; `*` matches any value, a|b either
    checked: 2026-09-30 https://fal.ai/models/minimax/h3-max/image-to-video
    ```

A price table with a second dimension (fal's size × quality tables) can put that argument in columns:

    by: image_size
    columns: quality = low, medium, high
    square_hd|1024x1024: 0.00588 0.01317 0.05268

`estimate()` looks up the row for a request's final arguments (schema defaults fill the gaps) and multiplies.
Custom `{width, height}` sizes match rows written as `1920x1080`.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .core import EXIT_USAGE, FalkitError

_BLOCK_RE = re.compile(r"^(`{3,}|~{3,})[ \t]*pricing[ \t]*\n(.*?)^\1[ \t]*$", re.M | re.S)
_CHARS_RE = re.compile(r"chars\((\w+)\)(?:\s*/\s*(\d+))?")
_RESERVED = {"per", "count", "by", "columns", "checked", "note", "bound"}
STALE_AFTER_DAYS = 30  # launch promos and repricing are common; re-check the model page monthly
OPAQUE_UNITS = ("unit", "units", "compute", "token", "gpu")


def parse(text: str) -> dict | None:
    """The pricing block of a prompting.md, or None. Raises on a malformed block."""
    m = _BLOCK_RE.search(text)
    if not m:
        return None
    table: dict[str, Any] = {
        "per": None, "count": [], "by": [], "columns": None, "rows": {}, "checked": None, "source": None, "bound": None,
    }
    for raw in m.group(2).splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, sep, value = line.rpartition(":")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            raise FalkitError(f"pricing block: can't read line {raw.strip()!r} (expected key: value)", EXIT_USAGE)
        low = key.lower()
        if low == "checked" or low.startswith("checked"):
            # "checked: 2026-09-30 https://…" — rpartition split inside the URL, so re-split on the first colon
            _, _, rest = line.partition(":")
            parts = rest.strip().split(None, 1)
            table["checked"] = parts[0] if parts else None
            table["source"] = parts[1] if len(parts) > 1 else None
        elif low in ("per", "note", "bound"):
            table[low] = value
        elif low in ("count", "by"):
            table[low] = [x.strip() for x in value.split(",") if x.strip()]
        elif low.startswith("columns"):
            _, _, spec = line.partition(":")
            arg, eq, vals = spec.partition("=")
            if not eq:
                raise FalkitError("pricing block: write columns as `columns: <argument> = v1, v2, …`", EXIT_USAGE)
            table["columns"] = (arg.strip(), [v.strip().lower() for v in vals.split(",") if v.strip()])
        else:
            try:
                prices = [float(v.lstrip("$")) for v in value.split()]
            except ValueError as e:
                raise FalkitError(f"pricing block: {value!r} in {raw.strip()!r} is not a price", EXIT_USAGE) from e
            cols = table["columns"]
            if cols and len(prices) != len(cols[1]):
                raise FalkitError(
                    f"pricing block: {raw.strip()!r} has {len(prices)} price(s) for {len(cols[1])} column(s)", EXIT_USAGE
                )
            if not cols and len(prices) != 1:
                raise FalkitError(f"pricing block: {raw.strip()!r} has several prices but no `columns:` line", EXIT_USAGE)
            row = tuple(x.strip() for x in key.split(","))
            table["rows"][row] = dict(zip(cols[1], prices, strict=True)) if cols else prices[0]
    if not table["per"] or not table["rows"]:
        raise FalkitError("pricing block needs `per:` and at least one price row", EXIT_USAGE)
    width = max(1, len(table["by"]))
    bad = [",".join(k) for k in table["rows"] if len(k) != width]
    if bad:
        raise FalkitError(f"pricing block: rows {bad} need {width} value(s), one per `by` argument", EXIT_USAGE)
    return table


def load(profile_dir: Path) -> dict | None:
    path = Path(profile_dir) / "prompting.md"
    return parse(path.read_text(encoding="utf-8")) if path.exists() else None


def _value(name: str, args: dict, input_schema: dict) -> Any:
    if name in args:
        return args[name]
    return ((input_schema.get("properties") or {}).get(name) or {}).get("default")


def _norm(v: Any) -> str:
    if isinstance(v, dict):
        return "x".join(str(v.get(k)) for k in ("width", "height"))
    return str(v).strip().lower()


def estimate(table: dict | None, args: dict, input_schema: dict) -> dict | None:
    """{usd, basis, checked} for one request, or {usd: None, basis: why}. None when there is no table."""
    if not table:
        return None
    key = [_norm(_value(b, args, input_schema)) for b in table["by"]] or ["*"]
    best, best_wild = None, None
    for row, price in table["rows"].items():
        cells = [c.lower() for c in row]
        if all(c == "*" or k in c.split("|") for c, k in zip(cells, key, strict=True)):
            wild = sum(c == "*" for c in cells)
            if best_wild is None or wild < best_wild:
                best, best_wild = (row, price), wild
    checked = table.get("checked")
    if not best:
        return {"usd": None, "basis": f"no pricing row for {dict(zip(table['by'], key, strict=False))}", "checked": checked}
    unit_price = best[1]
    col_note = ""
    if table.get("columns"):
        arg, _ = table["columns"]
        col = _norm(_value(arg, args, input_schema))
        if col not in unit_price:
            return {"usd": None, "basis": f"no price column for {arg}={col}", "checked": checked}
        unit_price = unit_price[col]
        col_note = f"{arg}={col}"
    qty = 1.0
    parts = []
    for c in table["count"]:
        m = _CHARS_RE.fullmatch(c)
        if m:  # text billed by length: chars(text)/1000 → thousands of characters
            text = str(_value(m.group(1), args, input_schema) or "")
            per = float(m.group(2) or 1)
            qty *= len(text) / per
            parts.append(f"{len(text)} chars" + (f"/{m.group(2)}" if m.group(2) else ""))
            continue
        v = _value(c, args, input_schema)
        num = re.match(r"^\s*(\d+(?:\.\d+)?)", str(v)) if v is not None else None
        if not num:
            return {"usd": None, "basis": f"{c} has no numeric value", "checked": checked}
        qty *= float(num.group(1))
        parts.append(f"{c}={num.group(1)}")
    usd = round(unit_price * qty, 5)
    sel = ", ".join([f"{b}={k}" for b, k in zip(table["by"], key, strict=False)] + ([col_note] if col_note else []))
    basis = f"${unit_price} per {table['per']}" + (f" ({sel})" if sel else "") + (f" × {' × '.join(parts)}" if parts else "")
    return {"usd": usd, "basis": basis, "checked": checked, "bound": table.get("bound")}


def total(estimates: list[dict | None]) -> dict | None:
    known = [e for e in estimates if e]
    if not known:
        return None
    if any(e["usd"] is None for e in known) or len(known) != len(estimates):
        return {"usd": None, "basis": "some requests can't be priced", "checked": known[0].get("checked")}
    return {"usd": round(sum(e["usd"] for e in known), 5), "basis": f"{len(known)} request(s)",
            "checked": known[0].get("checked"), "bound": known[0].get("bound")}


def age_days(table: dict) -> float | None:
    checked = table.get("checked")
    if not checked:
        return None
    try:
        return (time.time() - time.mktime(time.strptime(checked, "%Y-%m-%d"))) / 86400
    except ValueError:
        return None


def is_opaque(unit: str | None) -> bool:
    """A unit that says nothing about what a request costs ("$1 per unit", GPU seconds, tokens)."""
    u = (unit or "").lower()
    return not u or any(x in u for x in OPAQUE_UNITS)


def describe(est: dict | None) -> str:
    if not est:
        return "no researched pricing table (see prompting.md → Pricing)"
    if est["usd"] is None:
        return f"can't estimate: {est['basis']}"
    sign = "≥" if est.get("bound") == "lower" else "≈"
    extra = "; a lower bound: some costs aren't in the table" if sign == "≥" else ""
    return f"{sign} ${est['usd']:.4f} ({est['basis']}; prices checked {est.get('checked') or 'n/a'}{extra})"
