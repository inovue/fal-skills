# Troubleshooting

Start with `fal doctor`. Set `FALKIT_DEBUG=1` to get full tracebacks for unexpected errors (exit code 1).

## Exit 2: usage or validation

| symptom | fix |
|---|---|
| `Arguments do not match the model schema: x: 'foo' is not one of [...]` | Use one of the listed values. `fal schema <endpoint>` lists every parameter. |
| `unknown parameter 'x'` (a warning) | Usually a typo. Unknown keys are sent anyway, but fal may ignore them. |
| `Profile 'x' not found` | `fal profile list`. Profiles are per scope: a project profile lives in `./.fal/profiles`. |
| `Cannot resolve run reference` | `fal runs list`. Note that `last` means the last *completed* run in the current output root. |
| Pinned defaults fail after a model update | `fal profile refresh <slug>`, then fix them with `profile set` / `--unset`. |

## Exit 3: cost guard

The estimate is above the limit, or it couldn't be computed and the unit price is above $0.05. Show the user the
estimate and ask. After they approve, rerun with `--yes`. If the same approval keeps coming up, raise the limit for
that profile: `fal profile meta <slug> --max-usd 5`.

## Exit 4: auth

- `No fal API key found`: see `references/auth.md`.
- `fal rejected the API key (401)`: the key was revoked or mistyped. Check the fal dashboard.
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

## Other

- **uv not installed**: `curl -LsSf https://astral.sh/uv/install.sh | sh`, or use pip as described in SKILL.md.
- **The model catalog seems outdated**: `fal models search … --refresh` (the cache lasts 6 hours).
- **A brand-new model is missing from search**: `fal models show <endpoint_id>` queries the API directly.
- **The output file has a `.bin` extension**: fal returned no content type. Rename the file. The manifest still has
  the URL.
