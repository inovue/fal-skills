"""Workflows: several models plus local processing, packaged as one skill.

A workflow is data, like a profile. It doesn't hard-code endpoints; each fal
step names a profile, so a model upgrade means re-pointing one profile:

    <name>/
      workflow.json   steps (fal / local / review), per-step profile, template and settings
      WORKFLOW.md     what the agent does at each step, and the step-specific ```template blocks
      scripts/        local processing used by `local` steps (split, crop, ffmpeg…)

Every prompted fal step renders its prompt from a template: one in WORKFLOW.md
(written for this workflow, following the profile's researched rules) or one in
the profile's prompting.md. `check` refuses templates that don't exist, and
`export` refuses steps whose model hasn't been researched, so a workflow skill
never sends a model a blind prompt.

The agent runs the steps one at a time (`fal workflow plan` prints the next
command) and looks at each intermediate result before paying for the next.
`fal workflow export` bundles the workflow, its profiles, its scripts and the
runtime into one standalone skill.

Lookup order: <skill dir> itself (an exported workflow skill) → ./.fal/workflows
(project) → ~/.fal-skills/workflows (user).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import __version__, pricing, profiles, runner, templates
from .core import EXIT_USAGE, SKILL_DIR, FalkitError, log, now_iso, read_json, user_home_dir, write_json
from .export import RUNTIME_FILES, prepare_dest, render, vendor_runtime

WORKFLOW_FORMAT = "fal-workflow@1"
STEP_TYPES = ("fal", "local", "review")
_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_PLACEHOLDER_RE = re.compile(r"\{(in|files):([a-z0-9-]+(?:\|[a-z0-9-]+)*)(?:#([\w.*-]+))?\}")
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
            "steps": [],
        }
        tpl = (SKILL_DIR / "assets" / "workflow.template.md").read_text(encoding="utf-8")
        (dest / "WORKFLOW.md").write_text(render(tpl, {"name": name}), encoding="utf-8")
    wf.update(name=name, created_at=now_iso(), runtime_version=__version__)
    write_json(dest / "workflow.json", wf)
    return dest


# ---------------------------------------------------------------------------
# Check: structure, profiles, templates, scripts
# ---------------------------------------------------------------------------
def _profile_or_none(slug: str) -> dict | None:
    try:
        return profiles.load(slug)
    except FalkitError:
        return None


def _step_price(step: dict, prof: dict) -> dict | None:
    """What one run of this step costs at its settings, from the profile's researched pricing table."""
    args = dict(prof.get("defaults") or {})
    if step.get("preset"):
        args.update((prof.get("presets") or {}).get(step["preset"]) or {})
    args.update(step.get("set") or {})
    try:
        table = pricing.load(Path(prof["path"]))
    except FalkitError:
        table = None
    est = pricing.estimate(table, args, prof["schema"]["input"])
    api = prof.get("pricing") or {}
    return {
        "estimate": est,
        "text": pricing.describe(est) if est else (
            f"${api.get('unit_price')} per {api.get('unit')} (API unit price; no researched table)" if api else "unknown"
        ),
    }


def doc_path(wdir: Path) -> Path:
    """WORKFLOW.md, or SKILL.md inside an exported workflow skill (its body is WORKFLOW.md)."""
    return wdir / "WORKFLOW.md" if (wdir / "WORKFLOW.md").exists() else wdir / "SKILL.md"


