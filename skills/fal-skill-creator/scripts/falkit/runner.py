"""Run a fal endpoint: build (template → prompt) → validate → upload → submit → wait → save.

Every run lands in its own directory with the media files, the raw result and
a `manifest.json` — the contract other runs (and other skills) consume to
chain generations into pipelines. See references/pipelines.md.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from . import __version__, pricing, profiles, schema, templates
from .core import (
    EXIT_API,
    EXIT_TIMEOUT,
    EXIT_USAGE,
    USER_AGENT,
    FalkitError,
    cache_dir,
    log,
    now_iso,
    read_json,
    resolve_key,
    set_path,
    truncate,
    write_json,
)

MANIFEST_FORMAT = "fal-manifest@1"
_print_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Target resolution: a profile, or a bare endpoint id (schema fetched + cached)
# ---------------------------------------------------------------------------
@dataclass
class Target:
    endpoint_id: str
    input_schema: dict
    profile: dict | None = None
    defaults: dict = field(default_factory=dict)
    presets: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.profile["slug"] if self.profile else profiles.slugify(self.endpoint_id)

    @property
    def prompt_field(self) -> str:
        return (self.profile or {}).get("prompt_field") or schema.prompt_field(self.input_schema) or "prompt"


def resolve_target(profile_ref: str | None, endpoint_id: str | None) -> Target:
    if profile_ref:
        p = profiles.load(profile_ref)
        return Target(p["endpoint_id"], p["schema"]["input"], p, p["defaults"], p["presets"])
    if not endpoint_id:
        raise FalkitError("Pass --profile or --endpoint", EXIT_USAGE)
    cached = cache_dir() / "schemas" / (profiles.slugify(endpoint_id) + ".json")
    if cached.exists() and time.time() - cached.stat().st_mtime < 86400:
        compact = read_json(cached)
    else:
        compact = schema.compact(schema.fetch_openapi(endpoint_id), endpoint_id)
        write_json(cached, compact)
    return Target(endpoint_id, compact["input"])


# ---------------------------------------------------------------------------
# Run references (for --from and from:REF values)
# ---------------------------------------------------------------------------
def index_path(root: Path) -> Path:
    return root / "index.jsonl"


def _index_entries(root: Path) -> list[dict]:
    p = index_path(root)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def load_manifest(ref: str, root: Path) -> tuple[Path, dict]:
    """Resolve 'last', 'last~N', 'label:TAG', 'label:TAG~N', a run id, a run dir, or a manifest path."""
    p = Path(ref).expanduser()
    if p.is_dir() and (p / "manifest.json").exists():
        return p / "manifest.json", read_json(p / "manifest.json")
    if p.is_file():
        return p, read_json(p)
    entries = _index_entries(root)
    m = re.fullmatch(r"(?:label:(?P<label>[^~]+)|last)(?:~(?P<back>\d+))?", ref)
    if m:
        if m.group("label"):  # workflow steps refer to each other by label, not by position
            entries = [e for e in entries if e.get("label") == m.group("label")]
        back = int(m.group("back") or 0)
        if len(entries) <= back:
            raise FalkitError(
                f"No run {ref!r} in {index_path(root)}", EXIT_USAGE, hint="Use `fal.py runs list` to see labels."
            )
        mp = (root / entries[-1 - back]["manifest"]).resolve()
        return mp, read_json(mp)
    for e in reversed(entries):
        if e.get("run_id") == ref:
            mp = (root / e["manifest"]).resolve()
            return mp, read_json(mp)
    raise FalkitError(f"Cannot resolve run reference {ref!r}", EXIT_USAGE, hint="Use `fal.py runs list`.")


def _select_output(manifest: dict, selector: str | None) -> list[dict]:
    outs = manifest.get("outputs") or []
    if not outs:
        raise FalkitError(f"Run {manifest.get('run_id')} has no file outputs", EXIT_USAGE)
    if selector is None:
        return [outs[0]]
    if selector == "*":
        return outs
    if selector.isdigit():
        i = int(selector)
        if i >= len(outs):
            raise FalkitError(f"Run {manifest.get('run_id')} has only {len(outs)} outputs", EXIT_USAGE)
        return [outs[i]]
    picked = [o for o in outs if o.get("kind") == selector or o.get("field") == selector]
    if not picked:
        raise FalkitError(f"No output matching {selector!r} in run {manifest.get('run_id')}", EXIT_USAGE)
    return picked


# ---------------------------------------------------------------------------
# Uploads (local files → fal CDN). Cached by content hash for a day.
# ---------------------------------------------------------------------------
class Uploader:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._client = None
        self._cache_path = cache_dir() / "uploads.json"
        try:
            self._cache = read_json(self._cache_path)
        except (FileNotFoundError, json.JSONDecodeError):
            self._cache = {}

    def _client_(self):
        if self._client is None:
            import fal_client

            self._client = fal_client.SyncClient(key=resolve_key())
        return self._client

    def upload(self, path: Path) -> str:
        path = Path(path).expanduser()
        if not path.is_file():
            raise FalkitError(f"Input file not found: {path}", EXIT_USAGE)
        if self.dry_run:
            return f"<upload:{path}>"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hit = self._cache.get(digest)
        if hit and time.time() - hit["at"] < 86400:
            return hit["url"]
        log(f"Uploading {path} …")
        url = self._client_().upload_file(path)
        self._cache[digest] = {"url": url, "at": time.time()}
        write_json(self._cache_path, self._cache)
        return url


def _url_alive(url: str) -> bool:
    try:
        r = httpx.head(url, timeout=10, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        return r.status_code < 400
    except httpx.HTTPError:
        return False


def _output_to_url(o: dict, uploader: Uploader) -> str:
    """Prefer the hosted URL (no re-upload); fall back to uploading the saved local copy."""
    url = o.get("url")
    if url and (uploader.dry_run or _url_alive(url)):
        return url
    if o.get("local_path") and Path(o["local_path"]).exists():
        return uploader.upload(Path(o["local_path"]))
    raise FalkitError(f"Output {o.get('field')} is no longer reachable and has no local copy", EXIT_USAGE)


# ---------------------------------------------------------------------------
# Argument building
# ---------------------------------------------------------------------------
@dataclass
class Plan:
    arguments: dict
    input_sources: dict = field(default_factory=dict)  # field → local path / run ref it came from
    parents: list = field(default_factory=list)  # manifest paths this run consumed
    wiring: list = field(default_factory=list)  # human-readable autowire notes
    prompt_template: dict | None = None  # {name, source, slots} when the prompt came from a template
    price_estimate: dict | None = None  # from the profile's researched pricing table


def build_arguments(
    target: Target,
    *,
    preset: str | None = None,
    input_obj: dict | None = None,
    sets: list[tuple[str, Any]] = (),
    prompt: str | None = None,
) -> dict:
    """Merge order (later wins): profile defaults < preset < --input < --set < --prompt (into the prompt field)."""
    args: dict = json.loads(json.dumps(target.defaults))
    if "sync_mode" in (target.input_schema.get("properties") or {}):
        # Some endpoints default to sync_mode=true (base64 in the response, nothing in fal's history, no URL to
        # chain from). Ask for hosted URLs unless a caller explicitly says otherwise.
        args.setdefault("sync_mode", False)
    if preset:
        if preset not in target.presets:
            raise FalkitError(
                f"Unknown preset {preset!r}", EXIT_USAGE, hint=f"Available: {', '.join(target.presets) or 'none'}"
            )
        args.update(json.loads(json.dumps(target.presets[preset])))
    if input_obj:
        args.update(input_obj)
    for k, v in sets:
        if "." not in k:
            v = schema.coerce_cli_value(k, v, target.input_schema)
        set_path(args, k, v)
    if prompt is not None:
        args[target.prompt_field] = prompt
    return args


def resolve_values(args: dict, plan: Plan, uploader: Uploader, root: Path) -> None:
    """Turn '@local/file' and 'from:REF[#sel]' strings into URLs, recursively."""

    def conv(value: Any, where: str) -> Any:
        if isinstance(value, list):
            out = []
            for i, v in enumerate(value):
                r = conv(v, f"{where}[{i}]")
                # from:REF#* expands to several URLs inside a list
                out.extend(r) if isinstance(r, list) and isinstance(v, str) and v.startswith("from:") else out.append(r)
            return out
        if isinstance(value, dict):
            return {k: conv(v, f"{where}.{k}") for k, v in value.items()}
        if not isinstance(value, str):
            return value
        if value.startswith("@") and len(value) > 1:
            path = Path(value[1:]).expanduser()
            plan.input_sources[where] = str(path)
            return uploader.upload(path)
        if value.startswith("from:"):
            ref, _, sel = value[5:].partition("#")
            mpath, manifest = load_manifest(ref or "last", root)
            if str(mpath) not in plan.parents:
                plan.parents.append(str(mpath))
            outs = _select_output(manifest, sel or None)
            plan.input_sources[where] = f"{manifest.get('run_id')}#{sel or 0}"
            urls = [_output_to_url(o, uploader) for o in outs]
            return urls if sel == "*" else urls[0]
        return value

    for k in list(args):
        args[k] = conv(args[k], k)


def autowire(args: dict, target: Target, from_refs: list[str], plan: Plan, uploader: Uploader, root: Path) -> None:
    """Fill empty media inputs from --from runs: each REF fills exactly one input.

    `--from REF` takes the run's first output that fits an empty input (required inputs first, then schema order);
    `--from REF#sel` picks outputs explicitly (an index, a kind, a field, or `*` for all of them, which only a
    list input accepts). One REF never spills into a second input, so a two-image run can't silently become a
    start frame *and* an end frame; give a second `--from` for that. Explicit --set values always win.
    """
    if not from_refs:
        return
    required = set(target.input_schema.get("required") or [])
    fields = []
    for name, prop in schema.ordered_properties(target.input_schema):
        kind = schema.media_kind_of_field(name, prop)
        if kind and args.get(name) in (None, "", []):
            fields.append((name not in required, name, prop, kind))
    fields.sort(key=lambda c: c[0])  # required first; sort is stable, so schema order within each group
    for ref in from_refs:
        run_ref, _, sel = ref.partition("#")
        mpath, manifest = load_manifest(run_ref, root)
        if str(mpath) not in plan.parents:
            plan.parents.append(str(mpath))
        outs = manifest.get("outputs") or []
        chosen = _select_output(manifest, sel) if sel else outs
        wired = False
        for i, (_, name, prop, kind) in enumerate(fields):
            fits = [o for o in chosen if kind == "any" or o.get("kind") == kind]
            if not fits:
                continue
            # An explicit selection goes into a list input whole; otherwise one output per REF.
            picked = fits if schema.is_list_field(prop) and sel else fits[:1]
            value = [_output_to_url(o, uploader) for o in picked]
            args[name] = value if schema.is_list_field(prop) else value[0]
            what = ", ".join(str(o.get("field")) for o in picked)
            plan.wiring.append(f"{name} ← {manifest.get('run_id')} {what} ({picked[0].get('kind')})")
            plan.input_sources[name] = f"{manifest.get('run_id')}#{what}"
            unused = [o for o in fits if o not in picked]
            if unused and not sel:
                log(
                    f"note: {run_ref} has {len(fits)} {kind} outputs; used the first. "
                    f"Pick another with --from {run_ref}#<index>, or all of them with #* (list inputs only)."
                )
            del fields[i]
            wired = True
            break
        if not wired:
            log(f"warning: --from {ref} matched no empty media input; use --set field=from:{ref}")


# ---------------------------------------------------------------------------
# Result handling
# ---------------------------------------------------------------------------
_KIND_BY_EXT = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".avif", ".heic"},
    "video": {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"},
    "audio": {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus"},
    "3d": {".glb", ".gltf", ".obj", ".fbx", ".usdz", ".ply", ".stl"},
}


def _kind(content_type: str | None, name: str) -> str:
    ct = (content_type or "").lower()
    for k in ("image", "video", "audio"):
        if ct.startswith(k + "/"):
            return k
    if ct.startswith("model/"):
        return "3d"
    ext = Path(urllib.parse.urlparse(name).path).suffix.lower()
    for k, exts in _KIND_BY_EXT.items():
        if ext in exts:
            return k
    return "file"


def extract_files(result: Any, prefix: str = "") -> list[dict]:
    """Find every file object ({url: ...}) in a result, whatever the model's output shape."""
    found = []
    if isinstance(result, dict):
        if isinstance(result.get("url"), str) and (
            result["url"].startswith(("http://", "https://", "data:", "file://"))
        ):
            found.append({"field": prefix or "output", "obj": result})
            return found
        for k, v in result.items():
            found += extract_files(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(result, list):
        for i, v in enumerate(result):
            found += extract_files(v, f"{prefix}.{i}" if prefix else str(i))
    return found


# mimetypes varies by OS; pin the types models actually return.
_EXT_BY_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "model/gltf-binary": ".glb",
    "model/gltf+json": ".gltf",
    "model/obj": ".obj",
    "application/json": ".json",
    "text/plain": ".txt",
}


