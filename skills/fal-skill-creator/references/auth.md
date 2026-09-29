# fal API key setup

The runtime looks for a key in this order and uses the first one it finds:

1. `FAL_KEY` environment variable.
2. `FAL_KEY_ID` + `FAL_KEY_SECRET`, joined as `id:secret`.
3. **Bitwarden Secrets Manager** (`bws` CLI), when `bws` is on PATH and `BWS_ACCESS_TOKEN` is set:
   - If `FAL_BWS_SECRET_ID` is set, that secret is read (`bws secret get <id>`). This is the fastest and least
     ambiguous option.
   - Otherwise, the secret whose key equals `FAL_BWS_SECRET_NAME` (default `FAL_KEY`) is used from
     `bws secret list`. Set `BWS_PROJECT_ID` to limit the lookup to one project. When two secrets share the name,
     the runtime stops and asks you to set `FAL_BWS_SECRET_ID`.

Check which source was used with `fal doctor`. It prints the source, never the key.

## Getting a key

Create a key at https://fal.ai/dashboard/keys. Model search and schema fetching work without a key. Pricing,
uploads and generation need one.

## Setting it up

**Environment variable** (simplest):
```bash
export FAL_KEY="…"            # add to your shell profile or a direnv .envrc (gitignored)
```

**Bitwarden Secrets Manager** (recommended for teams and CI):
```bash
bws secret create FAL_KEY "<key>" <project_id>
export BWS_ACCESS_TOKEN="<machine account token>"
# optional, faster:
export FAL_BWS_SECRET_ID="<secret uuid>"
```

## Rules the runtime follows (and the agent should too)

- The key goes only into the `Authorization: Key …` header of requests to fal. It is never printed, logged,
  written to disk, or passed as a command-line argument, because other local users can see arguments in `ps`.
- Error messages from bws are passed through as they are. They contain no secret values.
- Agents: never `echo $FAL_KEY`, never write the key into files, scripts, or `.env` files that might get
  committed, and never paste it into a command. If the user pastes a key into the chat, suggest rotating it.

## The fal MCP server

The Claude Code plugin connects the official fal MCP server (`https://mcp.fal.ai/mcp`) for model discovery. It needs
an API key: fal's sign-in server doesn't allow OAuth for Claude Code (dynamic client registration is disabled), and
Claude Code hides credential environment variables such as `FAL_KEY` from anything a plugin runs. Pick one:

**A. Enter the key in the plugin's options** (simplest). Claude Code asks for it when you enable the plugin, or
later: `/plugin` → Installed → fal → Configure options → "fal API key". It is stored in the OS credential store,
not in `settings.json`. Then reconnect `plugin:fal:fal-ai` from `/mcp`.

**B. Keep the key only in env or Bitwarden** (no second copy). Add the server at user scope with this skill's
helper, which reads the key the same way the runtime does, and disable the plugin's copy in `/mcp`:
```bash
claude mcp add-json --scope user fal-ai '{"type":"http","url":"https://mcp.fal.ai/mcp","headersHelper":"python3 <skill-dir>/scripts/mcp_headers.py"}'
```
The helper refuses to run outside Claude Code's MCP connection, so it can't leak the key into a transcript. Don't
run it by hand. (Claude Code passes environment variables to user-scope helpers, but not to plugin ones.)

Other clients (Cursor, Windsurf, Codex) take the same URL with an `Authorization: Bearer <key>` header; prefer a
setting that reads the key from an environment variable. The skill works without the server.

## Rotation

Create a new key in the fal dashboard, update the env var or the bws secret value, run `fal doctor`, then revoke
the old key. If you entered the key in the plugin's options (A above), update it there too; with the helper (B),
just reconnect the server from `/mcp`.
