"""Offline tests for the workflow layer: label refs, ingest, bundled profiles, workflows, sprite splitting, MCP auth.

No network, no key, no cost. Fal steps run through `--mock` results.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "fal-skill-creator"
SCRIPTS = SKILL / "scripts"
SPLIT = SKILL / "assets" / "workflows" / "sprite-sheet" / "scripts" / "split_sprites.py"
FIX = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

from falkit import profiles, runner, schema, workflows  # noqa: E402
from falkit.core import FalkitError  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FAL_SKILLS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    for v in ("FAL_PROFILES_DIR", "FAL_KEY", "FAL_KEY_ID", "FAL_KEY_SECRET", "BWS_ACCESS_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(profiles, "url_status", lambda url: 200)  # source checks stay offline


def _compact(name: str, endpoint: str) -> dict:
    return schema.compact(json.loads((FIX / name).read_text(encoding="utf-8")), endpoint)


def _profile(slug: str, compact: dict, pricing: dict, base: Path | None = None, status: str = "researched") -> Path:
    d = (base or profiles.user_dir()) / slug
    d.mkdir(parents=True)
    (d / "schema.json").write_text(json.dumps(compact), encoding="utf-8")
    (d / "defaults.json").write_text(json.dumps(schema.schema_defaults(compact["input"])), encoding="utf-8")
    (d / "profile.json").write_text(
        json.dumps({"slug": slug, "endpoint_id": compact["endpoint_id"], "pricing": pricing, "prompting_status": status}), encoding="utf-8")
    return d


GUIDES = SKILL / "assets" / "guides"


def _real_profile(slug: str, status: str = "researched", base: Path | None = None) -> Path:
    """A profile built from a live schema fixture and its bundled guide, as `profile init` would make it."""
    compact = json.loads((FIX / f"schema-{slug}.json").read_text(encoding="utf-8"))
    entry = json.loads((GUIDES / "index.json").read_text(encoding="utf-8"))["guides"][compact["endpoint_id"]]
    d = (base or profiles.user_dir()) / slug
    d.mkdir(parents=True)
    (d / "schema.json").write_text(json.dumps(compact), encoding="utf-8")
    (d / "defaults.json").write_text(json.dumps({**schema.schema_defaults(compact["input"]), **entry.get("recommend", {})}), encoding="utf-8")
    (d / "presets.json").write_text(json.dumps(entry.get("presets") or {}), encoding="utf-8")
    (d / "prompting.md").write_text((GUIDES / entry["file"]).read_text(), encoding="utf-8")
    (d / "profile.json").write_text(json.dumps({
        "slug": slug, "endpoint_id": compact["endpoint_id"], "category": compact["category"],
        "prompt_field": schema.prompt_field(compact["input"]), "prompting_status": status,
        "pricing": {"unit_price": 1, "unit": "units"},
    }), encoding="utf-8")
    return d


def _sheet(path: Path, rows: int = 2, cols: int = 3, alpha: bool = True) -> Path:
    im = Image.new("RGBA", (cols * 100, rows * 100), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for r in range(rows):
        for c in range(cols):
            d.rectangle((c * 100 + 20, r * 100 + 25, c * 100 + 75, r * 100 + 80), fill=(40 * r, 60 * c, 200, 255))
    d.point((cols * 100 - 2, rows * 100 - 2), fill=(255, 255, 255, 255))  # a speck to drop
    if not alpha:
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg.convert("RGB")
    im.save(path)
    return path


def _mock_run(target, tmp_path: Path, result: dict, label: str, from_refs=(), prompt="x") -> dict:
    opts = runner.RunOptions(root=tmp_path / "out", label=label, mock_result=result)
    opts.root.mkdir(exist_ok=True)
    return runner.run_many(
        target, [{}], preset=None, sets=[], prompt=prompt, from_refs=list(from_refs), opts=opts,
        dry_run=False, concurrency=1,
    )


# --- runs: label refs and ingest -----------------------------------------------
def test_label_refs_and_ingest_feed_autowire(tmp_path):
    flux = _compact("openapi-flux-dev.json", "fal-ai/flux/dev")
    kling = _compact("openapi-kling-i2v.json", "fal-ai/kling")
    img = _sheet(tmp_path / "a.png")
    res = {"images": [{"url": img.as_uri(), "content_type": "image/png"}]}
    t = runner.Target("fal-ai/flux/dev", flux["input"])
    first = _mock_run(t, tmp_path, res, "wf.a")
    _mock_run(t, tmp_path, res, "wf.b")
    second = _mock_run(t, tmp_path, res, "wf.a")
    root = tmp_path / "out"
    assert runner.load_manifest("label:wf.a", root)[1]["run_id"] == second["run_id"]
    assert runner.load_manifest("label:wf.a~1", root)[1]["run_id"] == first["run_id"]
    with pytest.raises(FalkitError):
        runner.load_manifest("label:missing", root)

    work = tmp_path / "work"
    work.mkdir()
    _sheet(work / "piece.png")
    (work / ".hidden").write_text("skip me", encoding="utf-8")
    m = runner.ingest([work], root, "wf.split", ["label:wf.a"], note="split", move=True)
    out = m["outputs"]
    assert len(out) == 1 and out[0]["kind"] == "image" and out[0]["url"] is None
    assert (out[0]["width"], out[0]["height"]) == (300, 200)
    assert m["parents"] == [str(runner.load_manifest("label:wf.a", root)[0])]
    assert not (work / "piece.png").exists() and (work / ".hidden").exists()

    plan = runner.prepare(
        runner.Target("fal-ai/kling", kling["input"]), {}, preset=None, sets=[], prompt="go",
        from_refs=["label:wf.split"], uploader=runner.Uploader(dry_run=True), root=root, quiet=True,
    )
    assert plan.arguments["image_url"].startswith("<upload:") and "piece.png" in plan.arguments["image_url"]


def test_ingest_rejects_missing_and_empty(tmp_path):
    with pytest.raises(FalkitError):
        runner.ingest([tmp_path / "nope"], tmp_path / "out", None, [])
    (tmp_path / "empty").mkdir()
    with pytest.raises(FalkitError):
        runner.ingest([tmp_path / "empty"], tmp_path / "out", None, [])


def test_jpeg_size_header(tmp_path):
    p = tmp_path / "x.jpg"
    Image.new("RGB", (123, 45), (9, 9, 9)).save(p)
    assert runner._image_size(p) == (123, 45)


# --- bundled profiles ------------------------------------------------------------
def test_bundled_profiles_shadow_user_profiles(tmp_path, monkeypatch):
    flux = _compact("openapi-flux-dev.json", "fal-ai/flux/dev")
    _profile("img", flux, {"unit_price": 0.025, "unit": "megapixels"})
    skill = tmp_path / "exported"
    _profile("img", flux, {"unit_price": 0.5, "unit": "images"}, base=skill / "profiles")
    monkeypatch.setattr(profiles, "SKILL_DIR", skill)
    assert profiles.load("img")["pricing"]["unit_price"] == 0.5
    assert profiles.list_all()[0]["path"].startswith(str(skill))


# --- workflows -----------------------------------------------------------------------
def test_workflow_check_plan_lineage_and_export(tmp_path):
    workflows.init("icons", "user", "sprite-sheet", False)
    rep = workflows.check("icons")
    assert not rep["ok"] and any("gpt-image" in e and "profile init" in e for e in rep["errors"])

    _real_profile("gpt-image")
    _real_profile("remove-bg")
    rep = workflows.check("icons")
    assert rep["ok"], rep["errors"]
    assert rep["export_blockers"] == []
    assert rep["pricing"]["sheet"]["estimate"]["usd"] == 0.00903  # medium, landscape_4_3 (the researched table)
    assert rep["pricing"]["cutout"]["estimate"]["usd"] == 0.01

    root = tmp_path / "out"
    p = workflows.plan("icons", root)
    assert p["next"] == "sheet" and p["steps"][2]["blocked_by"] == ["cutout|sheet"]
    sheet_cmd = p["steps"][0]["command"]
    assert "--label icons.sheet" in sheet_cmd and "WORKFLOW.md#sheet" in sheet_cmd and "--preset asset" in sheet_cmd
    assert "backdrop=fully transparent" in sheet_cmd and "count=<count>" in sheet_cmd and "--prompt" not in sheet_cmd
    assert p["steps"][0]["fill"] == ["use", "count", "style", "theme", "rows", "cols", "item_list"]
    assert p["steps"][1]["optional"] and "--template" not in p["steps"][1]["command"]

    sheet = _sheet(tmp_path / "sheet.png")
    res = {"images": [{"url": sheet.as_uri(), "content_type": "image/png"}]}
    sheet_t = runner.resolve_target("gpt-image", None)
    cut_t = runner.resolve_target("remove-bg", None)
    tpl = workflows.step_template(workflows.load("icons")["steps"][0], Path(p["path"]), None)
    slot_values = {"use": "an RPG inventory", "count": 6, "style": "16-bit pixel art", "theme": "fantasy item",
                   "rows": 2, "cols": 3, "item_list": "sword, shield, potion, key, chest, scroll",
                   "backdrop": "fully transparent, no checkerboard, no solid color"}
    opts = runner.RunOptions(root=root, label="icons.sheet", mock_result=res)
    m = runner.run_many(sheet_t, [{}], preset="asset", sets=[], prompt=None, from_refs=[], opts=opts, dry_run=False,
                        concurrency=1, template=tpl, slot_values=slot_values)
    assert m["arguments"]["prompt"].startswith("A sprite sheet for an RPG inventory: 6 16-bit pixel art fantasy item")
    assert m["arguments"]["background"] == "transparent" and m["arguments"]["sync_mode"] is False
    assert m["prompt_template"]["name"] == "sheet" and m["price_estimate"]["usd"] == 0.00903

    # The optional cutout is skipped: split reads the sheet directly.
    p = workflows.plan("icons", root)
    assert p["next"] == "cutout" and p["skip_to"] == "split"
    split = p["steps"][2]
    assert "blocked_by" not in split and "images-0.png" in split["command"]
    assert "--parent label:icons.sheet" in split["then"]
    r = subprocess.run(split["command"].replace("uv run ", f"{sys.executable} ", 1), shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["count"] == 6
    runner.ingest([Path(split["work_dir"])], root, "icons.split", ["label:icons.sheet"], move=True)
    p = workflows.plan("icons", root)
    assert p["next"] is None and p["steps"][1].get("skipped") and p["steps"][2]["done"]

    # Running the optional step makes split pending again, now fed by the cutout.
    _mock_run(cut_t, tmp_path, {"image": res["images"][0]}, "icons.cutout", ["label:icons.sheet"])
    p = workflows.plan("icons", root)
    assert p["next"] == "split" and "--parent label:icons.cutout" in p["steps"][2]["then"]

    # A new request reruns the first step: everything after it is pending again.
    _mock_run(sheet_t, tmp_path, res, "icons.sheet")
    p = workflows.plan("icons", root)
    assert p["next"] == "cutout" and [bool(s["done"]) for s in p["steps"]] == [True, False, False]

    dest = workflows.export("icons", tmp_path / "skills", None, False)
    assert dest.name == "fal-icons"
    for rel in ("SKILL.md", "workflow.json", "scripts/fal.py", "scripts/falkit/workflows.py", "scripts/falkit/pricing.py",
                "scripts/split_sprites.py", "profiles/gpt-image/prompting.md", "profiles/remove-bg/profile.json",
                "references/pipelines.md"):
        assert (dest / rel).exists(), rel
    text = (dest / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\nname: (.+)\ndescription: \"(.+?)\"\n", text)
    assert m and m.group(1) == "fal-icons" and 0 < len(m.group(2)) <= 1024
    assert "{{" not in text and "## Running the steps" in text and "```template sheet" in text
    assert "≈ $0.0090" in text and ", optional)" in text
    with pytest.raises(FalkitError):
        workflows.export("icons", tmp_path / "skills", None, False)  # exists; needs --force


def test_keyframe_to_video_example_checks_and_plans(tmp_path):
    _real_profile("gpt-image")
    _real_profile("h3-max-i2v")
    workflows.init("kv", "user", "keyframe-to-video", False)
    rep = workflows.check("kv")
    assert rep["ok"] and rep["export_blockers"] == [], rep
    assert rep["pricing"]["video"]["estimate"]["usd"] == 0.4  # 768P draft x 5 s at the regular $0.08/s
    p = workflows.plan("kv", tmp_path / "out")
    video = p["steps"][2]
    assert "--template animate" in video["command"] and "--preset draft" in video["command"]
    assert video["fill"] == ["action", "camera", "preserve", "negatives"]
    assert video["optional_slots"] == ["sound", "speaker", "line"]
    assert "--preset hero" in p["steps"][0]["command"] and p["steps"][1]["type"] == "review"


def test_workflow_check_catches_structural_errors(tmp_path):
    d = workflows.init("bad", "user", None, False)
    wf = json.loads((d / "workflow.json").read_text(encoding="utf-8"))
    wf["steps"] = [
        {"id": "a", "type": "review"},
        {"id": "b", "type": "local", "command": "python scripts/missing.py {in:zzz}", "from": ["a"]},
        {"id": "B", "type": "magic"},
    ]
    (d / "workflow.json").write_text(json.dumps(wf), encoding="utf-8")
    errors = "\n".join(workflows.check("bad")["errors"])
    for needle in ("description is empty", "review step 'a'", "scripts/missing.py", "{in:zzz}", "id must be", "type must be"):
        assert needle in errors, needle


def test_workflow_export_needs_researched_templated_steps(tmp_path):
    _real_profile("gpt-image", status="unresearched")
    _real_profile("remove-bg")
    d = workflows.init("icons", "user", "sprite-sheet", False)
    rep = workflows.check("icons")
    assert rep["ok"] and any("gpt-image" in b and "unresearched" in b for b in rep["export_blockers"])
    with pytest.raises(FalkitError) as e:
        workflows.export("icons", tmp_path / "skills", None, False)
    assert "unresearched" in str(e.value)

    wf = json.loads((d / "workflow.json").read_text(encoding="utf-8"))
    wf["steps"][0]["template"] = "nope"
    (d / "workflow.json").write_text(json.dumps(wf), encoding="utf-8")
    assert any("template 'nope'" in e for e in workflows.check("icons")["errors"])
    wf["steps"][0]["template"] = "asset"  # falls back to the profile's own template
    wf["steps"][0]["slots"] = {"moood": "x"}
    (d / "workflow.json").write_text(json.dumps(wf), encoding="utf-8")
    assert any("'slots' names moood" in e for e in workflows.check("icons")["errors"])
    wf["steps"][0].pop("template")
    wf["steps"][0].pop("slots")
    (d / "workflow.json").write_text(json.dumps(wf), encoding="utf-8")
    rep = workflows.check("icons")
    assert any("no 'template'" in b for b in rep["export_blockers"])
    assert '"<prompt from WORKFLOW.md>"' in workflows.plan("icons", tmp_path / "out")["steps"][0]["command"]
    wf["steps"][2]["from"] = ["cutout"]
    (d / "workflow.json").write_text(json.dumps(wf), encoding="utf-8")
    assert any("optional step 'cutout' is skipped" in w for w in workflows.check("icons")["warnings"])


def test_exported_workflow_skill_runs_its_own_plan(tmp_path):
    _real_profile("gpt-image")
    _real_profile("remove-bg")
    workflows.init("sprite-sheet", "project", "sprite-sheet", False)
    dest = workflows.export("sprite-sheet", tmp_path / "skills", None, False)
    env = {**os.environ, "FAL_SKILLS_HOME": str(tmp_path / "empty-home")}  # only bundled profiles exist
    r = subprocess.run(
        [sys.executable, str(dest / "scripts" / "fal.py"), "workflow", "plan", "--json"],
        capture_output=True, text=True, env=env, cwd=tmp_path, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    plan = json.loads(r.stdout)
    assert plan["next"] == "sheet" and str(dest) in plan["steps"][2]["command"]
    assert f"{dest.resolve() / 'SKILL.md'}#sheet" in plan["steps"][0]["command"]  # templates travel in SKILL.md
    r = subprocess.run(
        [sys.executable, str(dest / "scripts" / "fal.py"), "profile", "list", "--json"],
        capture_output=True, text=True, env=env, cwd=tmp_path, encoding="utf-8", errors="replace")
    assert {p["slug"] for p in json.loads(r.stdout)} == {"gpt-image", "remove-bg"}


# --- split_sprites.py ------------------------------------------------------------------
def _split(*args: str) -> tuple[int, dict]:
    r = subprocess.run([sys.executable, str(SPLIT), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, json.loads(r.stdout)


def test_split_sprites_by_gaps_grid_and_color_key(tmp_path):
    sheet = _sheet(tmp_path / "s.png")
    code, out = _split(str(sheet), "--out", str(tmp_path / "a"), "--expect", "6")
    assert code == 0 and out["count"] == 6 and out["mode"] == "alpha" and out["dropped_specks"] == 1
    boxes = [p["box"] for p in out["pieces"]]
    assert boxes == sorted(boxes, key=lambda b: (b[1] // 100, b[0]))  # reading order: rows, then columns
    first = Image.open(out["pieces"][0]["file"])
    assert first.mode == "RGBA" and first.size == (56 + 16, 56 + 16) and first.getpixel((0, 0))[3] == 0

    code, out = _split(str(sheet), "--out", str(tmp_path / "b"), "--grid", "2x3", "--square")
    assert code == 0 and out["count"] == 6 and all(p["size"][0] == p["size"][1] for p in out["pieces"])

    flat = _sheet(tmp_path / "flat.png", alpha=False)
    code, out = _split(str(flat), "--out", str(tmp_path / "c"), "--expect", "6")
    assert code == 0 and out["mode"] == "color" and out["count"] == 6
    assert Image.open(out["pieces"][0]["file"]).getpixel((0, 0))[3] == 0  # keyed background is transparent

    code, out = _split(str(sheet), "--out", str(tmp_path / "d"), "--expect", "9")
    assert code == 3 and "expected 9" in out["warning"]


def test_split_sprites_staggered_layout_without_clean_gaps(tmp_path):
    # Real generations stagger assets: no empty row or column separates them, and bounding boxes overlap.
    im = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((20, 20, 160, 150), fill=(255, 0, 0, 255))  # A
    d.ellipse((140, 180, 300, 280), fill=(0, 255, 0, 255))  # B: below A and overlapping it horizontally
    d.polygon([(200, 20), (380, 20), (380, 210), (330, 210), (330, 70), (200, 70)], fill=(0, 0, 255, 255))  # C
    d.point((180, 100), fill=(255, 255, 0, 255))  # a speck, 20 px from A and C
    sheet = tmp_path / "stagger.png"
    im.save(sheet)
    code, out = _split(str(sheet), "--out", str(tmp_path / "s"), "--expect", "3", "--pad", "0")
    assert code == 0, out
    colors = []
    for p in out["pieces"]:
        piece = Image.open(p["file"])
        opaque = {px[:3] for _, px in piece.getcolors(1 << 16) if px[3] > 0}
        colors.append(opaque)
    assert all(len(c) == 1 for c in colors), colors  # each piece holds one asset only, no neighbor bleeding in
    assert [next(iter(c)) for c in colors] == [(255, 0, 0), (0, 0, 255), (0, 255, 0)]  # reading order


# --- MCP headers helper -------------------------------------------------------------------
def _headers(env: dict) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if k not in {"FAL_KEY", "FAL_KEY_ID", "FAL_KEY_SECRET", "BWS_ACCESS_TOKEN"}}
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "mcp_headers.py")], capture_output=True, text=True, env={**clean, **env}, encoding="utf-8", errors="replace")


def test_mcp_headers_helper():
    r = _headers({"FAL_KEY": "k-test"})
    assert r.returncode == 2 and r.stdout == ""  # refuses outside Claude Code: the key never reaches a transcript
    r = _headers({"FAL_KEY": "k-test", "CLAUDE_CODE_MCP_SERVER_NAME": "fal-ai"})
    assert r.returncode == 0 and json.loads(r.stdout) == {"Authorization": "Bearer k-test"}
    r = _headers({"CLAUDE_CODE_MCP_SERVER_NAME": "fal-ai"})
    assert r.returncode == 0 and json.loads(r.stdout) == {}  # no key → Claude Code falls back to OAuth


def test_plugin_manifest_mcp_server_uses_user_config_key():
    # fal disables OAuth dynamic client registration, and a plugin's headersHelper never sees credential env vars,
    # so the plugin's server must get its key from a sensitive userConfig option.
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    server = manifest["mcpServers"]["fal-ai"]
    assert server["url"] == "https://mcp.fal.ai/mcp" and "headersHelper" not in server
    assert server["headers"]["Authorization"] == "Bearer ${user_config.fal_api_key}"
    option = manifest["userConfig"]["fal_api_key"]
    assert option["sensitive"] is True and option["required"] is False
