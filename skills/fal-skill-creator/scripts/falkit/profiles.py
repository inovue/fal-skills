"""Model profiles: everything needed to call one fal endpoint well.

A profile is data, not code — the runner is shared and tested once:

    <slug>/
      profile.json   identity, prompt field, pricing snapshot, research status
      schema.json    compact input/output JSON Schemas (refs inlined)
      openapi.json   raw upstream document, for jq spelunking
      defaults.json  pinned arguments merged under every call
      presets.json   named argument bundles ({"portrait": {...}})
      prompting.md   researched input guide: rules, inputs, parameters, ```template blocks, sources

`check()` holds prompting.md to a minimum standard, and a profile can only be
marked `researched` when it passes.

Lookup order: explicit path → <skill>/profiles (bundled in an exported workflow
skill) → $FAL_PROFILES_DIR, or else ./.fal/profiles (project) → ~/.fal-skills/profiles
(user). Earlier directories shadow later ones.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from datetime import date
from pathlib import Path
from typing import Any

from . import __version__, catalog, pricing, schema, templates
from .core import (
    EXIT_USAGE,
    SKILL_DIR,
    USER_AGENT,
    FalkitError,
    cache_dir,
    now_iso,
    read_json,
    user_home_dir,
    write_json,
)

PROFILE_FORMAT = "fal-profile@1"


def project_dir() -> Path:
    return Path(".fal") / "profiles"


def user_dir() -> Path:
    return user_home_dir() / "profiles"


def bundled_dir() -> Path:
    """Profiles shipped inside an exported workflow skill (absent in fal-skill-creator itself)."""
    return SKILL_DIR / "profiles"


def search_dirs() -> list[Path]:
    # A workflow skill's bundled profiles come first, so a same-named user profile can't change its behavior.
    bundled = [bundled_dir()] if bundled_dir().is_dir() else []
    if os.environ.get("FAL_PROFILES_DIR"):
        return bundled + [Path(os.environ["FAL_PROFILES_DIR"]).expanduser()]
    return bundled + [project_dir(), user_dir()]


def scope_dir(scope: str) -> Path:
    if os.environ.get("FAL_PROFILES_DIR"):
        return Path(os.environ["FAL_PROFILES_DIR"]).expanduser()
    return project_dir() if scope == "project" else user_dir()


def slugify(endpoint_id: str) -> str:
    parts = endpoint_id.split("/")
    if parts[0] in {"fal-ai", "fal"} and len(parts) > 1:
        parts = parts[1:]
    slug = "-".join(parts).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug[:64]


def find(ref: str) -> Path:
    p = Path(ref).expanduser()
    if (p / "profile.json").exists():
        return p
    for d in search_dirs():
        if (d / ref / "profile.json").exists():
            return d / ref
    # Allow referring to a profile by its endpoint id.
    for prof in list_all():
        if prof["endpoint_id"] == ref:
            return Path(prof["path"])
    raise FalkitError(
        f"Profile {ref!r} not found",
        EXIT_USAGE,
        hint="List profiles with `fal.py profile list`, or create one with `fal.py profile init <endpoint_id>`.",
    )


def load(ref: str) -> dict:
    d = find(ref)
    prof = read_json(d / "profile.json")
    prof["path"] = str(d)
    prof["schema"] = read_json(d / "schema.json")
    prof["defaults"] = read_json(d / "defaults.json") if (d / "defaults.json").exists() else {}
    prof["presets"] = read_json(d / "presets.json") if (d / "presets.json").exists() else {}
    return prof


def list_all() -> list[dict]:
    seen: set[str] = set()
    out = []
    for d in search_dirs():
        if not d.exists():
            continue
        for p in sorted(d.iterdir()):
            f = p / "profile.json"
            if not f.exists() or p.name in seen:
                continue
            seen.add(p.name)
            data = read_json(f)
            out.append(
                {
                    "slug": p.name,
                    "endpoint_id": data.get("endpoint_id"),
                    "category": data.get("category"),
                    "prompting_status": data.get("prompting_status"),
                    "path": str(p),
                }
            )
    return out


GUIDES_DIR = SKILL_DIR / "assets" / "guides"


def library_entry(endpoint_id: str) -> dict | None:
    """A bundled, researched guide for this endpoint (assets/guides/index.json), or None."""
    try:
        index = read_json(GUIDES_DIR / "index.json")
    except FileNotFoundError:
        return None
    entry = (index.get("guides") or {}).get(endpoint_id)
    if entry and (GUIDES_DIR / entry["file"]).exists():
        return entry
    return None


def init(endpoint_id: str, slug: str | None, scope: str, force: bool) -> Path:
    guide = library_entry(endpoint_id)
    slug = slug or (guide or {}).get("slug") or slugify(endpoint_id)
    dest = scope_dir(scope) / slug
    if (dest / "profile.json").exists() and not force:
        raise FalkitError(
            f"Profile {slug!r} already exists at {dest}",
            EXIT_USAGE,
            hint="Use `profile refresh` to update its schema, or --force to recreate it (keeps nothing).",
        )
    doc = schema.fetch_openapi(endpoint_id)
    compact = schema.compact(doc, endpoint_id)
    meta = catalog.get_model(endpoint_id) or {}
    price = catalog.get_prices([endpoint_id]).get(endpoint_id)

    dest.mkdir(parents=True, exist_ok=True)
    write_json(dest / "openapi.json", doc)
    write_json(dest / "schema.json", compact)
    write_json(dest / "defaults.json", schema.schema_defaults(compact["input"]))
    if not (dest / "presets.json").exists() or force:
        write_json(dest / "presets.json", {})
    profile = {
        "format": PROFILE_FORMAT,
        "slug": slug,
        "endpoint_id": endpoint_id,
        "display_name": meta.get("display_name") or endpoint_id,
        "category": compact.get("category") or meta.get("category"),
        "description": meta.get("description", ""),
        "license_type": meta.get("license_type"),
        "model_date": meta.get("date"),
        "documentation_url": compact["documentation_url"],
        "playground_url": compact["playground_url"],
        "prompt_field": schema.prompt_field(compact["input"]),
        "created_at": now_iso(),
        "schema_fetched_at": now_iso(),
        "runtime_version": __version__,
        "pricing": {**price, "fetched_at": now_iso()} if price else None,
        "prompting_status": "unresearched",
    }
    if guide:
        # A researched guide ships with the skill: start from it instead of a stub. It is only marked researched
        # if it still passes the check against this endpoint's live schema.
        shutil.copy2(GUIDES_DIR / guide["file"], dest / "prompting.md")
        if guide.get("presets") and (force or not read_json(dest / "presets.json")):
            write_json(dest / "presets.json", guide["presets"])
        profile["guide_source"] = f"bundled:{guide['file']}"
        profile["recommended_defaults"] = guide.get("recommend") or {}
        if profile["recommended_defaults"]:
            # Researched defaults (e.g. GPT Image quality=medium instead of fal's 4× more expensive `high`) apply at
            # once, so a run before A3 doesn't pay for the model's default. `profile set` changes them.
            write_json(dest / "defaults.json", {**read_json(dest / "defaults.json"), **profile["recommended_defaults"]})
        if guide.get("validated"):
            profile["validated_with"] = f"bundled: {guide['validated']}"
        write_json(dest / "profile.json", profile)
        report = check(str(dest))
        profile["prompting_status"] = "researched" if not report["errors"] else "stale"
        write_json(dest / "profile.json", profile)
        _stamp_header(dest / "prompting.md", profile["prompting_status"])
        return dest
    write_json(dest / "profile.json", profile)
    _write_prompting_stub(dest / "prompting.md", profile)
    return dest


# A starting `general` template per kind of output; research replaces it with the model's own structure.
_STUB_GENERAL = {
    "video": "{subject} {action}.[[ Setting: {setting}.]][[ Camera: {camera_move}.]][[ Style: {style}.]]",
    "speech": "{script}",
    "audio": "{genre_or_sound}, {mood}.[[ Instruments: {instruments_or_texture}.]][[ Tempo: {tempo}.]]",
    "3d": "{subject}, {material}.[[ Style: {style}.]]",
}
_STUB_RE = re.compile(r"```template general\n.*?\n```\n", re.S)


def _stub_kind(category: str, prompted: bool) -> str | None:
    if not prompted:
        return None
    c = category.lower()
    if "speech" in c and not c.startswith("speech-to"):
        return "speech"
    for kind in ("video", "3d", "audio"):
        if c.endswith(kind) or f"-{kind}" in c:
            return kind
    return "image"


def _write_prompting_stub(path: Path, profile: dict) -> None:
    tpl = (SKILL_DIR / "assets" / "prompting.template.md").read_text(encoding="utf-8")
    for k in ("endpoint_id", "display_name", "category", "documentation_url", "playground_url"):
        tpl = tpl.replace("{{" + k + "}}", str(profile.get(k) or ""))
    kind = _stub_kind(profile.get("category") or "", bool(profile.get("prompt_field")))
    if kind is None:  # no text input: templates don't apply, the guide is about inputs and parameters
        tpl = _STUB_RE.sub("", tpl).replace("When no specific template fits.\n", "(This model takes no text prompt.)\n")
    elif kind in _STUB_GENERAL:
        tpl = _STUB_RE.sub(lambda _m: f"```template general\n{_STUB_GENERAL[kind]}\n```\n", tpl)
    path.write_text(tpl, encoding="utf-8")


def _save_profile_json(d: Path, prof: dict) -> None:
    clean = {k: v for k, v in prof.items() if k not in {"path", "schema", "defaults", "presets"}}
    write_json(d / "profile.json", clean)


def set_defaults(ref: str, assignments: dict[str, Any], unset: list[str]) -> dict:
    from .core import set_path

    d = find(ref)
    defaults = read_json(d / "defaults.json") if (d / "defaults.json").exists() else {}
    for k, v in assignments.items():
        set_path(defaults, k, v)
    for k in unset:
        defaults.pop(k, None)
    compact = read_json(d / "schema.json")
    errors, warnings = schema.validate({**defaults}, {**compact["input"], "required": []})
    if errors:
        raise FalkitError("Defaults do not fit the schema:\n  " + "\n  ".join(errors), EXIT_USAGE)
    write_json(d / "defaults.json", defaults)
    return {"defaults": defaults, "warnings": warnings}


def set_preset(ref: str, name: str, assignments: dict[str, Any], delete: bool) -> dict:
    from .core import set_path

    d = find(ref)
    presets = read_json(d / "presets.json") if (d / "presets.json").exists() else {}
    if delete:
        presets.pop(name, None)
    else:
        bundle = presets.get(name, {})
        for k, v in assignments.items():
            set_path(bundle, k, v)
        presets[name] = bundle
    write_json(d / "presets.json", presets)
    return presets


def set_meta(ref: str, **fields: Any) -> dict:
    d = find(ref)
    prof = read_json(d / "profile.json")
    if fields.get("prompting_status") == "researched":
        report = check(str(d), online=True)
        if report["errors"]:
            raise FalkitError(
                "prompting.md isn't ready to be marked researched:\n  " + "\n  ".join(report["errors"]),
                EXIT_USAGE,
                hint="Fix it following references/prompt-research.md, then run this again. "
                "`fal.py profile check` shows the same report.",
            )
    for k, v in fields.items():
        prof[k] = v
    prof.pop("cost_guard", None)  # retired in 1.2
    _save_profile_json(d, prof)
    if "prompting_status" in fields:
        _stamp_header(d / "prompting.md", fields["prompting_status"])
    return prof


def _stamp_header(path: Path, status: str) -> None:
    """Keep prompting.md's header comment in step with profile.json."""
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^status:.*$", f"status: {status}", text, count=1, flags=re.M)
    if status == "researched":
        text = re.sub(r"^researched_at:[ \t]*$", f"researched_at: {date.today().isoformat()}", text, count=1, flags=re.M)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# prompting.md quality check