def step_template(step: dict, wdir: Path, prof: dict | None) -> dict | None:
    """The step's template: WORKFLOW.md first, then the profile's prompting.md. None if it has none."""
    name = step.get("template")
    if not name:
        return None
    doc = doc_path(wdir)
    if doc.exists() and name in templates.parse(doc.read_text(encoding="utf-8")):
        return templates.load(f"{doc}#{name}", None) | {"ref": f"{doc.resolve()}#{name}"}
    if prof:
        return templates.load(name, prof) | {"ref": name}
    raise FalkitError(f"template {name!r} not found", EXIT_USAGE)


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
    pricing: dict[str, dict | None] = {}
    blockers: list[str] = []  # fine for trying the workflow out, but not for exporting it as a skill
    for i, s in enumerate(steps):
        sid = s.get("id") or f"#{i}"
        where = f"step {sid}"
        if not _ID_RE.match(str(s.get("id") or "")):
            errors.append(f"{where}: id must be lowercase letters, digits and single hyphens")
        if sid in seen:
            errors.append(f"{where}: duplicate id")
        if s.get("type") not in STEP_TYPES:
            errors.append(f"{where}: type must be one of {', '.join(STEP_TYPES)}")
        for entry in s.get("from") or []:
            alts = entry.split("|")
            for dep in alts:
                if dep not in seen:
                    errors.append(f"{where}: 'from' names {dep!r}, which is not an earlier step")
                elif next(x for x in steps if x.get("id") == dep).get("type") == "review":
                    errors.append(f"{where}: 'from' names review step {dep!r}, which has no outputs")
            if all(next((x for x in steps if x.get("id") == d), {}).get("optional") for d in alts):
                warnings.append(
                    f"{where}: if optional step {alts[-1]!r} is skipped this step has no input; "
                    f"add a fallback such as '{entry}|<earlier step>'"
                )
        if s.get("type") == "fal":
            slug = s.get("profile")
            prof = _profile_or_none(slug) if slug else None
            if not slug:
                errors.append(f"{where}: fal steps need a 'profile'")
            elif not prof:
                hint = f" — create it: fal profile init {s['endpoint_hint']} --slug {slug}" if s.get("endpoint_hint") else ""
                errors.append(f"{where}: profile {slug!r} not found{hint}")
            else:
                prompted = s.get("prompted", True)
                if prompted and prof.get("prompting_status") != "researched":
                    blockers.append(
                        f"{where}: profile {slug!r} prompting is {prof.get('prompting_status')}; research it (SKILL.md A4)"
                    )
                if s.get("preset") and s["preset"] not in (prof.get("presets") or {}):
                    errors.append(f"{where}: preset {s['preset']!r} not in profile {slug!r}")
                if prompted and not s.get("template"):
                    blockers.append(f"{where}: no 'template'; the prompt would be written by hand on every run")
                if s.get("template"):
                    try:
                        tpl = step_template(s, wdir, prof)
                    except FalkitError:
                        errors.append(
                            f"{where}: template {s['template']!r} is in neither WORKFLOW.md nor {slug!r}'s prompting.md"
                        )
                    else:
                        extra = sorted(set(s.get("slots") or {}) - set(tpl["slots"]))
                        if extra:
                            errors.append(f"{where}: 'slots' names {', '.join(extra)}, not in template {s['template']!r}")
                        params = prof["schema"]["input"].get("properties") or {}
                        for problem in templates.lint(tpl["body"], set(params)):
                            errors.append(f"{where}: template {s['template']!r}: {problem}")
                        fixed_params = sorted(set(s.get("slots") or {}) & set(params))
                        if fixed_params:
                            errors.append(f"{where}: set {', '.join(fixed_params)} under 'set', not 'slots' (model parameters)")
                pricing[sid] = _step_price(s, prof)
        elif s.get("type") == "local":
            if not s.get("command"):
                errors.append(f"{where}: local steps need a 'command'")
            for script in re.findall(r"scripts/[\w./-]+", s.get("command") or ""):
                if not (wdir / script).exists():
                    errors.append(f"{where}: {script} does not exist in the workflow")
            for m in _PLACEHOLDER_RE.finditer(s.get("command") or ""):
                if any(d not in seen for d in m.group(2).split("|")):
                    errors.append(f"{where}: {m.group(0)} refers to a step that doesn't run earlier")
        seen.append(sid)
    if not doc_path(wdir).exists():
        errors.append("WORKFLOW.md is missing")
    if "max_usd" in wf:
        warnings.append("'max_usd' is ignored since 1.2 (the cost guard was removed); delete it")
    return {
        "name": wf.get("name"),
        "path": str(wdir),
        "ok": not errors,
        "errors": errors,
        "warnings": warnings + [f"{b} (blocks export)" for b in blockers],
        "export_blockers": blockers,
        "pricing": pricing,
    }


