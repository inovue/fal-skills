<!--
status: unresearched
researched_at:
model: {{endpoint_id}}
Fill this file by following references/prompt-research.md, then run:
  fal.py profile meta <slug> --prompting-status researched
-->
# Prompting guide: {{display_name}}

`{{endpoint_id}}` · {{category}} · [API docs]({{documentation_url}}) · [Playground]({{playground_url}})

> Not researched yet. Until it is, write plain, specific prompts (subject → action → setting → style → camera/lighting)
> and keep the defaults.

## Key rules
<!-- 3–6 bullets. These are the rules the agent has to follow every time. Each one cites a source like [S1]. -->

## Prompt structure
<!-- The order of components the model responds to best, plus the ideal length, language, and whether it
     prefers prose or tags. Note special syntax (weights, reference tokens like @image1, quoted on-screen text,
     speaker tags) only if the sources document it. -->

## Templates
<!-- Named templates with {slots}. Pick one per request, fill every slot, and drop the ones that don't apply.
     Include at least a general-purpose one plus one for each main use case of this model. -->

### general
```text
{subject}, {action}, {setting}. {style}. {composition_or_camera}. {lighting}.
```

## Parameters that matter
<!-- The parameters that change results the most, what to set them to for each use case, and the
     parameters to leave alone. Suggest presets here (`fal.py profile preset …`). -->

| parameter | when to change | recommended |
|---|---|---|

## Negative prompts and limitations
<!-- Is a negative prompt supported? What does the model ignore or get wrong (text rendering, hands, counting,
     motion limits, max duration)? -->

## Examples
<!-- 2–4 prompts copied verbatim from official sources where possible, each with its source. -->

## Sources
<!-- [S1] Title — URL — publisher (official/fal/community) — accessed YYYY-MM-DD -->
