"""Workflows: several models plus local processing, packaged as one skill.

A workflow is data, like a profile. It doesn't hard-code endpoints; each fal
step names a profile, so a model upgrade means re-pointing one profile:

    <name>/
      workflow.json   steps (fal / local / review), per-step settings, cost limit
      WORKFLOW.md     what the agent does at each step: prompt templates, checks
      scripts/        local processing used by `local` steps (split, crop, ffmpeg…)

The agent runs the steps one at a time (`fal workflow plan` prints the next
command) and looks at each intermediate result before paying for the next.
`fal workflow export` bundles the workflow, its profiles, its scripts and the
runtime into one standalone skill.

Lookup order: <skill dir> itself (an exported workflow skill) → ./.fal/workflows
(project) → ~/.fal-skills/workflows (user).
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from . import __version__, cost, profiles, runner
from .core import EXIT_USAGE, SKILL_DIR, FalkitError, log, now_iso, read_json, user_home_dir, write_json
from .export import RUNTIME_FILES, prepare_dest, render, vendor_runtime

WORKFLOW_FORMAT = "fal-workflow@1"
STEP_TYPES = ("fal", "local", "review")
_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_PLACEHOLDER_RE = re.compile(r"\{(in|files):([a-z0-9-]+)(?:#([\w.*-]+))?\}")
EXAMPLES_DIR = SKILL_DIR / "assets" / "workflows"


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------
def project_dir() -> Path:
    return Path(".fal") / "workflows"


def user_dir() -> Path:
    return user_home_dir() / "workflows"


def search_dirs() -> list[Path]:
    return [project_dir(), user_dir()]


def examples() -> list[str]:
    return sorted(p.name for p in EXAMPLES_DIR.iterdir() if (p / "workflow.json").exists()) if EXAMPLES_DIR.is_dir() else []


def find(ref: str | None) -> Path:
    """A path, a workflow name, or None for the workflow this exported skill contains."""
    if ref is None:
        if (SKILL_DIR / "workflow.json").exists():
            return SKILL_DIR
        raise FalkitError("Name a workflow", EXIT_USAGE, hint="List them with `fal.py workflow list`.")
    p = Path(ref).expanduser()
    if (p / "workflow.json").exists():
        return p
    if (SKILL_DIR / "workflow.json").exists() and read_json(SKILL_DIR / "workflow.json").get("name") == ref:
        return SKILL_DIR
    for d in search_dirs():
        if (d / ref / "workflow.json").exists():
            return d / ref
    raise FalkitError(
        f"Workflow {ref!r} not found",
        EXIT_USAGE,
        hint="List workflows with `fal.py workflow list`, or create one with `fal.py workflow init <name>`.",
    )


def load(ref: str | None) -> dict:
    d = find(ref)
    wf = read_json(d / "workflow.json")
    wf["path"] = str(d)
    return wf


def list_all() -> list[dict]:
    seen: set[str] = set()
    out = []
    for d in search_dirs():
        if not d.exists():
            continue
        for p in sorted(d.iterdir()):
            if not (p / "workflow.json").exists() or p.name in seen:
                continue
            seen.add(p.name)
            wf = read_json(p / "workflow.json")
            out.append({"name": p.name, "steps": [s.get("id") for s in wf.get("steps", [])], "path": str(p)})
    return out


def init(name: str, scope: str, example: str | None, force: bool) -> Path:
    if not _ID_RE.match(name) or len(name) > 60:
        raise FalkitError(f"Invalid workflow name {name!r} (lowercase letters, digits, single hyphens)", EXIT_USAGE)
    dest = (project_dir() if scope == "project" else user_dir()) / name
    if dest.exists():
        if not force:
            raise FalkitError(f"Workflow {name!r} already exists at {dest}", EXIT_USAGE, hint="Pass --force to replace it.")
        shutil.rmtree(dest)
    if example:
        src = EXAMPLES_DIR / example
        if not (src / "workflow.json").exists():
            raise FalkitError(f"Unknown example {example!r}", EXIT_USAGE, hint=f"Examples: {', '.join(examples())}")
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
        wf = read_json(dest / "workflow.json")
    else:
        dest.mkdir(parents=True)
        (dest / "scripts").mkdir()
        wf = {
            "format": WORKFLOW_FORMAT,
            "name": name,
            "description": "",
            "max_usd": 1.0,
            "steps": [],
        }
        tpl = (SKILL_DIR / "assets" / "workflow.template.md").read_text(encoding="utf-8")
        (dest / "WORKFLOW.md").write_text(render(tpl, {"name": name}), encoding="utf-8")
    wf.update(name=name, created_at=now_iso(), runtime_version=__version__)
    write_json(dest / "workflow.json", wf)
    return dest


# ---------------------------------------------------------------------------
# Check: structure, profiles, scripts, and the cost of one full run
# ---------------------------------------------------------------------------
def _profile_or_none(slug: str) -> dict | None:
    try:
        return profiles.load(slug)
    except FalkitError:
        return None


def _step_estimate(step: dict, prof: dict) -> dict:
    args = dict(prof.get("defaults") or {})
    if step.get("preset"):
        args.update((prof.get("presets") or {}).get(step["preset"]) or {})
    args.update(step.get("set") or {})
    est = cost.estimate(prof.get("pricing"), args, prof["schema"]["input"])
    count = int(step.get("count") or 1)
    if est.get("usd") is not None and count > 1:
        est = {**est, "usd": round(est["usd"] * count, 4), "count": count}
    return est


def check(ref: str | None) -> dict:
    wf = load(ref)
    wdir = Path(wf["path"])
    errors: list[str] = []
    warnings: list[str] = []
    if wf.get("format") != WORKFLOW_FORMAT:
        errors.append(f"format must be {WORKFLOW_FORMAT!r}")
    desc = wf.get("description") or ""
    if not desc:
        errors.append("description is empty (it becomes the exported skill's trigger description)")
    elif len(desc) > 1024:
        errors.append(f"description is {len(desc)} chars; the limit is 1024")
    steps = wf.get("steps") or []
    if not steps:
        errors.append("no steps")
    seen: list[str] = []
    estimates: dict[str, dict] = {}
    for i, s in enumerate(steps):
        sid = s.get("id") or f"#{i}"
        where = f"step {sid}"
        if not _ID_RE.match(str(s.get("id") or "")):
            errors.append(f"{where}: id must be lowercase letters, digits and single hyphens")
        if sid in seen:
            errors.append(f"{where}: duplicate id")
        if s.get("type") not in STEP_TYPES:
            errors.append(f"{where}: type must be one of {', '.join(STEP_TYPES)}")
        for dep in s.get("from") or []:
            if dep not in seen:
                errors.append(f"{where}: 'from' names {dep!r}, which is not an earlier step")
            elif next(x for x in steps if x.get("id") == dep).get("type") == "review":
                errors.append(f"{where}: 'from' names review step {dep!r}, which has no outputs")
        if s.get("type") == "fal":
            slug = s.get("profile")
            prof = _profile_or_none(slug) if slug else None
            if not slug:
                errors.append(f"{where}: fal steps need a 'profile'")
            elif not prof:
                hint = f" — create it: fal profile init {s['endpoint_hint']} --slug {slug}" if s.get("endpoint_hint") else ""
                errors.append(f"{where}: profile {slug!r} not found{hint}")
            else:
                if prof.get("prompting_status") != "researched" and s.get("prompted", True):
                    warnings.append(f"{where}: profile {slug!r} prompting is {prof.get('prompting_status')}")
                if s.get("preset") and s["preset"] not in (prof.get("presets") or {}):
                    errors.append(f"{where}: preset {s['preset']!r} not in profile {slug!r}")
                estimates[sid] = _step_estimate(s, prof)
        elif s.get("type") == "local":
            if not s.get("command"):
                errors.append(f"{where}: local steps need a 'command'")
            for script in re.findall(r"scripts/[\w./-]+", s.get("command") or ""):
                if not (wdir / script).exists():
                    errors.append(f"{where}: {script} does not exist in the workflow")
            for m in _PLACEHOLDER_RE.finditer(s.get("command") or ""):
                if m.group(2) not in seen:
                    errors.append(f"{where}: {m.group(0)} refers to a step that doesn't run earlier")
        seen.append(sid)
    if not (wdir / "WORKFLOW.md").exists():
        errors.append("WORKFLOW.md is missing")
    fal_steps = [s.get("id") for s in steps if s.get("type") == "fal"]
    known = [e["usd"] for e in estimates.values() if e.get("usd") is not None]
    unknown = [sid for sid in fal_steps if (estimates.get(sid) or {}).get("usd") is None]
    known_usd = round(sum(known), 4)
    limit = wf.get("max_usd")
    if limit is not None and known_usd > limit:
        warnings.append(f"one full run is estimated at ${known_usd:.4f}, above the workflow's max_usd ${limit}")
    for sid in unknown:
        if sid in estimates:
            reason = estimates[sid].get("reason") or "no quantity for this pricing unit"
            warnings.append(f"step {sid}: cost can't be estimated ({reason}); the cost guard decides at run time")
    return {
        "name": wf.get("name"),
        "path": str(wdir),
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "cost_per_run": {
            "usd": known_usd if not unknown else None,
            "known_usd": known_usd,
            "unknown_steps": unknown,
            "steps": estimates,
        },
    }


# ---------------------------------------------------------------------------
# Plan: the concrete command for each step, with earlier outputs resolved
# ---------------------------------------------------------------------------
def step_label(wf: dict, step_id: str) -> str:
    return f"{wf['name']}.{step_id}"


def _quote(s: str) -> str:
    return s if re.fullmatch(r"[\w./:@%+=,-]+", s) else "'" + s.replace("'", "'\"'\"'") + "'"


def _latest(wf: dict, sid: str, out_root: Path) -> tuple[Path, dict] | None:
    try:
        mp, manifest = runner.load_manifest(f"label:{step_label(wf, sid)}", out_root)
    except FalkitError:
        return None
    return mp.resolve(), manifest


def plan(ref: str | None, out_root: Path) -> dict:
    """Commands for every step, with earlier outputs filled in.

    A step counts as done only when its latest run was made from the latest run
    of each step it depends on. Rerunning an early step (a new request, or a
    retry) therefore marks everything after it as pending again, and placeholders
    never resolve to files from an older pass.
    """
    wf = load(ref)
    wdir = Path(wf["path"])
    types = {s["id"]: s.get("type") for s in wf.get("steps") or []}
    current: dict[str, dict] = {}  # step id → manifest of its run in the current pass
    rows = []
    for s in wf.get("steps") or []:
        sid = s["id"]
        label = step_label(wf, sid)
        deps = [d for d in s.get("from") or [] if types.get(d) != "review"]
        row: dict[str, Any] = {"id": sid, "type": s.get("type"), "purpose": s.get("purpose"), "label": label}
        latest = _latest(wf, sid, out_root) if s.get("type") != "review" else None
        row["done"] = None
        if latest:
            parents = {Path(p).resolve() for p in latest[1].get("parents") or []}
            fresh = all(d in current and Path(current[d]["_path"]) in parents for d in deps)
            if fresh:
                current[sid] = {**latest[1], "_path": str(latest[0])}
                row["done"] = {"run_id": latest[1]["run_id"], "run_dir": latest[1].get("run_dir")}
        if s.get("type") == "fal":
            parts = ["fal", "run", "-p", s["profile"]]
            if s.get("preset"):
                parts += ["--preset", s["preset"]]
            for k, v in (s.get("set") or {}).items():
                parts += ["--set", f"{k}={json.dumps(v) if not isinstance(v, str) else v}"]
            for dep in deps:
                parts += ["--from", f"label:{step_label(wf, dep)}"]
            if s.get("prompted", True):
                parts += ["--prompt", "<prompt from WORKFLOW.md>"]
            if int(s.get("count") or 1) > 1:
                row["note"] = f"run {s['count']} variations: --batch with {s['count']} lines, or repeat with new seeds"
            parts += ["--label", label]
            row["command"] = " ".join(_quote(p) if not p.startswith("<") else f'"{p}"' for p in parts)
            waiting = [d for d in deps if d not in current]
            if waiting:
                row["blocked_by"] = waiting
        elif s.get("type") == "local":
            work = (out_root / "_work" / wf["name"] / sid).resolve()
            unresolved: list[str] = []

            def fill(m: re.Match, unresolved: list[str] = unresolved) -> str:
                kind, dep, sel = m.groups()
                manifest = current.get(dep)
                if not manifest:
                    unresolved.append(dep)
                    return f"<{kind} of step {dep}>"
                outs = manifest.get("outputs") or []
                if sel and sel != "*":
                    outs = [o for o in outs if o.get("kind") == sel or o.get("field") == sel]
                paths = [o["local_path"] for o in outs if o.get("local_path")]
                if not paths:
                    unresolved.append(dep)
                    return f"<no local files in step {dep}>"
                return _quote(paths[0]) if kind == "in" else " ".join(_quote(p) for p in paths)

            cmd = s["command"].replace("{skill}", str(wdir)).replace("{out}", str(work))
            cmd = _PLACEHOLDER_RE.sub(fill, cmd)
            parents = " ".join(f"--parent label:{step_label(wf, d)}" for d in deps)
            row["command"] = cmd
            row["then"] = f"fal ingest {_quote(str(work))} --move --label {label}" + (f" {parents}" if parents else "")
            row["work_dir"] = str(work)
            waiting = sorted(set(unresolved) | {d for d in deps if d not in current})
            if waiting:
                row["blocked_by"] = waiting
        else:
            row["command"] = None
        if s.get("checkpoint", s.get("type") in ("fal", "review")):
            row["checkpoint"] = s.get("check") or "look at this step's output (and show the user) before continuing"
        rows.append(row)
    nxt = next((r["id"] for r in rows if not r["done"] and r["type"] != "review"), None)
    return {
        "name": wf["name"],
        "path": str(wdir),
        "next": nxt,
        "note": None if nxt else "every step has run; for a new request, start again at the first step",
        "steps": rows,
    }


# ---------------------------------------------------------------------------
# Export: workflow + its profiles + scripts + runtime → one standalone skill
# ---------------------------------------------------------------------------
def export(ref: str | None, dest_root: Path, name: str | None, force: bool) -> Path:
    report = check(ref)
    if not report["ok"]:
        raise FalkitError(
            "Workflow has problems:\n  " + "\n  ".join(report["errors"]),
            EXIT_USAGE,
            hint="Fix them, then rerun `fal.py workflow check`.",
        )
    for w in report["warnings"]:
        log(f"warning: {w}")
    wf = load(ref)
    src = Path(wf["path"])
    scripts = sorted(p.name for p in (src / "scripts").iterdir()) if (src / "scripts").is_dir() else []
    clash = set(scripts) & set(RUNTIME_FILES)
    if clash:
        raise FalkitError(f"Workflow scripts clash with the runtime: {', '.join(sorted(clash))}", EXIT_USAGE)
    dest = prepare_dest(dest_root, name or f"fal-{wf['name']}", force)
    vendor_runtime(dest)
    for item in scripts:
        s = src / "scripts" / item
        (shutil.copytree if s.is_dir() else shutil.copy2)(s, dest / "scripts" / item)
    slugs = sorted({s["profile"] for s in wf["steps"] if s.get("type") == "fal"})
    for slug in slugs:
        shutil.copytree(
            profiles.find(slug), dest / "profiles" / slug, ignore=shutil.ignore_patterns("openapi.json"), dirs_exist_ok=True
        )
    clean = {k: v for k, v in wf.items() if k != "path"}
    write_json(dest / "workflow.json", clean)

    body = (src / "WORKFLOW.md").read_text(encoding="utf-8")
    tpl = (SKILL_DIR / "assets" / "workflow-skill.template.md").read_text(encoding="utf-8")
    steps_md = "\n".join(
        f"{i}. `{s['id']}` ({s['type']}"
        + (f", profile `{s['profile']}`" if s.get("profile") else "")
        + f"): {s.get('purpose') or ''}"
        for i, s in enumerate(wf["steps"], 1)
    )
    c = report["cost_per_run"]
    values = {
        "skill_name": dest.name,
        "description": wf["description"].replace('"', "'"),
        "workflow_name": wf["name"],
        "runtime_version": __version__,
        "steps": steps_md,
        "cost": f"about ${c['known_usd']:.2f}"
        + (f" plus GPU-time or unpriced steps ({', '.join(c['unknown_steps'])})" if c["unknown_steps"] else ""),
        "profiles": ", ".join(f"`{s}`" for s in slugs) or "none",
        "body": body.strip(),
    }
    (dest / "SKILL.md").write_text(render(tpl, values), encoding="utf-8")
    (dest / ".exported.json").write_text(
        json.dumps({"runtime_version": __version__, "source_workflow": wf["name"]}, indent=2) + "\n"
    )
    return dest
