# Pipelines and the run manifest contract

Every `fal run` produces a self-describing run directory. Pipelines are built by pointing a later run at an
earlier run's manifest. The manifest format is stable (`fal-manifest@1`), so other skills, scripts and tools can
produce or consume it too.

## Contents
1. Directory layout
2. manifest.json schema
3. Referencing earlier runs (REF syntax)
4. Auto-wiring rules
5. Local steps (`fal ingest`)
6. Recipes
7. Using manifests from other tools

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
  "prompt_template": {                  // null when the prompt was passed as is
    "name": "general", "source": "/abs/…/profiles/flux-schnell/prompting.md",
    "slots": { "subject": "a red fox", "style": "" }, "field": "prompt"
  },
  "pricing": { "unit_price": 0.003, "unit": "megapixels", "currency": "USD", "fetched_at": "…" },  // the API's unit price
  "price_estimate": { "usd": 0.0032, "basis": "$0.003 per megapixel …", "checked": "2026-09-30" },  // researched table
  "seed": 461529223,
  "outputs": [
    {
      "field": "images.0",             // path of the file object inside result.json
      "kind": "image",                 // image | video | audio | 3d | file
      "url": "https://v3b.fal.media/…",
      "content_type": "image/png",
      "width": 1024, "height": 1024,   // from fal, or measured locally (images; video/audio with ffprobe)
      "duration": 5.17, "fps": 24, "has_audio": true,   // video and audio, measured with ffprobe when installed
      "local_path": "/abs/…/images-0.png",
      "bytes": 1540450,
      "sha256": "…"
    }
  ],
  "text": { "caption": "…" },          // short string fields of the result (captions, transcripts)
  "run_dir": "/abs/…",
  "runtime_version": "1.2.0"
}
```

Outputs are found generically: any object in the result that has a `url` is treated as a file. This covers
`images[]`, `video`, `audio_file`, `model_mesh`, and so on, with no per-model code.

## 3. Referencing earlier runs

| REF | meaning |
|---|---|
| `last` | the most recently completed run in this output root |
| `last~1`, `last~2` | the runs before that |
| `label:TAG`, `label:TAG~1` | the newest run with `--label TAG` (and the one before it); workflows label steps `<workflow>.<step>` |
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
2. Each field gets a media kind from its name. An explicit medium wins (`reference_video_urls` is video); generic
   words (`reference`, `frame`, `face`, `style`) mean image; anything else gets `any`.
3. **Each `--from REF` fills exactly one field**: the first empty one, required fields first, then schema order,
   whose kind matches one of the run's outputs. It takes the first fitting output; `REF#1` (index), `REF#image`
   (kind) or `REF#images.1` (field) pick another, and `REF#*` passes all of them into a list field. The rest of the
   run's outputs are never spilled into other fields: with a two-variant image run and a model that takes
   `image_url` and `end_image_url`, only `image_url` is filled. Use a second `--from` for the second field.
4. Every decision is printed as `wired: field ← run#output`. Read these lines; `--set field=from:REF#sel` is the
   explicit alternative.

## 5. Local steps (`fal ingest`)

When you process files yourself between models (split a sheet, crop, composite, ffmpeg), record the results:

```bash
uv run split_sprites.py "$(fal runs files label:cutout --kind image | head -1)" --out work/split
fal ingest work/split --label split --parent label:cutout --move
fal run -p upscaler --set image_url=from:label:split#3      # the 4th piece
```

`ingest` copies the files into a new run directory, writes a manifest (`endpoint_id: "local"`, kinds from
file extensions, image sizes from PNG and JPEG headers), and appends to `index.jsonl`. Its outputs have
`url: null`, so a later fal run uploads the local copy when it needs a URL. `--parent` keeps the lineage intact.

## 6. Recipes

Each prompted step renders a template from its own profile, so each model gets the prompt style it was researched
for: an image model's composition language for the keyframe, a video model's camera language for the motion.

**Keyframe, then animate, then upscale**
```bash
fal run -p flux-dev -t establishing --slot subject="…" --slot … --label keyframe
# look at the image first, then:
fal run -p kling-i2v --from last -t camera-move --slot motion="slow push-in" --slot ambience="snow drifting" --label anim
fal run -p video-upscaler --from last --label final
```

**First and last frame video**
```bash
fal run -p flux-dev -t general --slot … --label start
fal run -p flux-dev -t general --slot … --label end      # same template and seed keep the two frames consistent
fal run -p veo-flf --set first_frame_url=from:label:start --set last_frame_url=from:label:end -t transition --slot …
```

**Speech, then a talking head**
```bash
fal run -p tts -t narration --slot script="…" --label vo    # fills the model's `text` field
fal run -p lipsync --set audio_url=from:last#audio --set image_url=@./portrait.png
```

**Variations, then the best one onward.** Use `--batch` with one line per variant. Review them, then pass the
chosen run id explicitly: `--from <run_id>`.

**Pay for the expensive step only after checking the cheap one.** Stop between steps, show the user the
intermediate result, and only then continue. Video generation often costs 10–100× more than a keyframe, and a bad
keyframe can't be fixed by the video model.

## 7. Using manifests from other tools

- **Other fal-\* skills** (exported with `fal export`) ship the same runtime, so `--from` works across them
  whenever they share the output root. Keep the default `./fal-outputs`, or set `FAL_OUTPUT_DIR` once.
- **Non-fal tools** (ffmpeg, editors, upload scripts) read `outputs[].local_path`:
  `jq -r '.outputs[] | select(.kind=="video") | .local_path' fal-outputs/…/manifest.json`
- **Feeding external files into `--from`**: `fal ingest <files> --label <tag>` writes a proper manifest for them.