# ---------------------------------------------------------------------------
STALE_AFTER_DAYS = 180
_URL_RE = re.compile(r"https?://[^\s)>\]`'\"]+")
# Parameters through which the model rewrites or extends the prompt it's given. A researched prompt can be
# undone by these, so the guide has to say how to set them.
_REWRITE_RE = re.compile(r"expan|enhanc|optimi[sz]|rewrit|magic_prompt|auto_prompt|prompt_upsampl", re.I)
_VISUAL_RE = re.compile(r"image|video|3d", re.I)
_MIN_FIXED_LETTERS = 25


def _sections(text: str) -> dict[str, str]:
    """'## Heading' → body, with headings lower-cased and HTML comments removed."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    out: dict[str, str] = {}
    for m in re.finditer(r"^##[ \t]+(.+?)[ \t]*\n(.*?)(?=^##[ \t]+|\Z)", text, re.M | re.S):
        out[m.group(1).strip().lower()] = m.group(2)
    return out


def _section(sections: dict[str, str], *names: str) -> str | None:
    for heading, body in sections.items():
        if any(heading.startswith(n) for n in names):
            return body
    return None


def _bullets(body: str | None) -> list[str]:
    return re.findall(r"^[ \t]*(?:[-*]|\d+\.)[ \t]+(.+)$", body or "", re.M)


def url_status(url: str) -> int | None:
    """HTTP status of a source URL (cached for a day), or None when it couldn't be reached."""
    import httpx

    cache = cache_dir() / "url-status.json"
    try:
        seen = read_json(cache)
    except (FileNotFoundError, ValueError):
        seen = {}
    hit = seen.get(url)
    if hit and time.time() - hit["at"] < 86400:
        return hit["status"]
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": f"Mozilla/5.0 {USER_AGENT}"})
        status: int | None = r.status_code
    except httpx.HTTPError:
        status = None
    seen[url] = {"status": status, "at": time.time()}
    write_json(cache, seen)
    return status


