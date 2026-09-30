# Troubleshooting

Start with `fal doctor`. Set `FALKIT_DEBUG=1` to get full tracebacks for unexpected errors (exit code 1).

## Exit 2: usage or validation

| symptom | fix |
|---|---|
| `Arguments do not match the model schema: x: 'foo' is not one of [...]` | Use one of the listed values. `fal schema <endpoint>` lists every parameter. |
| `unknown parameter 'x'` (a warning) | Usually a typo. Unknown keys are sent anyway, but fal may ignore them. |
| `Profile 'x' not found` | `fal profile list`. Profiles are per scope: a project profile lives in `./.fal/profiles`. |
| `Cannot resolve run reference` / `No run 'label:…'` | `fal runs list`. `last` and `label:` refer to *completed* runs in the current output root (`--out` / `FAL_OUTPUT_DIR`). |
| `workflow check`: `profile 'x' not found` | Run the `fal profile init …` command it prints, or point the step at another profile. |
| `workflow plan` shows `<in of step …>` | That step hasn't run in the current pass yet. Run the steps in order; rerunning an early step resets the later ones. |
| Pinned defaults fail after a model update | `fal profile refresh <slug>`, then fix them with `profile set` / `--unset`. |

## Exit 3: cost guard

The estimate is above the limit, or it couldn't be computed and the unit price is above $0.05. For GPU-time pricing
("compute seconds"), the guard assumes up to 60 s per request, so large batches ask first. Show the user the
estimate and ask. After they approve, rerun with `--yes`. If the same approval keeps coming up, raise the limit for
that profile: `fal profile meta <slug> --max-usd 5`.

## Exit 4: auth

- `No fal API key found`: see `references/auth.md`.
- `fal rejected the API key (401)`: the key was revoked or mistyped. Check the fal dashboard.
- `cannot read BWS_ACCESS_TOKEN_FILE`: the path is wrong or not readable; it must hold only the token.
- `bws … failed`: the `BWS_ACCESS_TOKEN` expired, or the machine account lacks access to the project.

## Exit 5: fal API error

- **422 / validation**: fal's own validation is stricter than the schema in some cases (e.g. image dimensions,
  duration combinations). The message names the field.
- **Content policy / NSFW flags**: rephrase the prompt. Don't try to evade the filter.
- **Download failed**: the file URL expired or the network dropped. `fal fetch <run_dir>` downloads the result
  again without billing again.
- **429 / 5xx on metadata calls**: these are retried automatically with backoff. Persistent failures usually mean
  a fal incident (https://status.fal.ai).

## Exit 6: timeout

The job is still running on fal and will be billed whether you wait or not. Resume with `fal fetch <run_dir>`
(or `fal fetch last`). Don't resubmit. Use `fal status <run_dir>` to check the queue position, and
`fal cancel <run_dir>` to stop the job.

## MCP server

- **`plugin:fal:fal-ai` shows as failed in `/mcp`**: the plugin has no key, or a wrong one. Set it in `/plugin` →
  fal → Configure options, then reconnect. To keep the key only in env or Bitwarden, use the user-scope setup in
  auth.md and disable the plugin's server.
- **"Dynamic Client Registration rejected" / OAuth errors**: fal doesn't offer OAuth to Claude Code. Use an API
  key as above.
- **Helper-based setup fails to connect**: the key was rejected (check it with `fal doctor`), or bws took longer
  than the helper's 8 seconds (set `FAL_BWS_SECRET_ID` for a single direct lookup, or export `FAL_KEY`).
- **No MCP server at all** (another agent, or the plugin isn't installed): everything still works through
  `fal models search`, `fal models show` and `fal schema`.

## Workflows

- **`split_sprites.py` exits 3**: the piece count differs from `--expect`. Fewer pieces means assets touch or sit
  closer than `--min-gap`: lower it, regenerate with more spacing, or use `--grid RxC` on a clean grid. More pieces
  means detached parts or specks: raise `--min-gap` or `--min-area`.
- **A local step's output is missing from `--from`**: it wasn't recorded. Run the plan's `then` line
  (`fal ingest … --label <workflow>.<step>`).

## Other

- **uv not installed**: `curl -LsSf https://astral.sh/uv/install.sh | sh`, or use pip as described in SKILL.md.
- **The model catalog seems outdated**: `fal models search … --refresh` (the cache lasts 6 hours).
- **A brand-new model is missing from search**: `fal models show <endpoint_id>` queries the API directly.
- **The output file has a `.bin` extension**: fal returned no content type. Rename the file. The manifest still has
  the URL.