# ---------------------------------------------------------------------------
# Plan: the concrete command for each step, with earlier outputs resolved
# ---------------------------------------------------------------------------
def step_label(wf: dict, step_id: str) -> str:
    return f"{wf['name']}.{step_id}"


def _quote(s: str) -> str:
    """Quote for the platform's shell: double quotes on Windows (cmd and PowerShell), POSIX quoting elsewhere."""
    return subprocess.list2cmdline([s]) if os.name == "nt" else shlex.quote(s)


def _latest(wf: dict, sid: str, out_root: Path) -> tuple[Path, dict] | None:
    try:
        mp, manifest = runner.load_manifest(f"label:{step_label(wf, sid)}", out_root)
    except FalkitError:
        return None
    return mp.resolve(), manifest


def _fal_command(wf: dict, wdir: Path, s: dict, deps: list[str], label: str) -> list[str]:
    parts = ["fal", "run", "-p", s["profile"]]
    if s.get("preset"):
        parts += ["--preset", s["preset"]]
    for k, v in (s.get("set") or {}).items():
        parts += ["--set", f"{k}={json.dumps(v) if not isinstance(v, str) else v}"]
    for dep in deps:
        parts += ["--from", f"label:{step_label(wf, dep)}"]
    if s.get("prompted", True):
        tpl = None
        if s.get("template"):
            try:
                tpl = step_template(s, wdir, _profile_or_none(s["profile"]))
            except FalkitError:
                tpl = None
        if tpl:
            parts += ["--template", tpl["ref"]]
            fixed = s.get("slots") or {}
            for slot in tpl["slots"]:
                value = fixed.get(slot)
                if value is not None:
                    parts += ["--slot", f"{slot}={value}"]
                elif slot not in tpl["optional"]:
                    parts += ["--slot", f"{slot}=<{slot}>"]
        else:
            parts += ["--prompt", "<prompt from WORKFLOW.md>"]
    parts += ["--label", label]
    return parts


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

    def pick(entry: str) -> str | None:
        """'cutout|sheet' → the first alternative that ran in this pass (an optional step may have been skipped)."""
        return next((d for d in entry.split("|") if d in current), None)

    for s in wf.get("steps") or []:
        sid = s["id"]
        label = step_label(wf, sid)
        entries = [e for e in s.get("from") or [] if types.get(e.split("|")[0]) != "review"]
        resolved = [pick(e) for e in entries]
        deps = [r or e.split("|")[0] for r, e in zip(resolved, entries, strict=True)]
        row: dict[str, Any] = {"id": sid, "type": s.get("type"), "purpose": s.get("purpose"), "label": label}
        if s.get("optional"):
            row["optional"] = True
        latest = _latest(wf, sid, out_root) if s.get("type") != "review" else None
        row["done"] = None
        if latest:
            parents = {Path(p).resolve() for p in latest[1].get("parents") or []}
            fresh = all(r and Path(current[r]["_path"]) in parents for r in resolved)
            if fresh:
                current[sid] = {**latest[1], "_path": str(latest[0])}
                row["done"] = {"run_id": latest[1]["run_id"], "run_dir": latest[1].get("run_dir")}
        waiting = [e for r, e in zip(resolved, entries, strict=True) if not r]
        if s.get("type") == "fal":
            parts = _fal_command(wf, wdir, s, deps, label)
            if int(s.get("count") or 1) > 1:
                row["note"] = f"run {s['count']} variations: --batch with {s['count']} lines, or repeat with new seeds"
            row["command"] = " ".join(_quote(p) if not p.startswith("<") else f'"{p}"' for p in parts)
            unfilled = re.findall(r"=<([a-z0-9_]+)>$", "\n".join(parts), re.M)
            if unfilled:
                row["fill"] = unfilled
            tpl_opt = _optional_slots(s, wdir)
            if tpl_opt:
                row["optional_slots"] = tpl_opt
            if waiting:
                row["blocked_by"] = waiting
        elif s.get("type") == "local":
            work = (out_root / "_work" / wf["name"] / sid).resolve()
            unresolved: list[str] = []

            def fill(m: re.Match, unresolved: list[str] = unresolved) -> str:
                kind, entry, sel = m.groups()
                dep = pick(entry)
                manifest = current.get(dep) if dep else None
                if not manifest:
                    unresolved.append(entry)
                    return f"<{kind} of step {entry}>"
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
            waiting = sorted(set(unresolved) | set(waiting))
            if waiting:
                row["blocked_by"] = waiting
        else:
            row["command"] = None
        if s.get("checkpoint", s.get("type") in ("fal", "review")):
            row["checkpoint"] = s.get("check") or "look at this step's output (and show the user) before continuing"
        rows.append(row)
    for i, r in enumerate(rows):  # an optional step before a step that ran in this pass was skipped
        if r.get("optional") and not r["done"] and any(x["done"] for x in rows[i + 1 :]):
            r["skipped"] = True
    pending = [r for r in rows if not r["done"] and not r.get("skipped") and r["type"] != "review"]
    nxt = pending[0]["id"] if pending else None
    skip_to = None
    if pending and pending[0].get("optional"):
        skip_to = next((r["id"] for r in pending[1:] if not r.get("optional")), None)
    return {
        "name": wf["name"],
        "path": str(wdir),
        "next": nxt,
        "skip_to": skip_to,
        "note": None if nxt else "every step has run; for a new request, start again at the first step",
        "steps": rows,
    }