def check(ref: str, online: bool = False) -> dict:
    """Is prompting.md good enough to steer this model? Errors block `researched`; warnings are advice.

    online=True also fetches every source URL: a guide can't cite pages that don't exist.
    """
    d = find(ref)
    prof = read_json(d / "profile.json")
    path = d / "prompting.md"
    errors: list[str] = []
    warnings: list[str] = []
    base = {"profile": prof.get("slug"), "path": str(path), "status": prof.get("prompting_status")}
    if not path.exists():
        return {**base, "errors": ["prompting.md is missing"], "warnings": [], "templates": {}, "pricing": None}
    text = path.read_text(encoding="utf-8")
    sections = _sections(text)
    input_schema = read_json(d / "schema.json")["input"]
    summary = schema.summarize(input_schema)
    media_inputs = [r["name"] for r in summary if r.get("media_input")]
    pfield = prof.get("prompt_field") or schema.prompt_field(input_schema)
    visual = bool(_VISUAL_RE.search(prof.get("category") or ""))

    if "Not researched yet" in text:
        errors.append("the 'Not researched yet' notice from the stub is still there")
    rules = _bullets(_section(sections, "key rules"))
    if len(rules) < 3:
        errors.append(f"'## Key rules' has {len(rules)} bullet(s); write 3–6 rules the agent applies every time")
    elif not any(re.search(r"\[S\d+\]", r) for r in rules):
        errors.append("no key rule cites a source like [S1]")

    found = templates.parse(text)
    if pfield and not found:
        errors.append("no templates: add at least one ```template <name> block (a `general` one at minimum)")
    props = input_schema.get("properties") or {}
    for name, body in found.items():
        for problem in templates.lint(body, set(props)):
            errors.append(f"template {name!r}: {problem}")
        letters = len(re.findall(r"[^\W\d_]", templates.fixed_text(body)))
        if not templates.slots(body):
            warnings.append(f"template {name!r} has no {{slots}}, so every request gets the same prompt")
        elif letters < _MIN_FIXED_LETTERS:
            msg = (f"template {name!r} is almost only slots; its fixed wording should carry the researched "
                   "structure (order, vocabulary, syntax), with slots only for what changes per request")
            (errors if visual else warnings).append(msg)

    if media_inputs:
        inputs = _section(sections, "inputs")
        if not inputs or not inputs.strip():
            errors.append(
                f"'## Inputs' is missing or empty; this model takes {', '.join(media_inputs)}: "
                "document formats, sizes, aspect ratios and how references are used"
            )
        else:
            missing = [m for m in media_inputs if m not in inputs]
            if missing:
                warnings.append(f"'## Inputs' doesn't mention {', '.join(missing)}")
    body_lower = text.lower()
    for r in summary:
        if r["name"] != pfield and _REWRITE_RE.search(r["name"]) and r["name"].lower() not in body_lower:
            errors.append(
                f"the model rewrites prompts through {r['name']!r} (default {r.get('default')!r}); "
                "say in the guide how to set it, since it changes what the model actually receives"
            )
    table_rows = [ln for ln in (_section(sections, "parameters") or "").splitlines() if ln.strip().startswith("|")]
    if len(table_rows) < 3:  # header, separator, then at least one row
        warnings.append("'## Parameters that matter' has no rows")

    try:
        price_table = pricing.parse(text)
    except FalkitError as e:
        errors.append(str(e))
        price_table = None
    unit = (prof.get("pricing") or {}).get("unit")
    if not price_table:
        msg = ("no ```pricing block: copy the price table from the fal model page "
               "(see references/prompt-research.md), because the API's unit price")
        if pricing.is_opaque(unit) or "character" in (unit or "").lower():
            errors.append(f"{msg} ('{unit or 'none'}') says nothing about what a request costs")
        else:
            warnings.append(f"{msg} is often only the cheapest tier")
    else:
        col_arg = [price_table["columns"][0]] if price_table.get("columns") else []
        counted = [pricing._CHARS_RE.fullmatch(c).group(1) if pricing._CHARS_RE.fullmatch(c) else c
                   for c in price_table["count"]]
        for b in price_table["by"] + counted + col_arg:
            if b not in (input_schema.get("properties") or {}):
                errors.append(f"pricing block names {b!r}, which is not a parameter of this model")
        age = pricing.age_days(price_table)
        if age is None:
            warnings.append("pricing block has no `checked: YYYY-MM-DD <url>` line")
        elif age > pricing.STALE_AFTER_DAYS:
            warnings.append(f"prices checked {int(age)} days ago; launch promos end and prices change, re-check the model page")

    urls = sorted(set(_URL_RE.findall(_section(sections, "sources") or "")))
    if not urls:
        errors.append("'## Sources' lists no URLs")
    else:
        if not any("fal.ai/models/" in u for u in urls):
            errors.append(f"cite fal's model page ({prof.get('playground_url') or 'https://fal.ai/models/<endpoint>'}): "
                          "it documents the parameters, limits and prices of the deployment you call")
        if len(urls) < 2:
            warnings.append("only one source; cross-check with the model maker's own guide")
        if online:
            for u in urls:
                st = url_status(u)
                if st in (404, 410) or (st is not None and 500 <= st < 600 and "fal.ai" in u):
                    errors.append(f"source doesn't exist ({st}): {u}")
                elif st is None or st >= 400:
                    warnings.append(f"couldn't verify source ({st or 'unreachable'}): {u}")

    m = re.search(r"^researched_at:[ \t]*(\d{4}-\d{2}-\d{2})", text, re.M)
    if m:
        age = (time.time() - time.mktime(time.strptime(m.group(1), "%Y-%m-%d"))) / 86400
        if age > STALE_AFTER_DAYS:
            warnings.append(f"researched {int(age)} days ago; check for a newer model version or guide")
    if not prof.get("validated_with"):
        what = "a template" if pfield else "it"
        warnings.append(f"not validated yet: run {what} once, check the result, then "
                        "`profile meta <slug> --validated-with <run_id>`")
    if len(text.splitlines()) > 200:
        warnings.append(f"{len(text.splitlines())} lines; it's read before every generation, so aim for under 150")
    return {
        **base,
        "errors": errors,
        "warnings": warnings,
        "templates": {name: templates.slots(body) for name, body in found.items()},
        "pricing": price_table and {k: price_table[k] for k in ("per", "count", "by", "columns", "checked")},
    }


