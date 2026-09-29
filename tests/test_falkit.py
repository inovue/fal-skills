"""Offline tests for the falkit runtime. No network, no key, no cost.

Run:  make test   (or: uv run --with pytest --with fal-client --with httpx --with jsonschema pytest -q)
Live smoke test (costs ~$0.003): FAL_LIVE=1 make test
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "fal-skill-creator" / "scripts"
FIX = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

from falkit import cost, profiles, runner, schema  # noqa: E402
from falkit.core import FalkitError, parse_assignment, set_path  # noqa: E402


@pytest.fixture
def flux() -> dict:
    return schema.compact(json.loads((FIX / "openapi-flux-dev.json").read_text()), "fal-ai/flux/dev")


@pytest.fixture
def kling() -> dict:
    ep = "fal-ai/kling-video/v2.1/standard/image-to-video"
    return schema.compact(json.loads((FIX / "openapi-kling-i2v.json").read_text()), ep)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FAL_SKILLS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("FAL_PROFILES_DIR", raising=False)
    monkeypatch.delenv("FAL_MAX_COST", raising=False)
    monkeypatch.chdir(tmp_path)


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


# --- cost -----------------------------------------------------------------
def test_cost_megapixels(flux):
    e = cost.estimate(
        {"unit_price": 0.025, "unit": "megapixels"}, {"image_size": "square_hd", "num_images": 2}, flux["input"]
    )
    assert e["confidence"] == "high" and e["usd"] == pytest.approx(0.025 * 1.05 * 2)


def test_cost_seconds_uses_schema_default(kling):
    e = cost.estimate({"unit_price": 0.056, "unit": "seconds"}, {}, kling["input"])
    assert e["usd"] == pytest.approx(0.28)
    e = cost.estimate({"unit_price": 0.056, "unit": "seconds"}, {"duration": "10"}, kling["input"])
    assert e["usd"] == pytest.approx(0.56)


def test_cost_guard_blocks_and_limits(monkeypatch):
    ok, _ = cost.guard({"usd": 0.5}, 1.0)
    assert ok
    ok, reason = cost.guard({"usd": 2.0}, 1.0)
    assert not ok and "exceeds" in reason
    assert cost.guard({"usd": None, "unit_price": 0.01, "unit": "tokens"}, 1.0)[0]
    assert not cost.guard({"usd": None, "unit_price": 0.5, "unit": "tokens"}, 1.0)[0]
    monkeypatch.setenv("FAL_MAX_COST", "3")
    assert cost.max_usd(None, None) == 3.0
    assert cost.max_usd(None, {"cost_guard": {"max_usd": 7}}) == 7.0
    assert cost.max_usd(0.5, {"cost_guard": {"max_usd": 7}}) == 0.5


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
    return runner.execute(target, runner.Plan(arguments={"prompt": name}), {"usd": 0}, opts)


def test_mock_run_writes_manifest_and_index(tmp_path):
    src = tmp_path / "src.png"
    src.write_bytes(b"\x89PNG fake")
    m = _mock_run(tmp_path, "one", {"images": [{"url": src.as_uri(), "content_type": "image/png"}], "seed": 42})
    assert m["format"] == "fal-manifest@1" and m["seed"] == 42
    out = m["outputs"][0]
    assert out["kind"] == "image" and Path(out["local_path"]).read_bytes() == b"\x89PNG fake"
    assert out["local_path"].endswith("images-0.png")
    idx = (tmp_path / "out" / "index.jsonl").read_text().splitlines()
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
        )
    )
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
    from falkit import core

    monkeypatch.setattr(core, "_key_cache", None)
    monkeypatch.setenv("FAL_KEY", "abc")
    assert core.resolve_key() == "abc" and core.key_source() == "env FAL_KEY"
    monkeypatch.setattr(core, "_key_cache", None)
    monkeypatch.delenv("FAL_KEY")
    monkeypatch.setenv("FAL_KEY_ID", "i")
    monkeypatch.setenv("FAL_KEY_SECRET", "s")
    assert core.resolve_key() == "i:s"


def test_missing_key_is_auth_error(monkeypatch):
    from falkit import core

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
    )


def test_cli_profile_from_fixture_and_mock_run(tmp_path, flux):
    # Build a profile by hand from the fixture (profile init needs network).
    d = tmp_path / "home" / "profiles" / "flux-dev"
    d.mkdir(parents=True)
    (d / "schema.json").write_text(json.dumps(flux))
    (d / "defaults.json").write_text(json.dumps(schema.schema_defaults(flux["input"])))
    (d / "profile.json").write_text(
        json.dumps(
            {
                "slug": "flux-dev",
                "endpoint_id": "fal-ai/flux/dev",
                "pricing": {"unit_price": 0.025, "unit": "megapixels"},
            }
        )
    )
    img = tmp_path / "o.png"
    img.write_bytes(b"png")
    mock = tmp_path / "mock.json"
    mock.write_text(json.dumps({"images": [{"url": img.as_uri(), "content_type": "image/png"}], "seed": 3}))
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


def test_no_upload_before_cost_guard(tmp_path, kling, monkeypatch):
    img = tmp_path / "private.png"
    img.write_bytes(b"secret-ish")
    calls = []
    monkeypatch.setattr(runner.Uploader, "_client_", lambda self: calls.append("client") or None)
    monkeypatch.setattr(runner, "price_for", lambda t: {"unit_price": 0.056, "unit": "seconds"})
    target = runner.Target("fal-ai/kling", kling["input"])
    opts = runner.RunOptions(root=tmp_path / "out")
    with pytest.raises(FalkitError) as e:
        runner.run_many(
            target,
            [{}],
            preset=None,
            sets=[("image_url", "@" + str(img))],
            prompt="x",
            from_refs=[],
            opts=opts,
            max_cost=0.01,
            assume_yes=False,
            dry_run=False,
            concurrency=1,
        )
    assert e.value.code == 3 and calls == []
