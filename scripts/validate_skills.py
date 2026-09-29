"""Validate every skills/*/SKILL.md against the Agent Skills frontmatter rules.

Checks: required fields, name format and match with the directory, description length,
body length, and that every file referenced in backticks under references/ or assets/ exists.
"""

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ALLOWED = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def check(skill_md: Path) -> list[str]:
    errs = []
    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return [f"{skill_md}: missing YAML frontmatter"]
    fm, body = yaml.safe_load(m.group(1)), m.group(2)
    name, desc = fm.get("name", ""), fm.get("description", "")
    if not NAME_RE.match(name) or len(name) > 64:
        errs.append(f"name {name!r}: lowercase letters, digits and single hyphens, max 64 chars")
    if name != skill_md.parent.name:
        errs.append(f"name {name!r} must match directory {skill_md.parent.name!r}")
    if not desc or len(desc) > 1024:
        errs.append(f"description must be 1-1024 chars (got {len(desc)})")
    if len(fm.get("compatibility", "")) > 500:
        errs.append("compatibility must be <= 500 chars")
    extra = set(fm) - ALLOWED
    if extra:
        errs.append(f"unknown frontmatter keys: {sorted(extra)}")
    if len(body.splitlines()) > 500:
        errs.append(f"body is {len(body.splitlines())} lines; keep SKILL.md under 500 and move detail to references/")
    for ref in set(re.findall(r"`((?:references|assets|scripts)/[\w./-]+)`", body)):
        if not (skill_md.parent / ref).exists():
            errs.append(f"referenced file does not exist: {ref}")
    return [f"{skill_md.relative_to(ROOT)}: {e}" for e in errs]


def main() -> int:
    skills = sorted(ROOT.glob("skills/*/SKILL.md"))
    errors = [e for s in skills for e in check(s)]
    for e in errors:
        print(f"✗ {e}")
    print(f"{len(skills)} skill(s) checked, {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
