#!/usr/bin/env python3
"""Optional headersHelper for the fal MCP server (https://mcp.fal.ai/mcp) at Claude Code user scope.

The `fal` plugin takes the key in its options. Use this helper instead when you
want the key to stay in env or Bitwarden only: add the server yourself at user or
local scope and disable the plugin's copy.

    claude mcp add-json --scope user fal-ai \
      '{"type":"http","url":"https://mcp.fal.ai/mcp","headersHelper":"python3 /abs/path/scripts/mcp_headers.py"}'

Claude Code runs it when it connects and reads a JSON object of headers from
stdout. The key comes from the same place the runtime uses (FAL_KEY,
FAL_KEY_ID/FAL_KEY_SECRET, or bws). With no key it prints `{}` and the connection
fails with 401 (fal offers Claude Code no OAuth). It can't work inside a plugin or a project .mcp.json:
Claude Code strips credential variables from helpers those supply.

It prints the key only when Claude Code's helper environment is present, so an
agent that runs it by hand never gets the key into its transcript.
Standard library only: runs with a bare `python3`.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    if not os.environ.get("CLAUDE_CODE_MCP_SERVER_NAME"):
        print(
            "mcp_headers.py is a Claude Code headersHelper and prints credentials; "
            "it only runs when Claude Code connects to an MCP server.",
            file=sys.stderr,
        )
        return 2
    headers = {}
    try:
        from falkit.auth import resolve_key

        key = resolve_key(required=False, bws_timeout=8)  # Claude Code gives the helper 10 seconds
        if key:
            headers["Authorization"] = f"Bearer {key}"
    except Exception as e:  # never crash the helper; Claude Code reports the failed connection
        print(f"mcp_headers: no key ({type(e).__name__})", file=sys.stderr)
    print(json.dumps(headers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
