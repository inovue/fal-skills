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

from . import __version__, profiles
from .core import EXIT_USAGE, SKILL_DIR, FalkitError, read_json

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
        f"{verb[0].upper() + verb[1:]} with {name} ({prof['endpoint_id']}) on fal.ai, using researched prompt "
        f"templates, pinned defaults, a cost guard and pipeline-ready manifests. Use this whenever the user asks "
        f"for {name} or wants to {verb} and this model fits, including as a step chained after or before other "
        f"fal-* generation skills."
    )


def export(ref: str, dest_root: Path, name: str | None, force: bool) -> Path:
    src = profiles.find(ref)
    prof = read_json(src / "profile.json")
    skill_name = name or f"fal-{prof['slug']}"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", skill_name):
        raise FalkitError(f"Invalid skill name {skill_name!r} (lowercase letters, digits, hyphens)", EXIT_USAGE)
    dest = dest_root / skill_name
    if dest.exists():
        if not force:
            raise FalkitError(f"{dest} exists", EXIT_USAGE, hint="Pass --force to overwrite (re-vendors the runtime).")
        shutil.rmtree(dest)
    if prof.get("prompting_status") != "researched":
        from .core import log

        log("warning: this profile's prompting.md has not been researched yet — the exported skill will be weaker.")

    (dest / "scripts").mkdir(parents=True)
    shutil.copy2(SKILL_DIR / "scripts" / "fal.py", dest / "scripts" / "fal.py")
    shutil.copytree(
        SKILL_DIR / "scripts" / "falkit", dest / "scripts" / "falkit", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(src, dest / "profile", ignore=shutil.ignore_patterns("openapi.json"))
    (dest / "references").mkdir()
    for ref_file in ("pipelines.md", "auth.md", "troubleshooting.md"):
        shutil.copy2(SKILL_DIR / "references" / ref_file, dest / "references" / ref_file)
    (dest / "assets").mkdir()
    shutil.copy2(SKILL_DIR / "assets" / "prompting.template.md", dest / "assets" / "prompting.template.md")

    presets = read_json(src / "presets.json") if (src / "presets.json").exists() else {}
    tpl = (SKILL_DIR / "assets" / "exported-skill.template.md").read_text(encoding="utf-8")
    values = {
        "skill_name": skill_name,
        "description": _description(prof).replace('"', "'"),
        "display_name": prof.get("display_name") or prof["endpoint_id"],
        "endpoint_id": prof["endpoint_id"],
        "category": prof.get("category") or "unknown",
        "runtime_version": __version__,
        "presets": ", ".join(f"`{p}`" for p in presets) or "none yet",
        "defaults": _defaults_line(read_json(src / "defaults.json") if (src / "defaults.json").exists() else {}),
        "pricing": _pricing_line(prof.get("pricing")),
    }
    for k, v in values.items():
        tpl = tpl.replace("{{" + k + "}}", v)
    (dest / "SKILL.md").write_text(tpl, encoding="utf-8")
    (dest / "profile" / ".exported.json").write_text(
        json.dumps({"runtime_version": __version__, "source_profile": prof["slug"]}, indent=2) + "\n"
    )
    return dest


def _defaults_line(defaults: dict) -> str:
    if not defaults:
        return "the model's own defaults"
    return ", ".join(f"`{k}={json.dumps(v, ensure_ascii=False)}`" for k, v in defaults.items())


def _pricing_line(p: dict | None) -> str:
    if not p:
        return "unknown (the cost guard will ask before expensive runs)"
    return f"${p.get('unit_price')} per {p.get('unit')} (as of {str(p.get('fetched_at', ''))[:10]})"