def refresh(ref: str) -> dict:
    """Re-fetch schema + pricing; report what changed and which pinned defaults broke."""
    d = find(ref)
    prof = read_json(d / "profile.json")
    old = read_json(d / "schema.json")
    doc = schema.fetch_openapi(prof["endpoint_id"])
    new = schema.compact(doc, prof["endpoint_id"])
    old_props = set((old["input"].get("properties") or {}).keys())
    new_props = set((new["input"].get("properties") or {}).keys())
    defaults = read_json(d / "defaults.json") if (d / "defaults.json").exists() else {}
    errors, warnings = schema.validate(defaults, {**new["input"], "required": []})
    write_json(d / "openapi.json", doc)
    write_json(d / "schema.json", new)
    price = catalog.get_prices([prof["endpoint_id"]]).get(prof["endpoint_id"])
    if price:
        prof["pricing"] = {**price, "fetched_at": now_iso()}
    prof["schema_fetched_at"] = now_iso()
    prof["prompt_field"] = prof.get("prompt_field") or schema.prompt_field(new["input"])
    _save_profile_json(d, prof)
    return {
        "added_params": sorted(new_props - old_props),
        "removed_params": sorted(old_props - new_props),
        "required_changed": sorted(set(old["input"].get("required") or []) ^ set(new["input"].get("required") or [])),
        "defaults_errors": errors,
        "defaults_warnings": warnings,
        "pricing": prof.get("pricing"),
    }


def remove(ref: str) -> Path:
    d = find(ref)
    shutil.rmtree(d)
    return d