def _optional_slots(step: dict, wdir: Path) -> list[str]:
    if not step.get("template"):
        return []
    try:
        tpl = step_template(step, wdir, _profile_or_none(step["profile"]))
    except FalkitError:
        return []
    return [x for x in tpl["optional"] if x not in (step.get("slots") or {})]


# ---------------------------------------------------------------------------
# Export: workflow + its profiles + scripts + runtime → one standalone skill
# ---------------------------------------------------------------------------
def export(ref: str | None, dest_root: Path, name: str | None, force: bool) -> Path:
    report = check(ref)
    problems = report["errors"] + report["export_blockers"]
    if problems:
        raise FalkitError(
            "Workflow isn't ready to export:\n  " + "\n  ".join(problems),
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
    clean = {k: v for k, v in wf.items() if k not in {"path", "max_usd"}}
    write_json(dest / "workflow.json", clean)

    body = (src / "WORKFLOW.md").read_text(encoding="utf-8")
    tpl = (SKILL_DIR / "assets" / "workflow-skill.template.md").read_text(encoding="utf-8")
    steps_md = "\n".join(
        f"{i}. `{s['id']}` ({s['type']}"
        + (f", profile `{s['profile']}`" if s.get("profile") else "")
        + (", optional" if s.get("optional") else "")
        + f"): {s.get('purpose') or ''}"
        for i, s in enumerate(wf["steps"], 1)
    )
    prices = [f"`{sid}` {p['text'] if p else 'unknown'}" for sid, p in report["pricing"].items()]
    values = {
        "skill_name": dest.name,
        "description": wf["description"].replace('"', "'"),
        "workflow_name": wf["name"],
        "runtime_version": __version__,
        "steps": steps_md,
        "pricing": "; ".join(prices) or "no paid steps",
        "profiles": ", ".join(f"`{s}`" for s in slugs) or "none",
        "body": body.strip(),
    }
    (dest / "SKILL.md").write_text(render(tpl, values), encoding="utf-8")
    (dest / ".exported.json").write_text(
        json.dumps({"runtime_version": __version__, "source_workflow": wf["name"]}, indent=2) + "\n"
    )
    return dest