def _ext_for(obj: dict) -> str:
    for cand in (
        obj.get("file_name"),
        urllib.parse.urlparse(obj["url"]).path if not obj["url"].startswith("data:") else None,
    ):
        if cand:
            suffix = Path(cand).suffix
            if 1 < len(suffix) <= 6:
                return suffix.lower()
    ct = obj.get("content_type")
    if not ct and obj["url"].startswith("data:"):
        ct = obj["url"][5:].split(";", 1)[0]
    ct = (ct or "").split(";", 1)[0].strip().lower()
    if ct in _EXT_BY_TYPE:
        return _EXT_BY_TYPE[ct]
    guessed = mimetypes.guess_extension(ct) if ct else None
    return {".jpe": ".jpg"}.get(guessed or "", guessed or ".bin")


def download(url: str, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if url.startswith("data:"):
        _, data = url.split(",", 1)
        blob = base64.b64decode(data)
        dest.write_bytes(blob)
        return len(blob)
    if url.startswith("file://"):
        blob = Path(urllib.request.url2pathname(urllib.parse.urlparse(url).path)).read_bytes()
        dest.write_bytes(blob)
        return len(blob)
    last: Exception | None = None
    for attempt in range(4):
        try:
            with httpx.stream("GET", url, timeout=300, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                size = 0
                with tmp.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
                        size += len(chunk)
                tmp.replace(dest)
                return size
        except httpx.HTTPError as e:
            last = e
            time.sleep(2**attempt)
    raise FalkitError(f"Download failed for {truncate(url, 120)}: {last}", EXIT_API)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _strip_data_uris(obj: Any) -> Any:
    """Keep result.json small when a model returns base64 inline."""
    if isinstance(obj, dict):
        return {k: _strip_data_uris(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_data_uris(v) for v in obj]
    if isinstance(obj, str) and obj.startswith("data:") and len(obj) > 200:
        return obj[:60] + f"…<{len(obj)} chars>"
    return obj


# ---------------------------------------------------------------------------
# Run directories, manifests, index
# ---------------------------------------------------------------------------
def new_run_dir(root: Path, label: str, tag: str | None) -> tuple[str, Path]:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    suffix = hashlib.sha1(f"{time.time_ns()}{threading.get_ident()}".encode()).hexdigest()[:6]
    run_id = f"{stamp}-{label}" + (f"-{re.sub(r'[^a-zA-Z0-9_-]+', '-', tag)[:40]}" if tag else "") + f"-{suffix}"
    d = root / time.strftime("%Y-%m-%d") / run_id
    d.mkdir(parents=True, exist_ok=False)
    return run_id, d


def finalize(run_dir: Path, request: dict, result: Any, root: Path, download_files: bool = True) -> dict:
    files = extract_files(result)
    outputs = []
    for f in files:
        obj = f["obj"]
        entry: dict[str, Any] = {
            "field": f["field"],
            "kind": _kind(obj.get("content_type"), obj.get("file_name") or obj["url"][:200]),
            "url": None if obj["url"].startswith("data:") else obj["url"],
            "content_type": obj.get("content_type"),
        }
        for k in ("width", "height", "duration", "fps", "file_size"):
            if obj.get(k) is not None:
                entry[k] = obj[k]
        if download_files:
            name = re.sub(r"[^a-zA-Z0-9_-]+", "-", f["field"]).strip("-") + _ext_for(obj)
            dest = run_dir / name
            entry["bytes"] = download(obj["url"], dest)
            entry["local_path"] = str(dest.resolve())
            entry["sha256"] = _sha256(dest)
            for k, v in probe_media(dest, entry["kind"]).items():
                entry.setdefault(k, v)
        outputs.append(entry)

    manifest = {
        "format": MANIFEST_FORMAT,
        "run_id": request["run_id"],
        "created_at": request["submitted_at"],
        "completed_at": now_iso(),
        "endpoint_id": request["endpoint_id"],
        "profile": request.get("profile"),
        "request_id": request.get("request_id"),
        "label": request.get("label"),
        "arguments": request["arguments"],
        "input_sources": request.get("input_sources", {}),
        "parents": request.get("parents", []),
        "prompt_template": request.get("prompt_template"),
        "pricing": request.get("pricing"),
        "price_estimate": request.get("price_estimate"),
        "seed": result.get("seed") if isinstance(result, dict) else None,
        "outputs": outputs,
        "text": {k: v for k, v in result.items() if isinstance(v, str) and k not in {"prompt"} and len(v) < 20000}
        if isinstance(result, dict)
        else {},
        "run_dir": str(run_dir.resolve()),
        "runtime_version": __version__,
    }
    write_json(run_dir / "result.json", _strip_data_uris(result))
    write_json(run_dir / "manifest.json", manifest)
    request["status"] = "completed"
    write_json(run_dir / "request.json", request)
    _append_index(root, manifest, run_dir)
    return manifest


def _image_size(path: Path) -> tuple[int, int] | None:
    """Width and height from a PNG or JPEG header (no image library needed)."""
    try:
        with path.open("rb") as f:
            head = f.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
            if head[:2] != b"\xff\xd8":
                return None
            f.seek(2)
            while True:
                marker = f.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return None
                size = int.from_bytes(f.read(2), "big")
                if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
                    data = f.read(5)
                    return int.from_bytes(data[3:5], "big"), int.from_bytes(data[1:3], "big")
                f.seek(size - 2, 1)
    except OSError:
        return None


def probe_media(path: Path, kind: str) -> dict:
    """Measure what fal often doesn't report: image size; video/audio duration, size, fps and whether there's sound.

    Uses ffprobe when it's installed; without it, images still get their size from the file header.
    """
    out: dict[str, Any] = {}
    if kind == "image":
        size = _image_size(path)
        if size:
            out["width"], out["height"] = size
        return out
    if kind not in ("video", "audio") or not shutil.which("ffprobe"):
        return out
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate:format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
        )
        info = json.loads(proc.stdout or "{}")
    except (subprocess.SubprocessError, OSError, ValueError):
        return out
    streams = info.get("streams") or []
    dur = (info.get("format") or {}).get("duration")
    if dur:
        out["duration"] = round(float(dur), 3)
    video = next((st for st in streams if st.get("codec_type") == "video"), None)
    if video:
        out["width"], out["height"] = video.get("width"), video.get("height")
        num, _, den = str(video.get("r_frame_rate") or "").partition("/")
        if num.isdigit() and den.isdigit() and int(den):
            out["fps"] = round(int(num) / int(den), 3)
        out["has_audio"] = any(st.get("codec_type") == "audio" for st in streams)
    return out


def ingest(
    paths: list[Path],
    root: Path,
    label: str | None,
    parent_refs: list[str],
    note: str | None = None,
    move: bool = False,
) -> dict:
    """Record local files (a local processing step's output) as a run, so later runs can use them.

    Files are copied into the run directory, so the manifest stays valid when the
    originals change. Directories are expanded (sorted, non-hidden files only).
    With move=True the sources are deleted afterwards, which leaves a workflow's
    scratch directory empty for the next run.
    """
    files: list[Path] = []
    for p in paths:
        p = Path(p).expanduser()
        if p.is_dir():
            files += sorted(f for f in p.rglob("*") if f.is_file() and not f.name.startswith("."))
        elif p.is_file():
            files.append(p)
        else:
            raise FalkitError(f"Not found: {p}", EXIT_USAGE)
    if not files:
        raise FalkitError("Nothing to ingest (no files found)", EXIT_USAGE)
    parents = [str(load_manifest(ref, root)[0]) for ref in parent_refs]
    run_id, run_dir = new_run_dir(root, "local", label)
    outputs, used = [], set()
    for i, src in enumerate(files):
        name = src.name if src.name not in used else f"{i}-{src.name}"
        used.add(name)
        dest = run_dir / name
        dest.write_bytes(src.read_bytes())
        entry: dict[str, Any] = {
            "field": f"files.{i}",
            "kind": _kind(mimetypes.guess_type(src.name)[0], src.name),
            "url": None,  # not hosted yet; a later fal run uploads local_path when it needs a URL
            "content_type": mimetypes.guess_type(src.name)[0],
            "local_path": str(dest.resolve()),
            "bytes": dest.stat().st_size,
            "sha256": _sha256(dest),
        }
        entry.update(probe_media(dest, entry["kind"]))
        outputs.append(entry)
    stamp = now_iso()
    arguments = {"note": note, "sources": [str(f.resolve()) for f in files]}
    manifest = {
        "format": MANIFEST_FORMAT,
        "run_id": run_id,
        "created_at": stamp,
        "completed_at": stamp,
        "endpoint_id": "local",
        "profile": None,
        "request_id": None,
        "label": label,
        "arguments": arguments,
        "input_sources": {},
        "parents": parents,
        "prompt_template": None,
        "pricing": None,
        "price_estimate": None,
        "seed": None,
        "outputs": outputs,
        "text": {},
        "run_dir": str(run_dir.resolve()),
        "runtime_version": __version__,
    }
    request = {
        "run_id": run_id,
        "status": "completed",
        "endpoint_id": "local",
        "label": label,
        "arguments": arguments,
        "submitted_at": stamp,
    }
    write_json(run_dir / "request.json", request)
    write_json(run_dir / "manifest.json", manifest)
    _append_index(root, manifest, run_dir)
    if move:
        for f in files:
            f.unlink(missing_ok=True)
    return manifest


def _prompt_text(manifest: dict) -> str | None:
    args = manifest.get("arguments") or {}
    field_name = (manifest.get("prompt_template") or {}).get("field")
    for k in (field_name, "prompt", "text", "note"):
        if k and isinstance(args.get(k), str):
            return args[k]
    return None


def _append_index(root: Path, manifest: dict, run_dir: Path) -> None:
    line = {
        "run_id": manifest["run_id"],
        "completed_at": manifest["completed_at"],
        "endpoint_id": manifest["endpoint_id"],
        "profile": manifest.get("profile"),
        "label": manifest.get("label"),
        "kinds": sorted({o["kind"] for o in manifest["outputs"]}),
        "prompt": truncate(_prompt_text(manifest), 120),
        "template": (manifest.get("prompt_template") or {}).get("name"),
        "price_usd": (manifest.get("price_estimate") or {}).get("usd"),
        "manifest": str((run_dir / "manifest.json").resolve().relative_to(root.resolve())),
    }
    with _print_lock:
        with index_path(root).open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Submission + waiting
# ---------------------------------------------------------------------------
def _client():
    import fal_client

    return fal_client.SyncClient(key=resolve_key())


def _describe_http_error(e: Exception) -> str:
    resp = getattr(e, "response", None)
    detail = None
    if resp is not None:
        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = getattr(resp, "text", None)
    if isinstance(detail, list):  # FastAPI-style validation errors
        return "; ".join(
            f"{'.'.join(str(x) for x in d.get('loc', [])[1:])}: {d.get('msg')}" for d in detail if isinstance(d, dict)
        ) or str(e)
    return truncate(detail or str(e), 800)


def wait_for(handle: Any, timeout_s: float, prefix: str = "") -> Any:
    import fal_client

    start = time.time()
    seen_logs = 0
    last_state = None
    for status in handle.iter_events(with_logs=True, interval=2.0):
        if isinstance(status, fal_client.Queued):
            state = f"queued (position {status.position})"
        elif isinstance(status, fal_client.InProgress):
            state = "running"
        else:
            state = "completed"
        logs = getattr(status, "logs", None) or []
        with _print_lock:
            if state != last_state:
                log(f"{prefix}{state} · {int(time.time() - start)}s")
                last_state = state
            for entry in logs[seen_logs:]:
                msg = entry.get("message") if isinstance(entry, dict) else str(entry)
                if msg:
                    log(f"{prefix}  │ {truncate(msg, 200)}")
            seen_logs = max(seen_logs, len(logs))
        if isinstance(status, fal_client.Completed):
            if getattr(status, "error", None):
                raise FalkitError(f"fal reported an error: {status.error}", EXIT_API)
            break
        if time.time() - start > timeout_s:
            raise TimeoutError
    try:
        return handle.get()
    except fal_client.FalClientHTTPError as e:
        raise FalkitError(f"fal request failed: {_describe_http_error(e)}", EXIT_API) from e


@dataclass
class RunOptions:
    root: Path
    label: str | None = None
    timeout_s: float = 1800
    no_wait: bool = False
    download: bool = True
    mock_result: Any = None


def _pricing_table(target: Target) -> dict | None:
    if not target.profile:
        return None
    try:
        return pricing.load(Path(target.profile["path"]))
    except FalkitError as e:
        log(f"warning: {e}")
        return None


def pricing_snapshot(target: Target) -> dict | None:
    """The profile's unit price (as of its last refresh), recorded for reference. Never used to block a run."""
    p = (target.profile or {}).get("pricing")
    return {k: p.get(k) for k in ("unit_price", "unit", "currency", "fetched_at") if k in p} if p else None


def execute(target: Target, plan: Plan, opts: RunOptions, prefix: str = "") -> dict:
    run_id, run_dir = new_run_dir(opts.root, target.label, opts.label)
    request = {
        "run_id": run_id,
        "status": "preparing",
        "endpoint_id": target.endpoint_id,
        "profile": target.profile["slug"] if target.profile else None,
        "label": opts.label,
        "arguments": plan.arguments,
        "input_sources": plan.input_sources,
        "parents": plan.parents,
        "prompt_template": plan.prompt_template,
        "pricing": pricing_snapshot(target),
        "price_estimate": plan.price_estimate,
        "submitted_at": now_iso(),
    }
    if opts.mock_result is not None:
        request.update(status="mock", request_id="mock")
        write_json(run_dir / "request.json", request)
        return finalize(run_dir, request, opts.mock_result, opts.root, opts.download)

    import fal_client

    try:
        handle = _client().submit(target.endpoint_id, plan.arguments)
    except fal_client.FalClientHTTPError as e:
        request["status"] = "rejected"
        request["error"] = _describe_http_error(e)
        write_json(run_dir / "request.json", request)
        raise FalkitError(f"fal rejected the request: {request['error']}", EXIT_API) from e
    request.update(status="submitted", request_id=handle.request_id)
    write_json(run_dir / "request.json", request)
    log(f"{prefix}submitted {target.endpoint_id} · request {handle.request_id} · {run_dir}")
    if opts.no_wait:
        return {"run_id": run_id, "run_dir": str(run_dir), "request_id": handle.request_id, "status": "submitted"}
    try:
        result = wait_for(handle, opts.timeout_s, prefix)
    except TimeoutError:
        raise FalkitError(
            f"Still running after {int(opts.timeout_s)}s (request {handle.request_id})",
            EXIT_TIMEOUT,
            hint=f"The job keeps running on fal. Resume with: fal.py fetch {run_dir}",
        ) from None
    except FalkitError as e:
        request.update(status="failed", error=str(e))
        write_json(run_dir / "request.json", request)
        raise
    return finalize(run_dir, request, result, opts.root, opts.download)


def _submitted(run_dir: Path) -> dict:
    request = read_json(run_dir / "request.json")
    if not request.get("request_id"):
        raise FalkitError(
            f"Run {request.get('run_id')} was never accepted by fal (status: {request.get('status')})",
            EXIT_USAGE,
            hint=request.get("error") or "Nothing is running for it; fix the arguments and run again.",
        )
    return request


def fetch(run_dir: Path, root: Path, timeout_s: float, download_files: bool = True) -> dict:
    request = read_json(run_dir / "request.json")
    if request.get("status") == "completed":
        return read_json(run_dir / "manifest.json")
    request = _submitted(run_dir)
    handle = _client().get_handle(request["endpoint_id"], request["request_id"])
    try:
        result = wait_for(handle, timeout_s)
    except TimeoutError:
        raise FalkitError("Still running", EXIT_TIMEOUT, hint=f"Try again later: fal.py fetch {run_dir}") from None
    return finalize(run_dir, request, result, root, download_files)


def status(run_dir: Path) -> dict:
    import fal_client

    request = read_json(run_dir / "request.json")
    if request.get("status") in {"completed", "mock"}:
        return {"status": "completed", "run_dir": str(run_dir)}
    request = _submitted(run_dir)
    handle = _client().get_handle(request["endpoint_id"], request["request_id"])
    st = handle.status(with_logs=False)
    name = {fal_client.Queued: "queued", fal_client.InProgress: "running", fal_client.Completed: "completed"}.get(
        type(st), type(st).__name__
    )
    out = {"status": name, "request_id": request["request_id"], "run_dir": str(run_dir)}
    if isinstance(st, fal_client.Queued):
        out["position"] = st.position
    return out


def cancel(run_dir: Path) -> None:
    request = _submitted(run_dir)
    _client().get_handle(request["endpoint_id"], request["request_id"]).cancel()
    request["status"] = "cancelled"
    write_json(run_dir / "request.json", request)


# ---------------------------------------------------------------------------
# Orchestration used by the CLI
# ---------------------------------------------------------------------------
SLOTS_KEY = "$slots"  # in a --batch line: per-request template slot values, merged over --slot


def render_prompt(
    target: Target, template: dict | None, slot_values: dict, overlay: dict, args: dict | None = None
) -> tuple[str | None, dict | None]:
    """Render the template for one request. Returns (prompt, provenance for the manifest).

    `{=param}` placeholders take the request's own parameter values (after defaults, presets and --set), so the
    prompt and the parameters can't disagree.
    """
    if not template:
        return None, None
    values = {**slot_values, **(overlay.get(SLOTS_KEY) or {})}
    props = target.input_schema.get("properties") or {}
    as_slot = sorted(k for k in values if k in props)
    if as_slot:
        raise FalkitError(
            f"{', '.join(as_slot)} {'is a model parameter' if len(as_slot) == 1 else 'are model parameters'}, "
            "not template slots",
            EXIT_USAGE,
            hint=" ".join(f"Use --set {k}=… instead of --slot." for k in as_slot),
        )
    clash = [x for x in template["slots"] if x in props]
    if clash:
        raise FalkitError(
            f"Template {template['name']!r} uses parameter name(s) {', '.join(clash)} as slots",
            EXIT_USAGE,
            hint=f"Fix the template: write {', '.join('{=' + x + '}' for x in clash)} for the request's value, "
            "or rename the slot. `fal.py profile check` lists every problem.",
        )
    params = {p: (args or {}).get(p, (props.get(p) or {}).get("default")) for p in template.get("params") or []}
    prompt, unused, warnings = templates.render(template["body"], values, params)
    if unused:
        raise FalkitError(
            f"Template {template['name']!r} has no slot(s) {', '.join(unused)}",
            EXIT_USAGE,
            hint=f"Its slots: {', '.join(template['slots'])}. A misspelled slot would silently drop what you meant.",
        )
    for w in warnings:
        log(f"warning: {w}")
    used = {k: v for k, v in values.items() if k in template["slots"]}
    return prompt, {"name": template["name"], "source": template["source"], "slots": used, "field": target.prompt_field}


def prepare(
    target: Target,
    overlay: dict,
    *,
    preset: str | None,
    sets: list,
    prompt: str | None,
    from_refs: list[str],
    uploader: Uploader,
    root: Path,
    template: dict | None = None,
    slot_values: dict | None = None,
    strict: bool = True,
    quiet: bool = False,
) -> Plan:
    overlay = dict(overlay)
    slots_overlay = {SLOTS_KEY: overlay.pop(SLOTS_KEY)} if SLOTS_KEY in overlay else {}
    args = build_arguments(target, preset=preset, input_obj=overlay, sets=sets, prompt=prompt)
    rendered, provenance = render_prompt(target, template, slot_values or {}, slots_overlay, args)
    if rendered is not None:
        args[target.prompt_field] = rendered
    plan = Plan(arguments=args, prompt_template=provenance)
    resolve_values(args, plan, uploader, root)
    autowire(args, target, from_refs, plan, uploader, root)
    errors, warnings = schema.validate(args, target.input_schema)
    if not quiet:
        for w in warnings:
            log(f"warning: {w}")
        for w in plan.wiring:
            log(f"wired: {w}")
    if errors and strict:
        raise FalkitError(
            "Arguments do not match the model schema:\n  " + "\n  ".join(errors),
            EXIT_USAGE,
            hint="Inspect parameters with `fal.py schema <endpoint>` or the profile's schema.json.",
        )
    if errors and not quiet:
        # --dry-run reports schema problems without stopping, so the whole plan is visible at once.
        for e in errors:
            log(f"schema: {e}")
    return plan


def research_note(target: Target, prompted: bool) -> str | None:
    """Why this prompt may not be the model's best input, or None when it's backed by research."""
    if not prompted:
        return None
    if not target.profile:
        return (
            "no profile: this prompt isn't backed by research on the model. "
            "Create one (`profile init`, then research prompting.md) before relying on the result."
        )
    status = target.profile.get("prompting_status")
    if status != "researched":
        return f"profile {target.profile['slug']!r} prompting is {status}; research prompting.md (SKILL.md A4) first."
    return None


def run_many(
    target: Target,
    overlays: list[dict],
    *,
    preset: str | None,
    sets: list,
    prompt: str | None,
    from_refs: list[str],
    opts: RunOptions,
    dry_run: bool,
    concurrency: int,
    template: dict | None = None,
    slot_values: dict | None = None,
) -> dict:
    kw = dict(preset=preset, sets=sets, prompt=prompt, from_refs=from_refs, root=opts.root, template=template,
              slot_values=slot_values)
    # Pass 1 builds and validates every request with @files as placeholders, so nothing is uploaded
    # until all of them are known to be valid.
    dry = Uploader(dry_run=True)
    plans = [prepare(target, ov, uploader=dry, strict=not dry_run, **kw) for ov in overlays]
    prompted = any(target.prompt_field in p.arguments for p in plans)
    note = research_note(target, prompted)
    if note:
        log(f"note: {note}")
    table = _pricing_table(target)
    for p in plans:
        p.price_estimate = pricing.estimate(table, p.arguments, target.input_schema)
    price_total = pricing.total([p.price_estimate for p in plans])
    log(f"price: {pricing.describe(price_total if len(plans) > 1 else plans[0].price_estimate)}")

    if dry_run:
        return {
            "dry_run": True,
            "endpoint_id": target.endpoint_id,
            "profile": target.profile["slug"] if target.profile else None,
            "prompt_field": target.prompt_field,
            "requests": [
                {
                    "arguments": p.arguments,
                    "prompt_template": p.prompt_template,
                    "price_estimate": p.price_estimate,
                    "input_sources": p.input_sources,
                    "wiring": p.wiring,
                }
                for p in plans
            ],
            "price_total": price_total,
            "pricing": pricing_snapshot(target),
            "research": note or "ok",
        }
    # Pass 2: real uploads / URL liveness checks. --mock never touches the network, so it keeps pass 1's placeholders.
    if opts.mock_result is None and any(p.input_sources for p in plans):
        real = Uploader(dry_run=False)
        estimates = [p.price_estimate for p in plans]
        plans = [prepare(target, ov, uploader=real, strict=True, quiet=True, **kw) for ov in overlays]
        for p, est in zip(plans, estimates, strict=True):
            p.price_estimate = est

    if len(plans) == 1:
        return execute(target, plans[0], opts)

    results: list[Any] = [None] * len(plans)

    def work(i: int) -> None:
        try:
            results[i] = execute(target, plans[i], opts, prefix=f"[{i + 1}/{len(plans)}] ")
        except FalkitError as e:
            results[i] = {"error": str(e), "code": e.code}

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        list(pool.map(work, range(len(plans))))
    failed = [r for r in results if isinstance(r, dict) and "error" in r]
    return {"batch": True, "total": len(plans), "failed": len(failed), "price_total": price_total, "runs": results}
