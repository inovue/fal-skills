"""Prompt templates: named prompts with {slots}, kept in markdown next to the research behind them.

A template is a fenced block whose info string is `template <name>`:

    ```template product-shot
    Photorealistic product photograph of {product} on {surface}.[[ Props: {props}.]] {=duration} …
    ```

A profile keeps its templates in prompting.md; a workflow keeps step-specific
ones in WORKFLOW.md. `fal run --template NAME --slot key=value` renders one, so
the prompt a model receives is always the researched structure with only the
request-specific parts filled in, and the manifest records which template and
which values produced it.

Three kinds of placeholder:
- `{name}`: a required slot. It must be given a non-empty value (`--slot name=value`).
- `[[ … {name} … ]]`: an optional part. It's kept only when every slot in it has a value and dropped whole
  otherwise, so "[[ Camera: {camera_move}.]]" never leaves a dangling "Camera:".
- `{=param}`: the value of the model parameter `param` in this request (`{=duration}` → "10"), so the prompt
  and the request can't disagree. It's set with `--set`, never with `--slot`.
A plain `{name}` that is also a model parameter is refused: write `{=name}` for the parameter's value, or
rename the slot. `{{` and `}}` are literal braces. Older prompting.md files (a `### name` heading followed by
a ```text block under `## Templates`) are read too.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .core import EXIT_USAGE, FalkitError

_FENCE_RE = re.compile(
    r"^(?P<fence>`{3,}|~{3,})[ \t]*template[ \t]+(?P<name>[A-Za-z0-9_.-]+)[ \t]*\n(?P<body>.*?)^(?P=fence)[ \t]*$",
    re.M | re.S,
)
_LEGACY_SECTION_RE = re.compile(r"^##[ \t]+Templates[ \t]*\n(?P<section>.*?)(?=^##[ \t]+\S|\Z)", re.M | re.S)
_LEGACY_ITEM_RE = re.compile(
    r"^###[ \t]+`?(?P<name>[A-Za-z0-9_.-]+)`?[^\n]*\n(?:(?!^###).)*?^(?P<fence>`{3,})[a-z]*[ \t]*\n(?P<body>.*?)^(?P=fence)",
    re.M | re.S,
)
_SLOT_RE = re.compile(r"(?<!\{)\{([a-z][a-z0-9_]*)\}(?!\})")
_PARAM_RE = re.compile(r"(?<!\{)\{=([a-z][a-z0-9_]*)\}(?!\})")
_GROUP_RE = re.compile(r"\[\[(.*?)\]\]", re.S)
_CJK_RE = re.compile(r"[぀-ヿ㐀-鿿豈-﫿가-힯]")
# Signs of a broken sentence after rendering: a label with nothing after it, an empty quote, stray punctuation.
_DANGLING_RE = re.compile(r"\b[A-Z][\w ]{0,30}:[ \t]*(?=$|\n|[.,;])|\"\"|“”|「」|\(\s*\)|\s[,.;:](?=\s|$)|,\s*[.;]|\.\s*\.", re.M)


def parse(text: str) -> dict[str, str]:
    """All templates in a markdown document, by name, in document order."""
    found = {m.group("name"): m.group("body").strip("\n") for m in _FENCE_RE.finditer(text)}
    if found:
        return found
    section = _LEGACY_SECTION_RE.search(text)
    if section:
        for m in _LEGACY_ITEM_RE.finditer(section.group("section")):
            found.setdefault(m.group("name"), m.group("body").strip("\n"))
    return found


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for s in items:
        if s not in seen:
            seen.append(s)
    return seen


def slots(body: str) -> list[str]:
    """Slots the request fills (required and optional), in order. `{=param}` placeholders aren't slots."""
    return _unique(_SLOT_RE.findall(body))


def param_slots(body: str) -> list[str]:
    """Model parameters the template quotes with `{=param}`."""
    return _unique(_PARAM_RE.findall(body))


def required_slots(body: str) -> list[str]:
    """Slots outside every [[ optional ]] group."""
    return slots(_GROUP_RE.sub("", body))


def optional_slots(body: str) -> list[str]:
    req = set(required_slots(body))
    return [s for s in slots(body) if s not in req]


def fixed_text(body: str) -> str:
    """The template's own wording: what research put there, without slots or group markers."""
    text = _PARAM_RE.sub(" ", _SLOT_RE.sub(" ", body.replace("[[", " ").replace("]]", " ")))
    return re.sub(r"\s+", " ", text).strip()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return ", ".join(_text(v) for v in value if _text(v))
    return str(value).strip()


def _sub(text: str, pattern: str, val: str) -> str:
    return re.sub(r"(?<!\{)" + re.escape(pattern) + r"(?!\})", lambda _m: val, text)


