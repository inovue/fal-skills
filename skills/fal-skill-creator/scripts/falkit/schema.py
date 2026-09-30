"""OpenAPI → compact, self-contained JSON Schemas for a fal endpoint.

fal publishes a queue OpenAPI document per endpoint. We keep the raw document
for reference, and derive a compact `schema.json` with all `$ref`s inlined and
`anyOf [X, null]` collapsed — small enough to read in context, and directly
usable for local validation before spending money on a request.
"""

from __future__ import annotations

import copy
from typing import Any

from jsonschema import Draft202012Validator

from .core import EXIT_USAGE, FalkitError, http_json, truncate

OPENAPI_URL = "https://fal.ai/api/openapi/queue/openapi.json"
_DROP_KEYS = {"title"}
_MAX_DESC = 400
_MAX_EXAMPLE = 400


def fetch_openapi(endpoint_id: str) -> dict:
    doc = http_json("GET", OPENAPI_URL, params={"endpoint_id": endpoint_id})
    if not isinstance(doc, dict) or "paths" not in doc:
        raise FalkitError(
            f"No OpenAPI schema for {endpoint_id!r}",
            EXIT_USAGE,
            hint="Check the endpoint id with `fal.py models search`.",
        )
    return doc


def _resolve(node: Any, components: dict, stack: tuple[str, ...] = ()) -> Any:
    if isinstance(node, list):
        return [_resolve(n, components, stack) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        if name in stack:
            return {"type": "object", "description": f"(recursive {name})"}
        target = _resolve(copy.deepcopy(components.get(name, {})), components, stack + (name,))
        siblings = {k: v for k, v in node.items() if k != "$ref"}
        return {**target, **_resolve(siblings, components, stack)}
    out: dict[str, Any] = {}
    for k, v in node.items():
        if k in _DROP_KEYS and not isinstance(v, dict):
            continue
        if k == "description" and isinstance(v, str):
            v = truncate(" ".join(v.split()), _MAX_DESC)
        elif k == "examples" and isinstance(v, list):
            v = [truncate(v[0], _MAX_EXAMPLE) if isinstance(v[0], str) else v[0]] if v else v
        elif k == "properties" and isinstance(v, dict):
            v = {pk: _resolve(pv, components, stack) for pk, pv in v.items()}
            out[k] = v
            continue
        out[k] = _resolve(v, components, stack)
    return _collapse_nullable(out)


def _collapse_nullable(node: dict) -> dict:
    """anyOf [ {type: X}, {type: null} ] → type: [X, null]; keeps other anyOfs intact."""
    alts = node.get("anyOf")
    if not isinstance(alts, list) or len(alts) != 2:
        return node
    non_null = [a for a in alts if a != {"type": "null"}]
    if len(non_null) != 1 or len(alts) - len(non_null) != 1:
        return node
    other = non_null[0]
    merged = {k: v for k, v in node.items() if k != "anyOf"}
    for k, v in other.items():
        merged.setdefault(k, v)
    if isinstance(other.get("type"), str):
        merged["type"] = [other["type"], "null"]
    return merged


def compact(doc: dict, endpoint_id: str) -> dict:
    components = (doc.get("components") or {}).get("schemas") or {}
    paths = doc.get("paths") or {}
    post_path = "/" + endpoint_id if "post" in paths.get("/" + endpoint_id, {}) else None
    if not post_path:
        post_path = next((p for p, v in paths.items() if "post" in v and "/requests/" not in p), None)
    if not post_path:
        raise FalkitError(f"OpenAPI for {endpoint_id} has no submit (POST) path", EXIT_USAGE)
    body = paths[post_path]["post"].get("requestBody", {})
    in_schema = body.get("content", {}).get("application/json", {}).get("schema", {})
    result_path = next((p for p in paths if p.endswith("/requests/{request_id}")), None)
    out_schema: dict = {}
    if result_path:
        out_schema = (
            paths[result_path]
            .get("get", {})
            .get("responses", {})
            .get("200", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema", {})
        )
    meta = (doc.get("info") or {}).get("x-fal-metadata") or {}
    return {
        "endpoint_id": endpoint_id,
        "category": meta.get("category"),
        "documentation_url": meta.get("documentationUrl") or f"https://fal.ai/models/{endpoint_id}/api",
        "playground_url": meta.get("playgroundUrl") or f"https://fal.ai/models/{endpoint_id}",
        "input": _resolve(in_schema, components),
        "output": _resolve(out_schema, components),
    }


# ---------------------------------------------------------------------------
# Introspection used by summaries, cost estimates and pipeline auto-wiring
# ---------------------------------------------------------------------------
def _types(prop: dict) -> list[str]:
    t = prop.get("type")
    if isinstance(t, list):
        return [x for x in t if x != "null"]
    if isinstance(t, str):
        return [t]
    alts = prop.get("anyOf") or prop.get("oneOf") or []
    return sorted({x for a in alts for x in _types(a)})


def ordered_properties(input_schema: dict) -> list[tuple[str, dict]]:
    props = input_schema.get("properties") or {}
    order = input_schema.get("x-fal-order-properties") or []
    names = [n for n in order if n in props] + [n for n in props if n not in order]
    return [(n, props[n]) for n in names]


def media_kind_of_field(name: str, prop: dict | None = None) -> str | None:
    """Guess which media kind a URL-ish input field wants (image/video/audio/any)."""
    n = name.lower()
    urlish = n.endswith(("_url", "_urls", "_uri", "_file", "_files")) or n in {"image", "video", "audio", "images"}
    if prop and not urlish:
        fmt = prop.get("format") or ((prop.get("items") or {}).get("format"))
        urlish = fmt in {"uri", "url", "binary"}
    if not urlish:
        return None
    # An explicit medium in the name wins over generic words: `reference_video_urls` is video, not image,
    # even though "reference" usually means a reference image.
    for kind, needles in (
        ("image", ("image", "photo", "mask", "logo")),
        ("video", ("video", "clip", "footage")),
        ("audio", ("audio", "voice", "speech", "music", "sound", "song")),
        ("3d", ("mesh", "glb", "model_3d", "3d")),
        ("image", ("face", "style", "reference", "frame")),
    ):
        if any(x in n for x in needles):
            return kind
    return "any"


def is_list_field(prop: dict) -> bool:
    return "array" in _types(prop)


# Where a model takes its main text input. Most use `prompt`; speech and music models often don't.
_PROMPT_FIELDS = ("prompt", "text", "gen_text", "text_prompt", "script", "lyrics", "input")


def prompt_field(input_schema: dict) -> str | None:
    """The string field that `--prompt` and `--template` fill, or None when the model takes no text."""
    props = input_schema.get("properties") or {}
    for name in _PROMPT_FIELDS:
        if name in props and "string" in (_types(props[name]) or ["string"]):
            return name
    return None


def summarize(input_schema: dict) -> list[dict]:
    """One row per parameter — what the agent shows the user when choosing defaults."""
    required = set(input_schema.get("required") or [])
    rows = []
    for name, prop in ordered_properties(input_schema):
        row: dict[str, Any] = {
            "name": name,
            "type": "|".join(_types(prop)) or "any",
            "required": name in required,
        }
        for k in ("default", "enum", "minimum", "maximum"):
            if k in prop:
                row[k] = prop[k]
        if "enum" not in row:  # e.g. image_size: anyOf [ImageSize object, enum of presets]
            alt_enums = [e for a in (prop.get("anyOf") or []) for e in (a.get("enum") or [])]
            if alt_enums:
                row["enum"] = alt_enums
        if prop.get("description"):
            row["description"] = truncate(prop["description"], 160)
        kind = media_kind_of_field(name, prop)
        if kind:
            row["media_input"] = kind
        rows.append(row)
    return rows


def format_summary(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        bits = [r["type"]]
        if r["required"]:
            bits.append("REQUIRED")
        if "default" in r:
            bits.append(f"default={r['default']!r}")
        if "enum" in r:
            bits.append("one of " + ", ".join(map(str, r["enum"])))
        if "minimum" in r or "maximum" in r:
            bits.append(f"range {r.get('minimum', '')}..{r.get('maximum', '')}")
        if "media_input" in r:
            bits.append(f"media:{r['media_input']}")
        lines.append(
            f"- {r['name']} ({'; '.join(bits)})" + (f"\n    {r['description']}" if r.get("description") else "")
        )
    return "\n".join(lines)


def coerce_cli_value(name: str, value: Any, input_schema: dict) -> Any:
    """Fix JSON-parsing surprises from --set: duration=10 → "10" when the schema wants a string."""
    prop = (input_schema.get("properties") or {}).get(name)
    if not prop:
        return value
    types = set(_types(prop)) | {t for a in (prop.get("anyOf") or []) for t in _types(a)}
    if isinstance(value, (bool, int, float)) and "string" in types and not types & {"number", "integer", "boolean"}:
        return str(value).lower() if isinstance(value, bool) else str(value)
    if isinstance(value, str) and types and "string" not in types:
        if types & {"integer", "number"}:
            try:
                return int(value) if "integer" in types and value.lstrip("-").isdigit() else float(value)
            except ValueError:
                return value
    return value


def schema_defaults(input_schema: dict) -> dict:
    """Defaults worth pinning in a profile (reproducibility across upstream default changes).

    Skips seeds (pinning one kills variety), sync_mode (we always want URLs
    back, not base64 blobs in the result), and the prompt field (a default
    prompt would silently stand in for a missing one).
    """
    out = {}
    skip = {"seed", "sync_mode", prompt_field(input_schema)}
    for name, prop in ordered_properties(input_schema):
        if name in skip or "default" not in prop or prop["default"] is None:
            continue
        out[name] = prop["default"]
    return out


def validate(arguments: dict, input_schema: dict) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Unknown keys are warnings — usually a typo."""
    errors = []
    validator = Draft202012Validator(input_schema)
    for err in sorted(validator.iter_errors(arguments), key=lambda e: list(e.path)):
        where = ".".join(str(p) for p in err.path) or "(root)"
        errors.append(f"{where}: {err.message}")
    known = set((input_schema.get("properties") or {}).keys())
    warnings = [f"unknown parameter {k!r} (not in schema)" for k in arguments if known and k not in known]
    return errors, warnings
