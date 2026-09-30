"""Offline tests for the falkit runtime. No network, no key, no cost.

Run:  make test   (or: uv run --with pytest --with fal-client --with httpx --with jsonschema pytest -q)
Live smoke test (costs ~$0.003): FAL_LIVE=1 make test
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "fal-skill-creator" / "scripts"
FIX = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

from falkit import export, profiles, runner, schema, templates  # noqa: E402
from falkit.core import FalkitError, parse_assignment, set_path  # noqa: E402


@pytest.fixture
def flux() -> dict:
    return schema.compact(json.loads((FIX / "openapi-flux-dev.json").read_text(encoding="utf-8")), "fal-ai/flux/dev")


@pytest.fixture
def kling() -> dict:
    ep = "fal-ai/kling-video/v2.1/standard/image-to-video"
    return schema.compact(json.loads((FIX / "openapi-kling-i2v.json").read_text(encoding="utf-8")), ep)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FAL_SKILLS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("FAL_PROFILES_DIR", raising=False)
    if not os.environ.get("FAL_LIVE"):  # offline means offline, even on a machine that has a key
        for v in ("FAL_KEY", "FAL_KEY_ID", "FAL_KEY_SECRET", "BWS_ACCESS_TOKEN"):
            monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(profiles, "url_status", lambda url: 200)  # source checks stay offline


# --- schema ---------------------------------------------------------------
def test_compact_inlines_refs_and_collapses_nullable(flux):
    props = flux["input"]["properties"]
    assert "$ref" not in json.dumps(flux)
    assert props["seed"]["type"] == ["integer", "null"]
    assert "prompt" in flux["input"]["required"]
    assert flux["output"]["properties"]["images"]["items"]["properties"]["url"]["type"] == "string"
    assert flux["category"] == "text-to-image"


def test_summary_and_media_detection(kling):
    rows = {r["name"]: r for r in schema.summarize(kling["input"])}
    assert rows["image_url"]["media_input"] == "image" and rows["image_url"]["required"]
    assert rows["duration"]["enum"] == ["5", "10"]
    assert "media_input" not in rows["prompt"]


def test_anyof_enum_surfaces_in_summary(flux):
    rows = {r["name"]: r for r in schema.summarize(flux["input"])}
    assert "landscape_16_9" in rows["image_size"]["enum"]


def test_defaults_skip_seed_and_sync_mode(flux):
    d = schema.schema_defaults(flux["input"])
    assert "seed" not in d and "sync_mode" not in d
    assert d["num_images"] == 1


def test_validate_reports_errors_and_unknown_keys(flux):
    errors, warnings = schema.validate({"prompt": "x", "num_images": 99, "typo": 1}, flux["input"])
    assert any("num_images" in e for e in errors)
    assert warnings == ["unknown parameter 'typo' (not in schema)"]
    errors, _ = schema.validate({"num_images": 2}, flux["input"])
    assert any("prompt" in e for e in errors)


def test_cli_value_coercion(kling, flux):
    assert schema.coerce_cli_value("duration", 10, kling["input"]) == "10"
    assert schema.coerce_cli_value("num_images", "2", flux["input"]) == 2
    assert schema.coerce_cli_value("prompt", "hello", flux["input"]) == "hello"


# --- prompt field -----------------------------------------------------------
def test_prompt_field_detection(flux, kling):
    assert schema.prompt_field(flux["input"]) == "prompt"
    tts = {"type": "object", "properties": {"text": {"type": "string"}, "voice": {"type": "string"}}}
    assert schema.prompt_field(tts) == "text"
    assert schema.prompt_field({"type": "object", "properties": {"image_url": {"type": "string"}}}) is None
    t = runner.Target("fal-ai/tts", tts)
    assert runner.build_arguments(t, prompt="hello") == {"text": "hello"}
    with_default = {"type": "object", "properties": {"prompt": {"type": "string", "default": "a cat"}}}
    assert "prompt" not in schema.schema_defaults(with_default)  # a default prompt must never stand in for one


# --- templates ------------------------------------------------------------
GUIDE = """# Input guide
## Templates

