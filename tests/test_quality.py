"""Offline tests for input quality: bundled guides, templates, pricing tables, wiring, and the research check.

The schema fixtures (tests/fixtures/schema-*.json) are the live schemas of the models the bundled guides cover,
so a guide that stops matching its model fails here. No network, no key, no cost.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "fal-skill-creator"
SCRIPTS = SKILL / "scripts"
GUIDES = SKILL / "assets" / "guides"
FIX = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

from falkit import pricing, profiles, runner, schema, templates  # noqa: E402
from falkit.core import FalkitError  # noqa: E402

INDEX = json.loads((GUIDES / "index.json").read_text(encoding="utf-8"))["guides"]
FIXTURES = {json.loads(p.read_text(encoding="utf-8"))["endpoint_id"]: p for p in FIX.glob("schema-*.json")}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FAL_SKILLS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    for v in ("FAL_PROFILES_DIR", "FAL_KEY", "FAL_KEY_ID", "FAL_KEY_SECRET", "BWS_ACCESS_TOKEN", "BWS_ACCESS_TOKEN_FILE"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(profiles, "url_status", lambda url: 200)


def _profile_from(endpoint: str, guide_text: str | None = None, slug: str | None = None) -> Path:
    compact = json.loads(FIXTURES[endpoint].read_text(encoding="utf-8"))
    entry = INDEX.get(endpoint, {})
    slug = slug or entry.get("slug") or profiles.slugify(endpoint)
    d = profiles.user_dir() / slug
    d.mkdir(parents=True)
    (d / "schema.json").write_text(json.dumps(compact), encoding="utf-8")
    (d / "defaults.json").write_text(json.dumps({**schema.schema_defaults(compact["input"]), **entry.get("recommend", {})}), encoding="utf-8")
    (d / "presets.json").write_text(json.dumps(entry.get("presets") or {}), encoding="utf-8")
    (d / "prompting.md").write_text(guide_text if guide_text is not None else (GUIDES / entry["file"]).read_text(), encoding="utf-8")
    (d / "profile.json").write_text(json.dumps({
        "slug": slug, "endpoint_id": endpoint, "category": compact["category"], "path": str(d),
        "prompt_field": schema.prompt_field(compact["input"]), "prompting_status": "researched",
        "pricing": {"unit_price": 1, "unit": "units"},
    }), encoding="utf-8")
    return d


# --- bundled guides -------------------------------------------------------------------
@pytest.mark.parametrize("endpoint", sorted(e for e in INDEX if e in FIXTURES))
def test_bundled_guide_passes_the_research_check_against_the_live_schema(endpoint):
    d = _profile_from(endpoint)
    rep = profiles.check(str(d), online=True)
    assert rep["errors"] == [], rep["errors"]
    assert rep["pricing"] and rep["pricing"]["checked"]
    for w in rep["warnings"]:  # only the "validate with a real run" and intended parameter-slot notes are allowed
        assert "not validated" in w or "take the request's parameter value" in w, w


def test_every_index_entry_points_at_a_file_and_real_presets():
    for endpoint, entry in INDEX.items():
        assert (GUIDES / entry["file"]).exists(), endpoint
        if endpoint in FIXTURES:
            props = json.loads(FIXTURES[endpoint].read_text(encoding="utf-8"))["input"]["properties"]
            for name, preset in (entry.get("presets") or {}).items():
                assert set(preset) <= set(props), (endpoint, name)
            assert set(entry.get("recommend") or {}) <= set(props), endpoint


def test_guide_prices_match_the_model_pages():
    gi = _profile_from("openai/gpt-image-2.5/sunburst/text-to-image")
    t = pricing.load(gi)
    s = json.loads(FIXTURES["openai/gpt-image-2.5/sunburst/text-to-image"].read_text(encoding="utf-8"))["input"]
    assert pricing.estimate(t, {"quality": "medium", "image_size": "square_hd"}, s)["usd"] == 0.01317
    hero = {"quality": "medium", "image_size": {"width": 1920, "height": 1088}}
    assert pricing.estimate(t, hero, s)["usd"] == 0.01029
    assert pricing.estimate(t, {"quality": "high", "image_size": "landscape_16_9", "num_images": 2}, s)["usd"] == 0.10536
    assert pricing.estimate(t, {"quality": "auto"}, s)["usd"] is None  # auto can't be priced; says so

    h3 = _profile_from("minimax/h3-max/image-to-video")
    t = pricing.load(h3)
    s = json.loads(FIXTURES["minimax/h3-max/image-to-video"].read_text(encoding="utf-8"))["input"]
    assert pricing.estimate(t, {"resolution": "1080P", "duration": 10}, s)["usd"] == 1.6
    assert pricing.estimate(t, {}, s)["usd"] == 0.4  # schema defaults: 768P, 5 s


# --- pricing blocks ------------------------------------------------------------------------
def test_pricing_block_parse_errors_are_clear():
    with pytest.raises(FalkitError, match="per:"):
        pricing.parse("```pricing\n480P: 0.05\n```\n")
    with pytest.raises(FalkitError, match="columns"):
        pricing.parse("```pricing\nper: image\nby: size\nsmall: 0.1 0.2\n```\n")
    with pytest.raises(FalkitError, match="not a price"):
        pricing.parse("```pricing\nper: image\n*: cheap\n```\n")
    t = pricing.parse("```pricing\nper: request\n*: 0.01\nchecked: 2026-09-30 https://fal.ai/models/x\n```\n")
    assert t["checked"] == "2026-09-30" and t["source"] == "https://fal.ai/models/x"
    assert pricing.estimate(t, {}, {})["usd"] == 0.01


def test_opaque_units():
    assert pricing.is_opaque("units") and pricing.is_opaque("compute seconds") and not pricing.is_opaque("images")


# --- templates -------------------------------------------------------------------------------
def test_optional_groups_drop_cleanly():
    body = "{subject} {action} in {setting}.[[ Camera: {camera_move}.]][[ Sound: {sound}.]] No text."
    assert templates.required_slots(body) == ["subject", "action", "setting"]
    assert templates.optional_slots(body) == ["camera_move", "sound"]
    text, _, _ = templates.render(body, {"subject": "A fox", "action": "runs", "setting": "snow"})
    assert text == "A fox runs in snow. No text."
    text, _, _ = templates.render(body, {"subject": "A fox", "action": "runs", "setting": "snow", "camera_move": "orbit"})
    assert text == "A fox runs in snow. Camera: orbit. No text."


def test_language_warning_spares_verbatim_text():
    body = 'Poster for {use}. Headline: "{headline}". Visual: {visual}. All text legible and correctly spelled.'
    _, _, warn = templates.render(body, {"use": "a cafe", "headline": "期間限定", "visual": "a latte"})
    assert warn == []
    _, _, warn = templates.render(body, {"use": "a cafe", "headline": "SALE", "visual": "木のテーブル"})
    assert warn and "visual" in warn[0]


def test_parameter_named_slots_follow_the_request():
    d = _profile_from("minimax/h3-max/image-to-video")
    prof = profiles.load(str(d))
    target = runner.Target(prof["endpoint_id"], prof["schema"]["input"], prof, prof["defaults"], prof["presets"])
    tpl = templates.load("product-reveal", prof)
    vals = {"product": "bottle", "motion": "turns", "camera": "orbit", "lighting": "soft", "sound": "hum"}
    plan = runner.prepare(target, {}, preset=None, sets=[("duration", 10)], prompt=None, from_refs=[],
                          uploader=runner.Uploader(dry_run=True), root=Path("out"), template=tpl, slot_values=vals,
                          quiet=True)
    assert plan.arguments["prompt"].startswith("10-second product video.") and plan.arguments["duration"] == 10
    with pytest.raises(FalkitError, match="is a model parameter"):
        runner.prepare(target, {}, preset=None, sets=[], prompt=None, from_refs=[], uploader=runner.Uploader(dry_run=True),
                       root=Path("out"), template=tpl, slot_values={**vals, "duration": 7}, quiet=True)


# --- runtime correctness on real schemas -------------------------------------------------------------
def test_media_kinds_on_real_schemas():
    r2v = {"reference_video_urls": {"type": "array"}, "reference_audio_urls": {"type": "array"},
           "reference_image_urls": {"type": "array"}, "first_frame_url": {"type": "string"}}
    kinds = {n: schema.media_kind_of_field(n, p) for n, p in r2v.items()}
    assert kinds == {"reference_video_urls": "video", "reference_audio_urls": "audio",
                     "reference_image_urls": "image", "first_frame_url": "image"}


def _mock(tmp_path: Path, label: str, n_images: int) -> None:
    imgs = []
    for i in range(n_images):
        f = tmp_path / f"{label}-{i}.png"
        Image.new("RGB", (32, 16)).save(f)
        imgs.append({"url": f.as_uri(), "content_type": "image/png"})
    target = runner.Target("fal-ai/x", {"type": "object", "properties": {}})
    opts = runner.RunOptions(root=tmp_path / "out", label=label, mock_result={"images": imgs})
    (tmp_path / "out").mkdir(exist_ok=True)
    runner.execute(target, runner.Plan(arguments={"prompt": label}), opts)


def test_one_from_fills_one_input(tmp_path):
    """A two-variant image run must not become the H3 start frame *and* end frame."""
    h3 = json.loads(FIXTURES["minimax/h3-max/image-to-video"].read_text(encoding="utf-8"))["input"]
    target = runner.Target("minimax/h3-max/image-to-video", h3)
    _mock(tmp_path, "variants", 2)
    _mock(tmp_path, "end", 1)
    up = runner.Uploader(dry_run=True)
    root = tmp_path / "out"
    plan = runner.Plan(arguments={"prompt": "x"})
    runner.autowire(plan.arguments, target, ["label:variants"], plan, up, root)
    assert plan.arguments["image_url"].endswith("variants-0.png") and "end_image_url" not in plan.arguments
    plan = runner.Plan(arguments={"prompt": "x"})
    runner.autowire(plan.arguments, target, ["label:variants#1", "label:end"], plan, up, root)
    assert plan.arguments["image_url"].endswith("variants-1.png")  # the chosen variant is the start frame
    assert plan.arguments["end_image_url"].endswith("end-0.png") and len(plan.wiring) == 2

    edit = json.loads(FIXTURES["openai/gpt-image-2.5/sunburst/edit"].read_text(encoding="utf-8"))["input"]
    t2 = runner.Target("openai/gpt-image-2.5/sunburst/edit", edit)
    plan = runner.Plan(arguments={"prompt": "x"})
    runner.autowire(plan.arguments, t2, ["label:variants"], plan, up, root)
    assert len(plan.arguments["image_urls"]) == 1 and "mask_url" not in plan.arguments  # never a variant as a mask
    plan = runner.Plan(arguments={"prompt": "x"})
    runner.autowire(plan.arguments, t2, ["label:variants#*"], plan, up, root)
    assert len(plan.arguments["image_urls"]) == 2


def test_sync_mode_is_always_off_unless_asked():
    s = {"type": "object", "properties": {"image_url": {"type": "string"}, "sync_mode": {"type": "boolean", "default": True}}}
    t = runner.Target("pixelcut/background-removal", s)
    assert runner.build_arguments(t)["sync_mode"] is False
    assert runner.build_arguments(t, sets=[("sync_mode", True)])["sync_mode"] is True


def test_probe_media_measures_images(tmp_path):
    f = tmp_path / "a.png"
    Image.new("RGBA", (40, 30)).save(f)
    assert runner.probe_media(f, "image") == {"width": 40, "height": 30}


# --- the research check can't be satisfied by a skeleton ---------------------------------------------
FAKE = """# guide
## Key rules
- be good [S1]
- be nice
- ok
## Templates
```template general
{x}
```
## Sources
- https://example.invalid/made-up-page
"""


def test_research_check_rejects_a_fake_guide(monkeypatch):
    d = _profile_from("openai/gpt-image-2.5/sunburst/text-to-image", FAKE, slug="fake")
    errors = "\n".join(profiles.check(str(d))["errors"])
    for needle in ("almost only slots", "fal's model page", "pricing"):
        assert needle in errors, needle
    monkeypatch.setattr(profiles, "url_status", lambda url: 404)
    guide = (GUIDES / "gpt-image-2.5-text-to-image.md").read_text(encoding="utf-8")
    d = _profile_from("openai/gpt-image-2.5/sunburst/text-to-image", guide, slug="dead-links")
    assert any("source doesn't exist (404)" in e for e in profiles.check(str(d), online=True)["errors"])


def test_research_check_requires_prompt_rewriting_to_be_addressed():
    guide = (GUIDES / "h3-max-image-to-video.md").read_text(encoding="utf-8").replace("prompt_expansion_mode", "the expansion setting")
    d = _profile_from("minimax/h3-max/image-to-video", guide, slug="h3-no-expansion")
    assert any("prompt_expansion_mode" in e for e in profiles.check(str(d))["errors"])


# --- CLI: validation must name a real run of this profile -----------------------------------------------
def _cli(*args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / "fal.py"), *args], capture_output=True, text=True,
                          env={**os.environ, **env}, encoding="utf-8", errors="replace")


def test_validated_with_must_be_a_templated_run_of_this_profile(tmp_path):
    _profile_from("openai/gpt-image-2.5/sunburst/text-to-image")
    img = tmp_path / "o.png"
    Image.new("RGB", (8, 8)).save(img)
    mock = tmp_path / "mock.json"
    mock.write_text(json.dumps({"images": [{"url": img.as_uri(), "content_type": "image/png"}]}), encoding="utf-8")
    env = {"FAL_KEY": "", "BWS_ACCESS_TOKEN": "", "BWS_ACCESS_TOKEN_FILE": "", "FAL_OUTPUT_DIR": str(tmp_path / "out"),
           "FAL_SKILLS_HOME": str(tmp_path / "home"), "XDG_CACHE_HOME": str(tmp_path / "cache")}
    r = _cli("run", "-p", "gpt-image", "--prompt", "a fox", "--mock", str(mock), "--label", "plain", env=env)
    assert r.returncode == 0, r.stderr
    r = _cli("profile", "meta", "gpt-image", "--validated-with", "label:plain", env=env)
    assert r.returncode == 2 and "--template" in r.stderr
    slots = ["--slot", "intended_use=Blog header", "--slot", "subject=a fox", "--slot", "details=orange fur",
             "--slot", "setting=snow"]
    r = _cli("run", "-p", "gpt-image", "-t", "general", *slots, "--mock", str(mock), "--label", "tpl", env=env)
    assert r.returncode == 0, r.stderr
    assert "price: ≈ $0.0090" in r.stderr  # default landscape_4_3 at the recommended medium quality
    r = _cli("profile", "meta", "gpt-image", "--validated-with", "label:tpl", "--json", env=env)
    assert r.returncode == 0 and json.loads(r.stdout)["validated_with"].endswith(tuple("0123456789abcdef"))


def test_template_lint_catches_what_breaks_real_requests():
    params = {"duration", "background"}
    assert templates.lint("A {subject} video. Background: {background}.", params)[0].startswith("{background}")
    assert "{=nope}" in templates.lint("A {subject}, {=nope} seconds.", params)[0]
    broken = templates.lint("{use}: {subject}. Setting: {setting}.[[ Style: {style}.]]", params)
    assert broken == []  # required slots can't be empty any more, so this renders cleanly
    dangling = templates.lint("{subject}.[[ Style: {style}]]. Camera:[[ {camera}]].", params)
    assert dangling and "broken text" in dangling[0]
    assert templates.lint("{=duration}-second clip of {subject}.[[ Sound: {sound}.]]", params) == []


def test_every_bundled_template_renders_cleanly_both_ways():
    for endpoint, entry in INDEX.items():
        if endpoint not in FIXTURES:
            continue
        props = set(json.loads(FIXTURES[endpoint].read_text(encoding="utf-8"))["input"]["properties"])
        for name, body in templates.parse((GUIDES / entry["file"]).read_text(encoding="utf-8")).items():
            assert templates.lint(body, props) == [], (entry["file"], name)


def test_quick_templates_are_short():
    for entry in INDEX.values():
        found = templates.parse((GUIDES / entry["file"]).read_text(encoding="utf-8"))
        if found:  # prompted models ship a `quick` template with at most 3 required slots
            assert "quick" in found and len(templates.required_slots(found["quick"])) <= 3, entry["file"]


def test_lower_bound_prices_say_so():
    d = _profile_from("openai/gpt-image-2.5/sunburst/edit")
    s = json.loads(FIXTURES["openai/gpt-image-2.5/sunburst/edit"].read_text(encoding="utf-8"))["input"]
    est = pricing.estimate(pricing.load(d), {"quality": "medium", "image_size": "auto"}, s)
    assert pricing.describe(est).startswith("≥ $0.0132")


def test_profile_init_seeds_from_the_library(monkeypatch):
    endpoint = "openai/gpt-image-2.5/sunburst/text-to-image"
    compact = json.loads(FIXTURES[endpoint].read_text(encoding="utf-8"))
    monkeypatch.setattr(profiles.schema, "fetch_openapi", lambda e: {"paths": {}})
    monkeypatch.setattr(profiles.schema, "compact", lambda doc, e: compact)
    monkeypatch.setattr(profiles.catalog, "get_model", lambda e: None)
    monkeypatch.setattr(profiles.catalog, "get_prices", lambda ids: {endpoint: {"unit_price": 1, "unit": "units"}})
    d = profiles.init(endpoint, None, "user", False)
    prof = profiles.load("gpt-image")
    assert d.name == "gpt-image" and prof["prompting_status"] == "researched"
    assert prof["defaults"]["quality"] == "medium"  # the researched default, not fal's 4x pricier `high`
    assert "hero" in prof["presets"] and prof["validated_with"].startswith("bundled: 2026-09-30")
    assert "status: researched" in (d / "prompting.md").read_text(encoding="utf-8")
    assert profiles.check("gpt-image")["warnings"] == []


def test_pricing_by_characters_of_text():
    t = pricing.parse("```pricing\nper: 1000 characters\ncount: chars(text)/1000\n*: 0.08\n```\n")
    est = pricing.estimate(t, {"text": "x" * 250}, {})
    assert est["usd"] == 0.02 and "250 chars/1000" in est["basis"]
