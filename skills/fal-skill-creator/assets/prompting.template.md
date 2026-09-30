<!--
status: unresearched
researched_at:
model: {{endpoint_id}}
Fill this file by following references/prompt-research.md. `fal.py profile check <slug>` shows what is still
missing; `fal.py profile meta <slug> --prompting-status researched` is refused until the check passes.
-->
# Input guide: {{display_name}}

`{{endpoint_id}}` · {{category}} · [API docs]({{documentation_url}}) · [Playground]({{playground_url}})

> Not researched yet. Until it is, write plain, specific prompts (subject → action → setting → style → camera/lighting)
> and keep the defaults.

## Key rules
<!-- 3–6 bullets the agent applies on every request, each citing a source like [S1]. The rules that most change
     the result for THIS model: prose or tags, what goes first, how to quote on-screen text, how references are
     named, what the model ignores. -->

## Prompt structure
<!-- The order of components the model follows best, the ideal length, language support (does Japanese work, or
     should the prompt be translated?), and special syntax only if the sources document it: quoted text, reference
     tokens like @image1, weights, speaker tags, timestamps, camera terms. -->

## Inputs
<!-- Everything besides the prompt that the model reads. For each media input (image_url, reference images, start
     and end frames, audio, video, masks): accepted formats, best resolution and aspect ratio, size and count limits,
     what makes a good reference (clean background, one subject, matching aspect ratio), and how the prompt should
     refer to it. For text-only models: language, length limits, and anything to strip (markdown, emoji). -->

## Templates
<!-- One ```template <name> block per main use case, plus `general` and a 1–3 slot `quick` one. Slots are
     {snake_case} and must be filled (`--slot name=value`); optional parts go in [[ … ]] and drop whole when their
     slots aren't given; {=param} inserts a model parameter's value (e.g. {=duration}). After each block, one line
     on when to use it. `fal.py profile check` renders every template both ways and rejects broken text. -->

```template general
{subject}, {action}.[[ Setting: {setting}.]][[ Style: {style}.]][[ Composition: {composition}.]][[ Lighting: {lighting}.]]
```
When no specific template fits.

## Parameters that matter
<!-- The parameters that change results the most, what to set them to per use case, and which to leave alone.
     Suggest presets here (`fal.py profile preset …`). -->

| parameter | when to change | recommended |
|---|---|---|

## Limitations
<!-- Is a negative prompt supported? What does the model ignore or get wrong (text rendering, hands, counting,
     motion limits, max duration)? What should the agent warn the user about instead of retrying? -->

## Examples
<!-- 2–4 prompts copied verbatim from official sources, each with its source. -->

## Sources
<!-- [S1] Title — URL — publisher (official/fal/community) — accessed YYYY-MM-DD -->
