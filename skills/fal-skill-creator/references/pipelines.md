# Pipelines and the run manifest contract

Every `fal run` produces a self-describing run directory. Pipelines are built by pointing a later run at an
earlier run's manifest. The manifest format is stable (`fal-manifest@1`), so other skills, scripts and tools can
produce or consume it too.

## Contents
1. Directory layout
2. manifest.json schema
3. Referencing earlier runs (REF syntax)
4. Auto-wiring rules
5. Recipes
6. Using manifests from other tools

## 1. Directory layout

```
fal-outputs/                     # --out / $FAL_OUTPUT_DIR
├── index.jsonl                  # one line per completed run (append-only history)
└── 2026-09-29/
    └── 20260929-013913-flux-schnell-fox-5db08a/     # <time>-<profile>-<label>-<rand>
        ├── images-0.png         # media, named after the output field
        ├── request.json         # what was submitted (+ status: submitted/completed/failed/rejected)
        ├── result.json          # raw fal result (base64 data URIs truncated)
        └── manifest.json        # the contract below
```

`request.json` is written before submission and updated as the run progresses. A crash or timeout never loses the
`request_id`, so `fal fetch <run_dir>` can always finish the run later.

## 2. manifest.json

```jsonc
{
  "format": "fal-manifest@1",
  "run_id": "20260929-013913-flux-schnell-fox-5db08a",
  "created_at": "2026-09-29T01:39:13+0000",
  "completed_at": "2026-09-29T01:39:20+0000",
  "endpoint_id": "fal-ai/flux/schnell",
  "profile": "flux-schnell",            // null for raw --endpoint runs
  "request_id": "01a0…",               // fal queue request id
  "label": "fox",
  "arguments": { "...": "exact arguments sent (uploaded files appear as their URLs)" },
  "input_sources": { "image_url": "20260929-…#images.0" },   // where each media input came from
  "parents": ["/abs/path/to/parent/manifest.json"],          // lineage for multi-step pipelines
  "cost_estimate": { "usd": 0.0032, "unit": "megapixels", "unit_price": 0.003, "quantity": 1.05, "confidence": "high" },
  "seed": 461529223,
  "outputs": [
    {
      "field": "images.0",             // path of the file object inside result.json
      "kind": "image",                 // image | video | audio | 3d | file
      "url": "https://v3b.fal.media/…",
      "content_type": "image/png",
      "width": 1024, "height": 1024,   // when fal reports them (also duration, fps, file_size)
      "local_path": "/abs/…/images-0.png",
      "bytes": 1540450,
      "sha256": "…"
    }
  ],
  "text": { "caption": "…" },          // short string fields of the result (captions, transcripts)
  "run_dir": "/abs/…",
  "runtime_version": "1.0.0"
}
```

Outputs are found generically: any object in the result that has a `url` is treated as a file. This covers
`images[]`, `video`, `audio_file`, `model_mesh`, and so on, with no per-model code.

## 3. Referencing earlier runs

| REF | meaning |
|---|---|
| `last` | the most recently completed run in this output root |
| `last~1`, `last~2` | the runs before that |
| `<run_id>` | a specific run (from `fal runs list`) |
| `<run_dir>` or `<…/manifest.json>` | a path, which also works across output roots and projects |

Two ways to use a REF:

- `--from REF`, repeatable, auto-wires empty media inputs (see section 4).
- `--set field=from:REF#sel` wires explicitly. `#sel` is optional:
  - `#0`, `#1`: the output at that index
  - `#image`, `#video`, `#audio`: the first output of that kind
  - `#images.1`: the output with that exact field path
  - `#*`: all outputs, as a list (for `*_urls` fields)

An output's hosted URL is reused when a quick HEAD request succeeds. Otherwise the local copy is uploaded again,
so pipelines keep working after the CDN URL expires.

## 4. Auto-wiring rules (`--from`)

1. The candidate fields are the input fields that look like media (`*_url`, `*_urls`, `image`, `audio_file`, or
   `format: uri`) and are still empty after defaults, presets, `--input`, and `--set` are applied.
2. Each field gets a media kind from its name: image-like names (`image`, `mask`, `reference`, `frame`, `face`,
   `style`), video-like names, audio-like names (`audio`, `voice`, `speech`, `music`), and 3D names. Anything
   else gets `any`.
3. Required fields are filled before optional ones, in schema order. Each output is used once. A list field
   takes every remaining output of its kind.
4. Every decision is printed as `wired: field ← run#output`. Read these lines. If a guess is wrong (e.g. a model
   has both `image_url` and `end_image_url`), use explicit `--set` for the ambiguous field.

## 5. Recipes

**Keyframe, then animate, then upscale**
```bash
fal run -p flux-dev --prompt "…" --label keyframe
# look at the image first, then:
fal run -p kling-i2v --from last --prompt "slow push-in, snow drifting" --label anim
fal run -p video-upscaler --from last --label final
```

**First and last frame video**
```bash
fal run -p flux-dev --prompt "…start…" --label start
fal run -p flux-dev --prompt "…end…" --label end
fal run -p veo-flf --set first_frame_url=from:last~1 --set last_frame_url=from:last --prompt "…"
```

**Speech, then a talking head**
```bash
fal run -p tts --prompt "…script…" --label vo
fal run -p lipsync --set audio_url=from:last#audio --set image_url=@./portrait.png
```

**Variations, then the best one onward.** Use `--batch` with one line per variant. Review them, then pass the
chosen run id explicitly: `--from <run_id>`.

**Pay for the expensive step only after checking the cheap one.** Stop between steps, show the user the
intermediate result, and only then continue. Video generation often costs 10–100× more than a keyframe.

## 6. Using manifests from other tools

- **Other fal-\* skills** (exported with `fal export`) ship the same runtime, so `--from` works across them
  whenever they share the output root. Keep the default `./fal-outputs`, or set `FAL_OUTPUT_DIR` once.
- **Non-fal tools** (ffmpeg, editors, upload scripts) read `outputs[].local_path`:
  `jq -r '.outputs[] | select(.kind=="video") | .local_path' fal-outputs/…/manifest.json`
- **Producing a manifest by hand** (to feed an external file into `--from`): write a minimal
  `{"format":"fal-manifest@1","run_id":"ext-1","outputs":[{"kind":"image","local_path":"/abs/x.png","url":null}]}`.
  The runtime uploads `local_path` because `url` is null.