```template product
{subject} on {surface}, {lighting}. {style}.
```

~~~template literal
JSON-ish {{braces}} stay, {subject} fills
~~~
"""


def test_template_parse_and_render():
    found = templates.parse(GUIDE)
    assert list(found) == ["product", "literal"]
    assert templates.slots(found["product"]) == ["subject", "surface", "lighting", "style"]
    text, unused, _ = templates.render(
        found["product"], {"subject": "a bottle", "surface": "slate", "lighting": "softbox", "style": "photo", "x": 1}
    )
    assert text == "a bottle on slate, softbox. photo." and unused == ["x"]
    # a required slot can't be left empty: that part of the template would dangle
    with pytest.raises(FalkitError, match="given empty"):
        templates.render(found["product"], {"subject": "a bottle", "surface": "slate", "lighting": "", "style": ""})
    text, _, _ = templates.render(found["literal"], {"subject": ["a", "b"]})
    assert text == "JSON-ish {braces} stay, a, b fills"
    with pytest.raises(FalkitError) as e:
        templates.render(found["product"], {"subject": "x"})
    assert e.value.code == 2 and "surface" in str(e.value)


def test_legacy_template_headings_still_parse():
    legacy = "## Templates\n\n### general\n```text\n{subject}, {style}.\n```\nwhen\n\n## Parameters\n"
    assert templates.parse(legacy) == {"general": "{subject}, {style}."}


# --- prompting.md check ------------------------------------------------------
RESEARCHED = """<!--
status: unresearched
researched_at:
-->
# Input guide: FLUX dev

## Key rules
- Write prose, subject first [S1].
- Quote on-screen text [S1].
- Put style last [S2].

## Prompt structure
Subject, then action, then setting.

## Templates

```template general
Editorial photograph: {subject}, {action}, {setting}. Natural light, true colors.[[ Style: {style}.]]
```

## Parameters that matter

| parameter | when to change | recommended |
|---|---|---|
| guidance_scale | literal prompts | 3.5 |

