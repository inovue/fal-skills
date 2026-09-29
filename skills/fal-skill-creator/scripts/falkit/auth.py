"""fal API key resolution: env first, then Bitwarden Secrets Manager (bws).

Standard library only: `scripts/mcp_headers.py` imports this with a bare
`python3`, before any dependency is installed. The key is never printed,
logged, or put on a command line.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from .errors import EXIT_AUTH, FalkitError

_key_cache: tuple[str, str] | None = None


def _bws_json(args: list[str], timeout: float = 60) -> Any:
    try:
        proc = subprocess.run(
            ["bws", *args, "--output", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
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


def _key_from_bws(timeout: float = 60) -> tuple[str, str] | None:
    if not shutil.which("bws") or not os.environ.get("BWS_ACCESS_TOKEN"):
        return None
    secret_id = os.environ.get("FAL_BWS_SECRET_ID")
    if secret_id:
        data = _bws_json(["secret", "get", secret_id], timeout)
        return data["value"].strip(), f"bws secret id {secret_id[:8]}…"
    name = os.environ.get("FAL_BWS_SECRET_NAME", "FAL_KEY")
    list_args = ["secret", "list"]
    if os.environ.get("BWS_PROJECT_ID"):
        list_args.append(os.environ["BWS_PROJECT_ID"])
    matches = [s for s in _bws_json(list_args, timeout) if s.get("key") == name]
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


def resolve_key(required: bool = True, bws_timeout: float = 60) -> str | None:
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
        found = _key_from_bws(bws_timeout)
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
