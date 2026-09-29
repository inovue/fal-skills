#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "fal-client>=1.0,<2",
#   "httpx>=0.27",
#   "jsonschema>=4.21",
# ]
# ///
"""fal.ai toolkit for agents: discover models, build profiles, generate, chain.

    uv run scripts/fal.py doctor
    uv run scripts/fal.py models search "video" -c image-to-video
    uv run scripts/fal.py profile init fal-ai/flux/dev
    uv run scripts/fal.py run -p flux-dev --prompt "a red fox" --dry-run

Exit codes: 0 ok · 2 usage/validation · 3 cost needs approval (--yes)
            4 auth · 5 fal API error · 6 timeout (resume with `fetch`)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252; never crash on ✓ or CJK prompts
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from falkit.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
