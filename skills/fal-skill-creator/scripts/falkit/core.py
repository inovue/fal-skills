"""Shared plumbing: errors/exit codes, key resolution, paths, HTTP, output."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from . import __version__

# ---------------------------------------------------------------------------
# Exit codes — stable contract for agents and shell pipelines.
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_ERROR = 1  # unexpected failure
EXIT_USAGE = 2  # bad arguments / schema validation failed
EXIT_NEEDS_CONFIRMATION = 3  # cost guard tripped; rerun with --yes after asking the user
EXIT_AUTH = 4  # no key / key rejected
EXIT_API = 5  # fal returned an error for the request
EXIT_TIMEOUT = 6  # still running at --timeout; resumable with `fetch`

USER_AGENT = f"fal-skill-creator/{__version__}"


class FalkitError(Exception):
    """An error with a user-facing message, an exit code, and an optional hint."""

    def __init__(self, message: str, code: int = EXIT_ERROR, hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.hint = hint


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
# Key resolution: env first, then Bitwarden Secrets Manager (bws).
# The key is never printed, logged, or put on a command line.
# ---------------------------------------------------------------------------
_key_cache: tuple[str, str] | None = None


def _bws_json(args: list[str]) -> Any:
    try:
        proc = subprocess.run(
            ["bws", *args, "--output", "json"],
            capture_output=True,
            text=True,
            timeout=60,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as e:
        raise FalkitError("bws timed out", EXIT_AUTH) from e
    if proc.returncode != 0:
        # bws error text never contains the secret value, safe to surface.
        raise FalkitError(
            f"bws {' '.join(args[:2])} failed: {proc.stderr.strip()[:300]}",
            EXIT_AUTH,
            hint="Check BWS_ACCESS_TOKEN and that the machine account can read the secret.",
        )
    return json.loads(proc.stdout)


def _key_from_bws() -> tuple[str, str] | None:
    if not shutil.which("bws") or not os.environ.get("BWS_ACCESS_TOKEN"):
        return None
    secret_id = os.environ.get("FAL_BWS_SECRET_ID")
    if secret_id:
        data = _bws_json(["secret", "get", secret_id])
        return data["value"].strip(), f"bws secret id {secret_id[:8]}…"
    name = os.environ.get("FAL_BWS_SECRET_NAME", "FAL_KEY")
    list_args = ["secret", "list"]
    if os.environ.get("BWS_PROJECT_ID"):
        list_args.append(os.environ["BWS_PROJECT_ID"])
    matches = [s for s in _bws_json(list_args) if s.get("key") == name]
    if not matches:
        return None
    if len(matches) > 1:
        ids = ", ".join(m["id"] for m in matches)
        raise FalkitError(
            f"{len(matches)} bws secrets are named {name!r}",
            EXIT_AUTH,
            hint=f"Set FAL_BWS_SECRET_ID to one of: {ids}",
        )
    return matches[0]["value"].strip(), f"bws secret {name!r} ({matches[0]['id'][:8]}…)"


def resolve_key(required: bool = True) -> str | None:
    """Return the fal API key, or None when not required and unavailable."""
    global _key_cache
    if _key_cache:
        return _key_cache[0]
    found: tuple[str, str] | None = None
    if os.environ.get("FAL_KEY"):
        found = (os.environ["FAL_KEY"].strip(), "env FAL_KEY")
    elif os.environ.get("FAL_KEY_ID") and os.environ.get("FAL_KEY_SECRET"):
        found = (f"{os.environ['FAL_KEY_ID']}:{os.environ['FAL_KEY_SECRET']}", "env FAL_KEY_ID/FAL_KEY_SECRET")
    else:
        found = _key_from_bws()
    if not found:
        if required:
            raise FalkitError(
                "No fal API key found",
                EXIT_AUTH,
                hint="Set FAL_KEY, or set BWS_ACCESS_TOKEN with a bws secret named FAL_KEY "
                "(or FAL_BWS_SECRET_ID). See references/auth.md.",
            )
        return None
    _key_cache = found
    return found[0]


def key_source() -> str | None:
    resolve_key(required=False)
    return _key_cache[1] if _key_cache else None


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
