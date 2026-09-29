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

## Rotation

Create a new key in the fal dashboard, update the env var or the bws secret value, run `fal doctor`, then revoke
the old key. Nothing else stores the key, so nothing else needs updating.
