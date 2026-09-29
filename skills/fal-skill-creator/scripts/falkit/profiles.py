"""Model profiles: everything needed to call one fal endpoint well.

A profile is data, not code — the runner is shared and tested once:

    <slug>/
      profile.json   identity, pricing snapshot, cost guard, research status
      schema.json    compact input/output JSON Schemas (refs inlined)
      openapi.json   raw upstream document, for jq spelunking
      defaults.json  pinned arguments merged under every call
      presets.json   named argument bundles ({"portrait": {...}})
      prompting.md   researched prompt guide + templates for this model

Lookup order: explicit path → <skill>/profiles (bundled in an exported workflow
skill) → $FAL_PROFILES_DIR, or else ./.fal/profiles (project) → ~/.fal-skills/profiles
(user). Earlier directories shadow later ones.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

from . import __version__, catalog, schema
from .core import EXIT_USAGE, SKILL_DIR, FalkitError, now_iso, read_json, user_home_dir, write_json

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


def init(endpoint_id: str, slug: str | None, scope: str, force: bool) -> Path:
    slug = slug or slugify(endpoint_id)
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
        "created_at": now_iso(),
        "schema_fetched_at": now_iso(),
        "runtime_version": __version__,
        "pricing": {**price, "fetched_at": now_iso()} if price else None,
        "cost_guard": {"max_usd": None},
        "prompting_status": "unresearched",
    }
    write_json(dest / "profile.json", profile)
    _write_prompting_stub(dest / "prompting.md", profile)
    return dest


def _write_prompting_stub(path: Path, profile: dict) -> None:
    tpl = (SKILL_DIR / "assets" / "prompting.template.md").read_text(encoding="utf-8")
    for k in ("endpoint_id", "display_name", "category", "documentation_url", "playground_url"):
        tpl = tpl.replace("{{" + k + "}}", str(profile.get(k) or ""))
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
    for k, v in fields.items():
        if k == "max_usd":
            prof.setdefault("cost_guard", {})["max_usd"] = v
        else:
            prof[k] = v
    _save_profile_json(d, prof)
    return prof


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
