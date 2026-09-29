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

The Claude Code plugin connects the official fal MCP server (`https://mcp.fal.ai/mcp`) for model discovery. It
signs in with **OAuth**: run `/mcp`, pick `plugin:fal:fal-ai`, and authenticate once in the browser. The plugin
can't reuse your API key, because Claude Code deliberately hides credential environment variables from anything a
plugin runs.

To use your API key instead (for example on a headless machine), add the server yourself at user scope with this
skill's helper. The helper reads the key the same way the runtime does, and at user scope Claude Code lets it see
your environment:
```bash
claude mcp add-json --scope user fal-ai '{"type":"http","url":"https://mcp.fal.ai/mcp","headersHelper":"python3 <skill-dir>/scripts/mcp_headers.py"}'
```
The helper refuses to run outside Claude Code's MCP connection, so it can't leak the key into a transcript. Don't
run it by hand. If both the plugin's server and yours are present, disable one in `/mcp`.

Cursor, Windsurf and Codex take the same URL; use their OAuth sign-in. The skill works without the server.

## Rotation

Create a new key in the fal dashboard, update the env var or the bws secret value, run `fal doctor`, then revoke
the old key. Nothing else stores the key. If you connected the MCP server with the helper, reconnect it from `/mcp`
so it picks up the new key. OAuth sign-ins are separate from API keys.