## Sources
- [S1] FLUX guide — https://docs.bfl.ai/guides/prompting — official — accessed 2026-09-30
- [S2] fal model page — https://fal.ai/models/fal-ai/flux/dev — fal — accessed 2026-09-30
"""


def _hand_profile(tmp_path: Path, compact: dict, slug: str = "flux-dev", guide: str | None = None) -> Path:
    d = tmp_path / "home" / "profiles" / slug
    d.mkdir(parents=True)
    (d / "schema.json").write_text(json.dumps(compact), encoding="utf-8")
    (d / "defaults.json").write_text(json.dumps(schema.schema_defaults(compact["input"])), encoding="utf-8")
    (d / "profile.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "endpoint_id": compact["endpoint_id"],
                "display_name": slug,
                "category": compact.get("category"),
                "pricing": {"unit_price": 0.025, "unit": "megapixels"},
                "prompting_status": "unresearched",
            }
        ), encoding="utf-8")
    stub = (SCRIPTS.parent / "assets" / "prompting.template.md").read_text(encoding="utf-8")
    (d / "prompting.md").write_text(guide if guide is not None else stub, encoding="utf-8")
    return d


def test_profile_check_gates_researched_status(tmp_path, flux):
    d = _hand_profile(tmp_path, flux)
    rep = profiles.check("flux-dev")
    assert any("Not researched yet" in e for e in rep["errors"])
    assert any("Key rules" in e for e in rep["errors"]) and any("Sources" in e for e in rep["errors"])
    with pytest.raises(FalkitError) as e:
        profiles.set_meta("flux-dev", prompting_status="researched")
    assert e.value.code == 2

    (d / "prompting.md").write_text(RESEARCHED, encoding="utf-8")
    rep = profiles.check("flux-dev")
    assert rep["errors"] == [], rep["errors"]
    assert rep["templates"] == {"general": ["subject", "action", "setting", "style"]}
    assert any("not validated" in w for w in rep["warnings"])
    prof = profiles.set_meta("flux-dev", prompting_status="researched", validated_with="run-1")
    assert prof["prompting_status"] == "researched" and "cost_guard" not in prof
    head = (d / "prompting.md").read_text(encoding="utf-8")
    assert "status: researched" in head and re.search(r"researched_at: \d{4}-\d{2}-\d{2}", head)
    assert not any("not validated" in w for w in profiles.check("flux-dev")["warnings"])


def test_profile_check_requires_inputs_section_for_media_models(tmp_path, kling):
    _hand_profile(tmp_path, kling, "kling", RESEARCHED)
    errors = profiles.check("kling")["errors"]
    assert any("Inputs" in e and "image_url" in e for e in errors)
    _hand_profile(tmp_path, kling, "kling2", RESEARCHED.replace("## Templates", "## Inputs\n- image_url: 16:9 PNG\n\n## Templates"))
    assert profiles.check("kling2")["errors"] == []


def test_export_refuses_unresearched_profile_and_uses_description(tmp_path, flux):
    d = _hand_profile(tmp_path, flux)
    with pytest.raises(FalkitError):
        export.export("flux-dev", tmp_path / "skills", None, False)
    (d / "prompting.md").write_text(RESEARCHED, encoding="utf-8")
    profiles.set_meta("flux-dev", prompting_status="researched")
    dest = export.export("flux-dev", tmp_path / "skills", None, False, "Blog header images in 16:9 for our team.")
    text = (dest / "SKILL.md").read_text(encoding="utf-8")
    assert 'description: "Blog header images in 16:9 for our team."' in text
    assert "`general`: `subject`, `action`, `setting`; optional `style`" in text and "{{" not in text
    assert "cost guard" not in text.lower()


# --- runner ---------------------------------------------------------------
def test_extract_files_handles_any_shape():
    result = {
        "images": [{"url": "https://x/a.png", "content_type": "image/png"}, {"url": "https://x/b.png"}],
        "video": {"url": "https://x/v.mp4"},
        "nested": {"audio_file": {"url": "data:audio/wav;base64,AAAA", "content_type": "audio/wav"}},
        "seed": 1,
    }
    fields = [f["field"] for f in runner.extract_files(result)]
    assert fields == ["images.0", "images.1", "video", "nested.audio_file"]


def test_merge_order_and_coercion(kling):
    t = runner.Target(
        "ep", kling["input"], defaults={"duration": "5", "cfg_scale": 0.5}, presets={"long": {"duration": "10"}}
    )
    args = runner.build_arguments(t, preset="long", input_obj={"cfg_scale": 0.7}, sets=[("duration", 5)], prompt="p")
    assert args == {"duration": "5", "cfg_scale": 0.7, "prompt": "p"}
    with pytest.raises(FalkitError):
        runner.build_arguments(t, preset="missing")


def _mock_run(tmp_path: Path, name: str, result: dict) -> dict:
    target = runner.Target("fal-ai/test", {"type": "object", "properties": {}})
    opts = runner.RunOptions(root=tmp_path / "out", label=name, mock_result=result)
    (tmp_path / "out").mkdir(exist_ok=True)
    return runner.execute(target, runner.Plan(arguments={"prompt": name}), opts)


def test_mock_run_writes_manifest_and_index(tmp_path):
    src = tmp_path / "src.png"
    src.write_bytes(b"\x89PNG fake")
    m = _mock_run(tmp_path, "one", {"images": [{"url": src.as_uri(), "content_type": "image/png"}], "seed": 42})
    assert m["format"] == "fal-manifest@1" and m["seed"] == 42
    out = m["outputs"][0]
    assert out["kind"] == "image" and Path(out["local_path"]).read_bytes() == b"\x89PNG fake"
    assert out["local_path"].endswith("images-0.png")
    idx = (tmp_path / "out" / "index.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(idx[-1])["run_id"] == m["run_id"]


def test_data_uri_output_is_decoded(tmp_path):
    m = _mock_run(tmp_path, "b64", {"audio": {"url": "data:audio/wav;base64,UklGRg==", "content_type": "audio/wav"}})
    out = m["outputs"][0]
    assert out["url"] is None and out["local_path"].endswith(".wav")
    assert Path(out["local_path"]).read_bytes() == b"RIFF"


def test_refs_and_autowire(tmp_path, kling):
    img = tmp_path / "k.png"
    img.write_bytes(b"img")
    first = _mock_run(tmp_path, "key", {"images": [{"url": img.as_uri(), "content_type": "image/png"}]})
    root = tmp_path / "out"
    mpath, manifest = runner.load_manifest("last", root)
    assert manifest["run_id"] == first["run_id"]

    target = runner.Target("fal-ai/kling", kling["input"])
    uploader = runner.Uploader(dry_run=True)  # dry-run: URLs are trusted, local uploads become placeholders
    plan = runner.Plan(arguments={"prompt": "move"})
    runner.autowire(plan.arguments, target, ["last"], plan, uploader, root)
    assert plan.arguments["image_url"] == img.as_uri()
    assert plan.parents == [str(mpath)]

    args = {"image_url": "from:last#image", "tail": "@" + str(img)}
    plan2 = runner.Plan(arguments=args)
    runner.resolve_values(args, plan2, uploader, root)
    assert args["image_url"] == img.as_uri()
    assert args["tail"] == f"<upload:{img}>"


def test_explicit_set_wins_over_autowire(tmp_path, kling):
    img = tmp_path / "k.png"
    img.write_bytes(b"img")
    _mock_run(tmp_path, "key", {"images": [{"url": img.as_uri(), "content_type": "image/png"}]})
    target = runner.Target("fal-ai/kling", kling["input"])
    plan = runner.Plan(arguments={"prompt": "x", "image_url": "https://mine/explicit.png"})
    runner.autowire(plan.arguments, target, ["last"], plan, runner.Uploader(dry_run=True), tmp_path / "out")
    assert plan.arguments["image_url"] == "https://mine/explicit.png"


def test_manual_manifest_with_local_only_output(tmp_path):
    img = tmp_path / "ext.png"
    img.write_bytes(b"x")
    mf = tmp_path / "ext.json"
    mf.write_text(
        json.dumps(
            {
                "format": "fal-manifest@1",
                "run_id": "ext-1",
                "outputs": [{"kind": "image", "local_path": str(img), "url": None}],
            }
        ), encoding="utf-8")
    args = {"image_url": f"from:{mf}"}
    runner.resolve_values(args, runner.Plan(arguments=args), runner.Uploader(dry_run=True), tmp_path)
    assert args["image_url"] == f"<upload:{img}>"


# --- profiles & core ------------------------------------------------------
def test_slugify():
    assert profiles.slugify("fal-ai/flux/dev") == "flux-dev"
    assert profiles.slugify("blackforestlabs/flux-3/edit-video") == "blackforestlabs-flux-3-edit-video"
    assert (
        profiles.slugify("fal-ai/kling-video/v2.1/standard/image-to-video")
        == "kling-video-v2-1-standard-image-to-video"
    )


def test_assignments_and_set_path():
    assert parse_assignment("n=2") == ("n", 2)
    assert parse_assignment("p=hello world") == ("p", "hello world")
    assert parse_assignment('l=["a"]') == ("l", ["a"])
    d: dict = {}
    set_path(d, "image_size.width", 768)
    assert d == {"image_size": {"width": 768}}


def test_key_resolution_env_first(monkeypatch):
    from falkit import auth as core

    monkeypatch.setattr(core, "_key_cache", None)
    monkeypatch.setenv("FAL_KEY", "abc")
    assert core.resolve_key() == "abc" and core.key_source() == "env FAL_KEY"
    monkeypatch.setattr(core, "_key_cache", None)
    monkeypatch.delenv("FAL_KEY")
    monkeypatch.setenv("FAL_KEY_ID", "i")
    monkeypatch.setenv("FAL_KEY_SECRET", "s")
    assert core.resolve_key() == "i:s"


def test_missing_key_is_auth_error(monkeypatch):
    from falkit import auth as core

    monkeypatch.setattr(core, "_key_cache", None)
    for v in ("FAL_KEY", "FAL_KEY_ID", "FAL_KEY_SECRET", "BWS_ACCESS_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(FalkitError) as e:
        core.resolve_key()
    assert e.value.code == core.EXIT_AUTH


# --- CLI end-to-end (offline, via --mock) ----------------------------------
def _cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "fal.py"), *args],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        encoding="utf-8",
        errors="replace",
    )


def test_cli_profile_from_fixture_and_mock_run(tmp_path, flux):
    # Build a profile by hand from the fixture (profile init needs network).
    _hand_profile(tmp_path, flux, guide=RESEARCHED)
    img = tmp_path / "o.png"
    img.write_bytes(b"png")
    mock = tmp_path / "mock.json"
    mock.write_text(json.dumps({"images": [{"url": img.as_uri(), "content_type": "image/png"}], "seed": 3}), encoding="utf-8")
    env = {"FAL_KEY": "", "BWS_ACCESS_TOKEN": "", "FAL_OUTPUT_DIR": str(tmp_path / "out")}

    r = _cli("profile", "list", "--json", env=env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)[0]["slug"] == "flux-dev"

    r = _cli("run", "-p", "flux-dev", "--prompt", "fox", "--mock", str(mock), "--json", env=env)
    assert r.returncode == 0, r.stderr
    m = json.loads(r.stdout)
    assert m["arguments"]["prompt"] == "fox" and m["outputs"][0]["kind"] == "image"

    r = _cli("run", "-p", "flux-dev", "--set", "num_images=9", "--prompt", "x", "--json", env=env)
    assert r.returncode == 2 and "num_images" in json.loads(r.stdout)["error"]

    r = _cli("runs", "show", "last", "--json", env=env)
    assert json.loads(r.stdout)["run_id"] == m["run_id"]

    # Templates: rendered into the prompt field, recorded in the manifest, missing slots refused.
    slots = ["--slot", "subject=a red fox", "--slot", "action=sleeping", "--slot", "setting=in snow"]
    r = _cli("run", "-p", "flux-dev", "-t", "general", *slots, "--mock", str(mock), "--json", env=env)
    assert r.returncode == 0, r.stderr
    m = json.loads(r.stdout)
    assert m["arguments"]["prompt"] == "Editorial photograph: a red fox, sleeping, in snow. Natural light, true colors."
    assert m["prompt_template"]["name"] == "general" and "style" not in m["prompt_template"]["slots"]
    assert m["pricing"]["unit"] == "megapixels" and "cost_estimate" not in m
    assert "prompting is unresearched" in r.stderr  # the run works, but says the guide isn't vetted
    r = _cli("run", "-p", "flux-dev", "-t", "general", "--slot", "subject=x", "--dry-run", "--json", env=env)
    assert r.returncode == 2 and "action" in json.loads(r.stdout)["error"]
    r = _cli("run", "-p", "flux-dev", "-t", "general", *slots, "--slot", "moood=calm", "--dry-run", "--json", env=env)
    assert r.returncode == 2 and "moood" in json.loads(r.stdout)["error"]  # a typo never silently drops intent
    r = _cli("run", "-p", "flux-dev", "-t", "general", *slots, "--slot", "num_images=2", "--dry-run", "--json", env=env)
    assert r.returncode == 2 or "num_images" not in r.stdout  # parameters are --set, not --slot
    r = _cli("run", "-p", "flux-dev", "-t", "nope", "--dry-run", "--json", env=env)
    assert r.returncode == 2 and "general" in json.loads(r.stdout)["hint"]
    r = _cli("run", "-p", "flux-dev", "--prompt", "x", "--yes", "--max-cost", "5", "--dry-run", "--json", env=env)
    assert r.returncode == 0 and "ignored" in r.stderr  # retired flags don't break old scripts


@pytest.mark.skipif(not os.environ.get("FAL_LIVE"), reason="set FAL_LIVE=1 to run against fal (costs ~$0.003)")
def test_live_flux_schnell(tmp_path):
    env = {"FAL_OUTPUT_DIR": str(tmp_path / "out")}
    r = _cli(
        "run",
        "-e",
        "fal-ai/flux/schnell",
        "--prompt",
        "a red apple on a table",
        "--set",
        "image_size=square",
        "--json",
        env=env,
    )
    assert r.returncode == 0, r.stderr
    m = json.loads(r.stdout)
    assert Path(m["outputs"][0]["local_path"]).stat().st_size > 1000


def test_no_upload_until_every_request_is_valid(tmp_path, kling, monkeypatch):
    img = tmp_path / "private.png"
    img.write_bytes(b"secret-ish")
    calls = []
    monkeypatch.setattr(runner.Uploader, "_client_", lambda self: calls.append("client") or None)
    target = runner.Target("fal-ai/kling", kling["input"])
    opts = runner.RunOptions(root=tmp_path / "out")
    with pytest.raises(FalkitError) as e:
        runner.run_many(
            target,
            [{}, {"duration": "7"}],  # the second request is invalid
            preset=None,
            sets=[("image_url", "@" + str(img))],
            prompt="x",
            from_refs=[],
            opts=opts,
            dry_run=False,
            concurrency=1,
        )
    assert e.value.code == 2 and calls == []


def test_fetch_refuses_a_run_fal_never_accepted(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    (d / "request.json").write_text(json.dumps({"run_id": "r", "status": "rejected", "error": "bad duration"}), encoding="utf-8")
    with pytest.raises(FalkitError) as e:
        runner.fetch(d, tmp_path, 1)
    assert e.value.code == 2 and "bad duration" in e.value.hint


def test_prompting_stub_matches_the_kind_of_model(tmp_path):
    cases = {
        ("text-to-speech", "text"): ["script"],
        ("image-to-video", "prompt"): ["subject", "action", "setting", "camera_move", "style"],
        ("text-to-image", "prompt"): ["subject", "action", "setting", "style", "composition", "lighting"],
        ("image-to-image", None): None,  # background removal: no text input, no template
    }
    for (category, field), expected in cases.items():
        path = tmp_path / f"{category}.md"
        profiles._write_prompting_stub(path, {"endpoint_id": "x", "category": category, "prompt_field": field})
        found = templates.parse(path.read_text(encoding="utf-8"))
        assert (templates.slots(found["general"]) if found else None) == expected, category


@pytest.mark.skipif(os.name == "nt", reason="fake bws is a POSIX shell script")
def test_bws_retries_transient_errors(tmp_path, monkeypatch):
    from falkit import auth

    counter = tmp_path / "calls"
    fake = tmp_path / "bws"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo x >> "{counter}"\n'
        f'if [ "$(wc -l < "{counter}")" -lt 2 ]; then echo "[503 Service Unavailable] upstream" >&2; exit 1; fi\n'
        """echo '[{"id": "abcdef1234", "key": "FAL_KEY", "value": "k-bws"}]'\n""", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "t")
    monkeypatch.setattr(auth, "_key_cache", None)
    monkeypatch.setattr(auth.time, "sleep", lambda s: None)
    assert auth.resolve_key() == "k-bws"
    assert counter.read_text(encoding="utf-8").count("x") == 2
