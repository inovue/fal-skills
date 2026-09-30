"""Export a profile as a standalone, self-contained skill.

The exported skill vendors a copy of this runtime, so it installs and runs on
its own (`npx skills add`, a plugin, or a plain copy into .claude/skills).
The runtime version is stamped so `fal.py export --force` can refresh it later.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import __version__, profiles, templates
from .core import EXIT_USAGE, SKILL_DIR, FalkitError, log, read_json

_CATEGORY_VERBS = {
    "text-to-image": "generate images from text",
    "image-to-image": "edit or transform images",
    "text-to-video": "generate videos from text",
    "image-to-video": "animate images into video",
    "video-to-video": "edit or transform videos",
    "text-to-audio": "generate audio or music from text",
    "text-to-speech": "synthesize speech from text",
    "audio-to-audio": "transform audio",
    "speech-to-text": "transcribe speech",
    "image-to-3d": "turn images into 3D models",
    "text-to-3d": "generate 3D models from text",
    "audio-to-video": "generate video driven by audio",
}


def _description(prof: dict) -> str:
    verb = _CATEGORY_VERBS.get(prof.get("category") or "", f"run {prof.get('category') or 'generation'} tasks")
    name = prof.get("display_name") or prof["endpoint_id"]
    return (
        f"{verb[0].upper() + verb[1:]} with {name} ({prof['endpoint_id']}) on fal.ai, using prompt templates and "
        f"input rules researched from the model's official guides, pinned defaults, and pipeline-ready manifests. "
        f"Use this whenever the user asks for {name} or wants to {verb} and this model fits, including as a step "
        f"chained after or before other fal-* generation skills."
    )


RUNTIME_FILES = ("fal.py", "falkit")
REFERENCE_FILES = ("pipelines.md", "auth.md", "troubleshooting.md")


def prepare_dest(dest_root: Path, skill_name: str, force: bool) -> Path:
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", skill_name) or len(skill_name) > 64:
        raise FalkitError(f"Invalid skill name {skill_name!r} (lowercase letters, digits, single hyphens)", EXIT_USAGE)
    dest = dest_root / skill_name
    if dest.exists():
        if not force:
            raise FalkitError(f"{dest} exists", EXIT_USAGE, hint="Pass --force to overwrite (re-vendors the runtime).")
        shutil.rmtree(dest)
    return dest


def vendor_runtime(dest: Path) -> None:
    """Copy the runtime and the shared references, so the exported skill runs on its own."""
    (dest / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(SKILL_DIR / "scripts" / "fal.py", dest / "scripts" / "fal.py")
    shutil.copytree(
        SKILL_DIR / "scripts" / "falkit", dest / "scripts" / "falkit", ignore=shutil.ignore_patterns("__pycache__")
    )
    (dest / "references").mkdir(exist_ok=True)
    for ref_file in REFERENCE_FILES:
        shutil.copy2(SKILL_DIR / "references" / ref_file, dest / "references" / ref_file)


def render(template: str, values: dict[str, str]) -> str:
    for k, v in values.items():
        template = template.replace("{{" + k + "}}", v)
    return template


def export(ref: str, dest_root: Path, name: str | None, force: bool, description: str | None = None) -> Path:
    src = profiles.find(ref)
    prof = read_json(src / "profile.json")
    report = profiles.check(str(src))
    if prof.get("prompting_status") != "researched" or report["errors"]:
        raise FalkitError(
            f"Profile {prof['slug']!r} isn't researched, so the exported skill would prompt the model blind",
            EXIT_USAGE,
            hint="Research prompting.md (SKILL.md A4), pass `fal.py profile check`, and mark it researched first.",
        )
    if description is not None and not 0 < len(description) <= 1024:
        raise FalkitError("--description must be 1-1024 characters", EXIT_USAGE)
    dest = prepare_dest(dest_root, name or f"fal-{prof['slug']}", force)
    skill_name = dest.name
    for w in report["warnings"]:
        log(f"warning: prompting.md: {w}")

    vendor_runtime(dest)
    shutil.copytree(src, dest / "profile", ignore=shutil.ignore_patterns("openapi.json"))
    (dest / "assets").mkdir()
    shutil.copy2(SKILL_DIR / "assets" / "prompting.template.md", dest / "assets" / "prompting.template.md")

    presets = read_json(src / "presets.json") if (src / "presets.json").exists() else {}
    tpl = (SKILL_DIR / "assets" / "exported-skill.template.md").read_text(encoding="utf-8")
    values = {
        "skill_name": skill_name,
        "description": " ".join((description or _description(prof)).split()).replace('"', "'"),
        "display_name": prof.get("display_name") or prof["endpoint_id"],
        "endpoint_id": prof["endpoint_id"],
        "category": prof.get("category") or "unknown",
        "runtime_version": __version__,
        "presets": ", ".join(f"`{p}`" for p in presets) or "none yet",
        "templates": _templates_block(src / "prompting.md"),
        "defaults": _defaults_line(read_json(src / "defaults.json") if (src / "defaults.json").exists() else {}),
        "pricing": _pricing_line(prof.get("pricing")),
    }
    (dest / "SKILL.md").write_text(render(tpl, values), encoding="utf-8")
    (dest / "profile" / ".exported.json").write_text(
        json.dumps({"runtime_version": __version__, "source_profile": prof["slug"]}, indent=2) + "\n"
    )
    return dest


def _templates_block(path: Path) -> str:
    found = templates.parse(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not found:
        return "- (none: write the prompt by hand following `profile/prompting.md`)"
    return "\n".join(f"- `{n}`: {templates.describe(b)}" for n, b in found.items())


def _defaults_line(defaults: dict) -> str:
    if not defaults:
        return "the model's own defaults"
    return ", ".join(f"`{k}={json.dumps(v, ensure_ascii=False)}`" for k, v in defaults.items())


def _pricing_line(p: dict | None) -> str:
    if not p:
        return "unknown (check https://fal.ai/pricing before expensive runs)"
    return f"${p.get('unit_price')} per {p.get('unit')} (as of {str(p.get('fetched_at', ''))[:10]})"
