"""Shared plumbing: errors/exit codes, key resolution, paths, HTTP, output."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .auth import key_source, resolve_key  # noqa: F401  (re-exported)
from .errors import (  # noqa: F401  (re-exported)
    EXIT_API,
    EXIT_AUTH,
    EXIT_ERROR,
    EXIT_NEEDS_CONFIRMATION,
    EXIT_OK,
    EXIT_TIMEOUT,
    EXIT_USAGE,
    FalkitError,
)

USER_AGENT = f"fal-skill-creator/{__version__}"


# ---------------------------------------------------------------------------
# Output helpers. stdout carries results (JSON with --json); stderr carries
# progress and diagnostics so `--json | jq` always works.
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def emit_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)  # atomic on POSIX: readers never see half-written files


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SKILL_DIR = Path(__file__).resolve().parents[2]


def user_home_dir() -> Path:
    return Path(os.environ.get("FAL_SKILLS_HOME", Path.home() / ".fal-skills")).expanduser()


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base).expanduser() / "fal-skills"


def output_root(override: str | None = None) -> Path:
    return Path(override or os.environ.get("FAL_OUTPUT_DIR") or "fal-outputs").expanduser()


# ---------------------------------------------------------------------------
# HTTP with retries. Only idempotent calls go through here — queue submission
# is never retried blindly, since that could double-bill.
# ---------------------------------------------------------------------------
_RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


def http_request(
    method: str,
    url: str,
    *,
    key: str | None = None,
    retries: int = 4,
    timeout: float = 60.0,
    **kwargs: Any,
) -> httpx.Response:
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    if key:
        headers["Authorization"] = f"Key {key}"
    delay = 1.0
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = httpx.request(method, url, headers=headers, timeout=timeout, follow_redirects=True, **kwargs)
        except httpx.TransportError as e:
            last_exc = e
        else:
            if resp.status_code not in _RETRY_STATUS or attempt == retries:
                return resp
            retry_after = resp.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                delay = max(delay, float(retry_after))
        if attempt < retries:
            time.sleep(min(delay, 30))
            delay *= 2
    raise FalkitError(f"Network error calling {url}: {last_exc}", EXIT_ERROR)


def http_json(method: str, url: str, **kwargs: Any) -> Any:
    resp = http_request(method, url, **kwargs)
    if resp.status_code in (401, 403):
        raise FalkitError(f"fal rejected the API key ({resp.status_code})", EXIT_AUTH)
    if resp.status_code >= 400:
        raise FalkitError(f"{method} {url} -> HTTP {resp.status_code}: {resp.text[:500]}", EXIT_API)
    return resp.json()


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------
def parse_value(raw: str) -> Any:
    """Parse a CLI value: JSON when it parses (numbers, bools, lists, objects), else the raw string."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw


def parse_assignment(item: str) -> tuple[str, Any]:
    if "=" not in item:
        raise FalkitError(f"Expected key=value, got {item!r}", EXIT_USAGE)
    k, v = item.split("=", 1)
    return k.strip(), parse_value(v)


def set_path(obj: dict, dotted: str, value: Any) -> None:
    """Assign into nested dicts with dotted keys: image_size.width=768."""
    parts = dotted.split(".")
    for p in parts[:-1]:
        nxt = obj.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            obj[p] = nxt
        obj = nxt
    obj[parts[-1]] = value


def truncate(s: Any, n: int) -> str:
    s = "" if s is None else str(s).replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
