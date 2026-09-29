"""Command-line interface. Run `fal.py --help` or `fal.py <command> --help`."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from . import __version__, catalog, cost, profiles, runner, schema
from .core import (
    EXIT_OK,
    EXIT_USAGE,
    FalkitError,
    emit_json,
    key_source,
    log,
    output_root,
    parse_assignment,
    read_json,
    resolve_key,
)


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------
def cmd_models_search(a: argparse.Namespace) -> Any:
    hits = catalog.search(
        " ".join(a.query) if a.query else None,
        category=a.category,
        since_days=a.since,
        include_training=a.include_training,
        include_inactive=a.include_inactive,
        refresh=a.refresh,
    )
    shown = hits[: a.limit]
    if a.prices:
        prices = catalog.get_prices([m["endpoint_id"] for m in shown])
        shown = [{**m, "price": prices.get(m["endpoint_id"])} for m in shown]
        hits = shown + hits[a.limit :]
    if a.json:
        return {"total": len(hits), "models": shown}
    print(f"{len(hits)} model(s), newest first:")
    print(catalog.format_table(hits, a.limit))
    return None


def cmd_models_categories(a: argparse.Namespace) -> Any:
    cats = catalog.categories(catalog.load_catalog(a.refresh))
    if a.json:
        return dict(cats)
    for c, n in cats:
        print(f"{n:>5}  {c}")
    return None


def cmd_models_show(a: argparse.Namespace) -> Any:
    m = catalog.get_model(a.endpoint_id)
    if not m:
        raise FalkitError(f"Unknown model {a.endpoint_id!r}", EXIT_USAGE)
    m = {**m, "pricing": catalog.get_prices([a.endpoint_id]).get(a.endpoint_id)}
    if a.json:
        return m
    print(f"{m['display_name']}  ({m['endpoint_id']})")
    print(f"  category: {m['category']} · date: {m['date'][:10]} · license: {m.get('license_type')}")
    p = m["pricing"]
    print("  pricing: " + (f"${p['unit_price']} per {p['unit']}" if p else "unavailable (no key?)"))
    print(f"  docs: {m['playground_url']}")
    print(f"  {m['description']}")
    return None


def cmd_pricing(a: argparse.Namespace) -> Any:
    resolve_key()
    prices = catalog.get_prices(a.endpoint_ids)
    if a.json:
        return prices
    for e in a.endpoint_ids:
        p = prices.get(e)
        print(f"{e}: " + (f"${p['unit_price']} per {p['unit']}" if p else "no price found"))
    return None


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------
def cmd_schema(a: argparse.Namespace) -> Any:
    compact = schema.compact(schema.fetch_openapi(a.endpoint_id), a.endpoint_id)
    if a.json:
        return compact if a.full else {"endpoint_id": a.endpoint_id, "parameters": schema.summarize(compact["input"])}
    print(f"{a.endpoint_id} — input parameters (schema order):")
    print(schema.format_summary(schema.summarize(compact["input"])))
    out_props = list((compact["output"].get("properties") or {}).keys())
    print(f"\noutput fields: {', '.join(out_props) or 'unknown'}")
    print(f"docs: {compact['documentation_url']}")
    return None


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------
def cmd_profile_init(a: argparse.Namespace) -> Any:
    d = profiles.init(a.endpoint_id, a.slug, a.scope, a.force)
    prof = profiles.load(str(d))
    summary = schema.summarize(prof["schema"]["input"])
    if a.json:
        return {
            "path": str(d),
            "slug": prof["slug"],
            "defaults": prof["defaults"],
            "parameters": summary,
            "pricing": prof.get("pricing"),
        }
    print(f"Created profile {prof['slug']!r} at {d}")
    p = prof.get("pricing")
    print("pricing: " + (f"${p['unit_price']} per {p['unit']}" if p else "unknown"))
    print("pinned defaults: " + json.dumps(prof["defaults"], ensure_ascii=False))
    print("\nparameters:")
    print(schema.format_summary(summary))
    print("\nnext: review defaults with the user, then research prompting (prompting.md).")
    return None


def cmd_profile_list(a: argparse.Namespace) -> Any:
    items = profiles.list_all()
    if a.json:
        return items
    if not items:
        print("No profiles yet. Create one with: fal.py profile init <endpoint_id>")
    for p in items:
        print(f"{p['slug']:<40} {p['endpoint_id']:<50} {p['category'] or '':<16} prompting:{p['prompting_status']}")
    return None


def cmd_profile_show(a: argparse.Namespace) -> Any:
    prof = profiles.load(a.profile)
    view = {k: v for k, v in prof.items() if k != "schema"}
    view["parameters"] = schema.summarize(prof["schema"]["input"])
    if a.json:
        return view
    print(json.dumps({k: v for k, v in view.items() if k != "parameters"}, ensure_ascii=False, indent=2))
    print("\nparameters:")
    print(schema.format_summary(view["parameters"]))
    return None


def cmd_profile_set(a: argparse.Namespace) -> Any:
    assigns = dict(parse_assignment(x) for x in a.assignments)
    res = profiles.set_defaults(a.profile, assigns, a.unset or [])
    for w in res["warnings"]:
        log(f"warning: {w}")
    if a.json:
        return res
    print("defaults: " + json.dumps(res["defaults"], ensure_ascii=False))
    return None


def cmd_profile_preset(a: argparse.Namespace) -> Any:
    assigns = dict(parse_assignment(x) for x in a.assignments)
    presets = profiles.set_preset(a.profile, a.name, assigns, a.delete)
    if a.json:
        return presets
    print(json.dumps(presets, ensure_ascii=False, indent=2))
    return None


def cmd_profile_meta(a: argparse.Namespace) -> Any:
    fields: dict[str, Any] = {}
    if a.max_usd is not None:
        fields["max_usd"] = None if a.max_usd < 0 else a.max_usd
    if a.prompting_status:
        fields["prompting_status"] = a.prompting_status
    if a.notes is not None:
        fields["notes"] = a.notes
    prof = profiles.set_meta(a.profile, **fields)
    return prof if a.json else print(json.dumps(prof, ensure_ascii=False, indent=2))


def cmd_profile_refresh(a: argparse.Namespace) -> Any:
    res = profiles.refresh(a.profile)
    if a.json:
        return res
    for k, v in res.items():
        print(f"{k}: {v}")
    return None


def cmd_profile_path(a: argparse.Namespace) -> Any:
    print(profiles.find(a.profile))
    return None


def cmd_profile_remove(a: argparse.Namespace) -> Any:
    d = profiles.remove(a.profile)
    print(f"Removed {d}")
    return None


# ---------------------------------------------------------------------------
# run / fetch / status / cancel / runs
# ---------------------------------------------------------------------------
def _load_overlays(a: argparse.Namespace) -> list[dict]:
    base: dict = {}
    if a.input:
        base.update(json.loads(a.input))
    if a.input_file:
        base.update(read_json(Path(a.input_file)))
    if not a.batch:
        return [base]
    overlays = []
    for i, line in enumerate(Path(a.batch).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            overlays.append({**base, **json.loads(line)})
        except json.JSONDecodeError as e:
            raise FalkitError(f"{a.batch}:{i}: invalid JSON ({e})", EXIT_USAGE) from e
    if not overlays:
        raise FalkitError(f"{a.batch} has no requests", EXIT_USAGE)
    return overlays


def cmd_run(a: argparse.Namespace) -> Any:
    target = runner.resolve_target(a.profile, a.endpoint)
    mock = read_json(Path(a.mock)) if a.mock else None
    opts = runner.RunOptions(
        root=output_root(a.out),
        label=a.label,
        timeout_s=a.timeout,
        no_wait=a.no_wait,
        download=not a.no_download,
        mock_result=mock,
    )
    opts.root.mkdir(parents=True, exist_ok=True)
    res = runner.run_many(
        target,
        _load_overlays(a),
        preset=a.preset,
        sets=[parse_assignment(x) for x in a.set or []],
        prompt=a.prompt,
        from_refs=a.from_ or [],
        opts=opts,
        max_cost=a.max_cost,
        assume_yes=a.yes,
        dry_run=a.dry_run,
        concurrency=a.concurrency,
    )
    if a.json:
        return res
    _print_run_result(res)
    return None


def _print_run_result(res: dict) -> None:
    if res.get("dry_run"):
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return
    if res.get("batch"):
        print(f"batch: {res['total'] - res['failed']}/{res['total']} succeeded")
        for r in res["runs"]:
            if "error" in r:
                print(f"  ✗ {r['error']}")
            else:
                _print_run_result(r)
        return
    if res.get("status") == "submitted":
        print(f"submitted {res['request_id']} → {res['run_dir']}\nresume with: fal.py fetch {res['run_dir']}")
        return
    print(f"✓ {res['run_id']}  ({res['endpoint_id']})")
    for o in res["outputs"]:
        loc = o.get("local_path") or o.get("url")
        dims = f" {o['width']}x{o['height']}" if o.get("width") else ""
        print(f"  {o['kind']:<6} {loc}{dims}")
    for k, v in (res.get("text") or {}).items():
        print(f"  {k}: {v[:300]}")
    print(f"  manifest: {Path(res['run_dir']) / 'manifest.json'}")


def cmd_fetch(a: argparse.Namespace) -> Any:
    root = output_root(a.out)
    run_dir = _run_dir(a.run, root)
    res = runner.fetch(run_dir, root, a.timeout, download_files=not a.no_download)
    if a.json:
        return res
    _print_run_result(res)
    return None


def _run_dir(ref: str, root: Path) -> Path:
    p = Path(ref).expanduser()
    if (p / "request.json").exists():
        return p
    if ref == "last":  # newest run of any status (pending runs are not in the index yet)
        dirs = sorted((d for d in root.glob("*/*") if (d / "request.json").exists()), key=lambda d: d.name)
        if dirs:
            return dirs[-1]
    mpath, _ = runner.load_manifest(ref, root)
    return mpath.parent


def cmd_status(a: argparse.Namespace) -> Any:
    res = runner.status(_run_dir(a.run, output_root(a.out)))
    return res if a.json else print(json.dumps(res, indent=2))


def cmd_cancel(a: argparse.Namespace) -> Any:
    runner.cancel(_run_dir(a.run, output_root(a.out)))
    print("cancel requested")
    return None


def cmd_runs_list(a: argparse.Namespace) -> Any:
    root = output_root(a.out)
    entries = runner._index_entries(root)[-a.limit :]
    if a.json:
        return entries
    if not entries:
        print(f"No runs recorded in {root}")
    for e in reversed(entries):
        cost_s = f"${e['cost_usd']}" if e.get("cost_usd") is not None else ""
        print(f"{e['run_id']:<60} {','.join(e.get('kinds') or []):<12} {cost_s:<8} {e.get('prompt') or ''}")
    return None


def cmd_runs_show(a: argparse.Namespace) -> Any:
    mpath, manifest = runner.load_manifest(a.run, output_root(a.out))
    return manifest if a.json else print(json.dumps(manifest, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# export / doctor
# ---------------------------------------------------------------------------
def cmd_export(a: argparse.Namespace) -> Any:
    from . import export

    dest = export.export(a.profile, Path(a.dest).expanduser(), a.name, a.force)
    if a.json:
        return {"path": str(dest)}
    print(f"Exported standalone skill to {dest}")
    return None


def cmd_doctor(a: argparse.Namespace) -> Any:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("python", sys.version_info >= (3, 10), sys.version.split()[0]))
    checks.append(
        ("uv", bool(shutil.which("uv")), shutil.which("uv") or "not found (optional; python3 + pip deps also work)")
    )
    checks.append(("bws", bool(shutil.which("bws")), shutil.which("bws") or "not found (optional)"))
    try:
        src = key_source()
        checks.append(("fal key", bool(src), src or "missing — see references/auth.md"))
    except FalkitError as e:
        checks.append(("fal key", False, f"{e} {e.hint or ''}"))
        src = None
    try:
        catalog.http_json("GET", catalog.MODELS_URL, params={"limit": 1})
        checks.append(("models API", True, "reachable"))
    except FalkitError as e:
        checks.append(("models API", False, str(e)))
    if src:
        try:
            ok = bool(
                catalog.http_json(
                    "GET", catalog.PRICING_URL, params={"endpoint_id": "fal-ai/flux/schnell"}, key=resolve_key()
                )
            )
            checks.append(("key valid", ok, "pricing API accepted the key"))
        except FalkitError as e:
            checks.append(("key valid", False, str(e)))
    checks.append(("profiles", True, " → ".join(str(d) for d in profiles.search_dirs())))
    root = output_root(a.out)
    checks.append(("output dir", os.access(root if root.exists() else Path("."), os.W_OK), str(root.resolve())))
    checks.append(("max cost", True, f"${cost.max_usd(None, None):.2f} per run (FAL_MAX_COST)"))
    if a.json:
        return {"version": __version__, "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks]}
    print(f"fal-skill-creator runtime {__version__}")
    for n, ok, d in checks:
        print(f"  {'✓' if ok else '✗'} {n:<11} {d}")
    return None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output on stdout")
    common.add_argument("--out", help="output root for runs (default: $FAL_OUTPUT_DIR or ./fal-outputs)")

    p = argparse.ArgumentParser(prog="fal.py", description="fal.ai model discovery, profiles and generation runs.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    # models
    pm = sub.add_parser("models", help="search the fal model catalog").add_subparsers(dest="sub", required=True)
    s = pm.add_parser("search", parents=[common], help="search models, newest first")
    s.add_argument("query", nargs="*", help="terms ANDed over id, name, tags, description")
    s.add_argument("--category", "-c", help="e.g. text-to-image, image-to-video (see `models categories`)")
    s.add_argument("--limit", "-n", type=int, default=15)
    s.add_argument("--since", type=int, metavar="DAYS", help="only models released in the last N days")
    s.add_argument("--include-training", action="store_true")
    s.add_argument("--include-inactive", action="store_true")
    s.add_argument("--refresh", action="store_true", help="ignore the 6h catalog cache")
    s.add_argument("--prices", action="store_true", help="add unit prices for the shown models (needs key)")
    s.set_defaults(fn=cmd_models_search)
    s = pm.add_parser("categories", parents=[common], help="list categories with model counts")
    s.add_argument("--refresh", action="store_true")
    s.set_defaults(fn=cmd_models_categories)
    s = pm.add_parser("show", parents=[common], help="details + pricing for one model")
    s.add_argument("endpoint_id")
    s.set_defaults(fn=cmd_models_show)

    s = sub.add_parser("pricing", parents=[common], help="unit prices for endpoints (needs key)")
    s.add_argument("endpoint_ids", nargs="+")
    s.set_defaults(fn=cmd_pricing)

    s = sub.add_parser("schema", parents=[common], help="fetch and summarize an endpoint's input schema")
    s.add_argument("endpoint_id")
    s.add_argument("--full", action="store_true", help="with --json: full compact input/output schema")
    s.set_defaults(fn=cmd_schema)

    # profile
    pp = sub.add_parser("profile", help="manage model profiles").add_subparsers(dest="sub", required=True)
    s = pp.add_parser("init", parents=[common], help="create a profile from an endpoint's schema")
    s.add_argument("endpoint_id")
    s.add_argument("--slug")
    s.add_argument("--scope", choices=["user", "project"], default="user")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_profile_init)
    s = pp.add_parser("list", parents=[common])
    s.set_defaults(fn=cmd_profile_list)
    s = pp.add_parser("show", parents=[common])
    s.add_argument("profile")
    s.set_defaults(fn=cmd_profile_show)
    s = pp.add_parser("set", parents=[common], help="pin default arguments: key=value …")
    s.add_argument("profile")
    s.add_argument("assignments", nargs="*")
    s.add_argument("--unset", action="append", metavar="KEY")
    s.set_defaults(fn=cmd_profile_set)
    s = pp.add_parser("preset", parents=[common], help="create/update a named preset: key=value …")
    s.add_argument("profile")
    s.add_argument("name")
    s.add_argument("assignments", nargs="*")
    s.add_argument("--delete", action="store_true")
    s.set_defaults(fn=cmd_profile_preset)
    s = pp.add_parser("meta", parents=[common], help="set cost guard / research status / notes")
    s.add_argument("profile")
    s.add_argument("--max-usd", type=float, help="per-run cost limit for this profile (negative clears)")
    s.add_argument("--prompting-status", choices=["unresearched", "researched", "stale"])
    s.add_argument("--notes")
    s.set_defaults(fn=cmd_profile_meta)
    s = pp.add_parser("refresh", parents=[common], help="re-fetch schema + pricing and report drift")
    s.add_argument("profile")
    s.set_defaults(fn=cmd_profile_refresh)
    s = pp.add_parser("path", parents=[common])
    s.add_argument("profile")
    s.set_defaults(fn=cmd_profile_path)
    s = pp.add_parser("remove", parents=[common])
    s.add_argument("profile")
    s.set_defaults(fn=cmd_profile_remove)

    # run
    s = sub.add_parser("run", parents=[common], help="generate: validate, price-check, submit, wait, save")
    tgt = s.add_mutually_exclusive_group(required=True)
    tgt.add_argument("--profile", "-p", help="profile slug, endpoint id, or profile directory")
    tgt.add_argument("--endpoint", "-e", help="raw endpoint id (no profile)")
    s.add_argument("--prompt")
    s.add_argument(
        "--set",
        "-s",
        action="append",
        metavar="KEY=VALUE",
        help="argument; VALUE is JSON if it parses. '@path' uploads a local file; 'from:REF[#sel]' uses a previous run's output",
    )
    s.add_argument("--input", help="JSON object of arguments")
    s.add_argument("--input-file", help="JSON file of arguments")
    s.add_argument("--preset")
    s.add_argument(
        "--from",
        dest="from_",
        action="append",
        metavar="REF",
        help="previous run (last, last~1, run id, dir, manifest) whose outputs auto-fill empty media inputs",
    )
    s.add_argument("--batch", help="JSONL file; one run per line (merged over other inputs)")
    s.add_argument("--concurrency", type=int, default=3)
    s.add_argument("--label", help="short tag added to the run id")
    s.add_argument("--max-cost", type=float, help="USD limit before asking (default: profile, $FAL_MAX_COST, or 1.00)")
    s.add_argument("--yes", "-y", action="store_true", help="the user approved the cost; skip the guard")
    s.add_argument("--dry-run", action="store_true", help="show final arguments + cost; submit nothing")
    s.add_argument("--no-wait", action="store_true", help="submit and return; finish later with `fetch`")
    s.add_argument("--timeout", type=float, default=1800)
    s.add_argument("--no-download", action="store_true")
    s.add_argument("--mock", metavar="RESULT_JSON", help="skip fal; treat this JSON as the result (testing)")
    s.set_defaults(fn=cmd_run)

    for name, fn, helptext in (
        ("fetch", cmd_fetch, "finish a --no-wait or timed-out run"),
        ("status", cmd_status, "check a submitted run"),
        ("cancel", cmd_cancel, "cancel a submitted run"),
    ):
        s = sub.add_parser(name, parents=[common], help=helptext)
        s.add_argument("run", help="run dir, run id, or last")
        if name == "fetch":
            s.add_argument("--timeout", type=float, default=1800)
            s.add_argument("--no-download", action="store_true")
        s.set_defaults(fn=fn)

    pr = sub.add_parser("runs", help="browse run history").add_subparsers(dest="sub", required=True)
    s = pr.add_parser("list", parents=[common])
    s.add_argument("--limit", "-n", type=int, default=20)
    s.set_defaults(fn=cmd_runs_list)
    s = pr.add_parser("show", parents=[common])
    s.add_argument("run", nargs="?", default="last")
    s.set_defaults(fn=cmd_runs_show)

    s = sub.add_parser("export", parents=[common], help="export a profile as a standalone skill")
    s.add_argument("profile")
    s.add_argument("--dest", default=".claude/skills")
    s.add_argument("--name", help="skill name (default fal-<slug>)")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("doctor", parents=[common], help="check setup: key, network, dirs")
    s.set_defaults(fn=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        res = args.fn(args)
        if getattr(args, "json", False) and res is not None:
            emit_json(res)
        return EXIT_OK
    except FalkitError as e:
        if getattr(args, "json", False):
            emit_json({"error": str(e), "code": e.code, "hint": e.hint})
        log(f"error: {e}")
        if e.hint:
            log(f"hint: {e.hint}")
        return e.code
    except KeyboardInterrupt:
        log("interrupted")
        return 130
    except Exception as e:  # unexpected: keep the message short unless debugging
        if os.environ.get("FALKIT_DEBUG"):
            raise
        if getattr(args, "json", False):
            emit_json(
                {"error": f"{type(e).__name__}: {e}", "code": 1, "hint": "rerun with FALKIT_DEBUG=1 for a traceback"}
            )
        log(f"error: {type(e).__name__}: {e}\nhint: rerun with FALKIT_DEBUG=1 for a traceback")
        return 1