def render(
    body: str, values: dict[str, Any], params: dict[str, Any] | None = None
) -> tuple[str, list[str], list[str]]:
    """Fill a template. Returns (prompt, unused slot names, warnings).

    Raises when a required slot is missing or empty, or a `{=param}` has no value in `params`.
    """
    text_values = {k: _text(v) for k, v in values.items()}
    missing = [s for s in required_slots(body) if not text_values.get(s)]
    if missing:
        opt = optional_slots(body)
        empty = [s for s in missing if s in values]
        raise FalkitError(
            f"Template slots without a value: {', '.join(missing)}"
            + (f" ({', '.join(empty)} given empty; required parts can't be left out)" if empty else ""),
            EXIT_USAGE,
            hint="Pass each with --slot name=value."
            + (f" Optional (may be left out): {', '.join(opt)}." if opt else ""),
        )
    param_values = {k: _text(v) for k, v in (params or {}).items()}
    no_param = [p for p in param_slots(body) if not param_values.get(p)]
    if no_param:
        raise FalkitError(
            f"Template quotes parameter(s) {', '.join(no_param)} but the request has no value for them",
            EXIT_USAGE,
            hint=" ".join(f"Set it with --set {p}=…" for p in no_param),
        )

    def fill(text: str) -> str:
        for n in slots(text):
            text = _sub(text, "{" + n + "}", text_values[n])
        for p in param_slots(text):
            text = _sub(text, "{=" + p + "}", param_values[p])
        return text

    def group(m: re.Match) -> str:
        inner = m.group(1)
        return fill(inner) if all(text_values.get(n) for n in slots(inner)) else ""

    out = fill(_GROUP_RE.sub(group, body))
    out = out.replace("{{", "{").replace("}}", "}")
    lines = [re.sub(r"[ \t]{2,}", " ", line).strip() for line in out.splitlines()]
    prompt = "\n".join(lines).strip()

    warnings = []
    wording = fixed_text(body)
    verbatim = set(re.findall(r"[\"“「']\{([a-z][a-z0-9_]*)\}[\"”」']", body))  # quoted: text that must appear as is
    filled = [n for n in slots(body) if n not in verbatim and _CJK_RE.search(text_values.get(n, ""))]
    if filled and not _CJK_RE.search(wording) and len(re.findall(r"[A-Za-z]", wording)) >= 20:
        warnings.append(
            f"slot(s) {', '.join(filled)} are in Japanese/Chinese/Korean but the template is English; "
            "translate the values unless prompting.md says this model handles mixed-language prompts "
            "(on-screen text that must appear verbatim is the exception)"
        )
    return prompt, sorted(set(values) - set(slots(body))), warnings


def lint(body: str, params: set[str] | None = None) -> list[str]:
    """Structural problems a template will cause on real requests (see profile check)."""
    problems = []
    params = params or set()
    clash = [s for s in slots(body) if s in params]
    if clash:
        problems.append(
            f"{', '.join('{' + s + '}' for s in clash)} {'is a' if len(clash) == 1 else 'are'} model parameter "
            f"name(s): write {', '.join('{=' + s + '}' for s in clash)} for the request's value, or rename the slot"
        )
    unknown = [p for p in param_slots(body) if params and p not in params]
    if unknown:
        problems.append(f"{', '.join('{=' + p + '}' for p in unknown)} name(s) no parameter of this model")
    if problems:
        return problems
    fake_params = {p: "X" for p in param_slots(body)}
    req = {s: "X" for s in required_slots(body)}
    # Render the way real requests do: nothing optional, and everything; neither may leave broken text behind.
    for label, values in (("with only the required slots", req), ("with every slot", {s: "X" for s in slots(body)})):
        text = render(body, values, fake_params)[0]
        m = _DANGLING_RE.search(text)
        if m:
            snippet = text[max(0, m.start() - 25) : m.end() + 15].replace("\n", " ")
            problems.append(f"{label} it renders broken text: …{snippet}…; move that part into [[ … ]]")
    return problems


# ---------------------------------------------------------------------------
# Resolving a template reference
# ---------------------------------------------------------------------------
def split_ref(ref: str) -> tuple[Path | None, str]:
    """'name' → (None, name); 'path/to/file.md#name' → (path, name)."""
    if "#" in ref:
        path, _, name = ref.rpartition("#")
        return Path(path).expanduser(), name
    return None, ref


def load(ref: str, profile: dict | None) -> dict:
    """Find a template by 'name' (the profile's prompting.md) or 'file.md#name'."""
    path, name = split_ref(ref)
    if path is None:
        if not profile:
            raise FalkitError(
                f"Template {name!r} needs a profile",
                EXIT_USAGE,
                hint="Run with --profile, or pass the template as path/to/file.md#name.",
            )
        path = Path(profile["path"]) / "prompting.md"
    if not path.is_file():
        raise FalkitError(f"Template file not found: {path}", EXIT_USAGE)
    found = parse(path.read_text(encoding="utf-8"))
    if name not in found:
        raise FalkitError(
            f"No template {name!r} in {path}",
            EXIT_USAGE,
            hint=f"Templates there: {', '.join(found) or 'none'}. List them with `fal.py profile templates <profile>`.",
        )
    body = found[name]
    return {
        "name": name,
        "source": str(path.resolve()),
        "body": body,
        "slots": slots(body),
        "required": required_slots(body),
        "optional": optional_slots(body),
        "params": param_slots(body),
    }


def describe(body: str) -> str:
    """One line for listings: required, optional, and parameter-filled parts."""
    parts = [", ".join(f"`{s}`" for s in required_slots(body)) or "no required slots"]
    if optional_slots(body):
        parts.append("optional " + ", ".join(f"`{s}`" for s in optional_slots(body)))
    if param_slots(body):
        parts.append("from the request " + ", ".join(f"`{p}`" for p in param_slots(body)))
    return "; ".join(parts)
