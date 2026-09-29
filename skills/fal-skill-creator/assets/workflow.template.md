# {{name}}

<!--
This file becomes the body of the exported skill. Write it for an agent that has never seen this workflow.
Keep model-specific prompting advice in each profile's prompting.md; keep here only what this workflow adds.
See references/workflows.md in fal-skill-creator for the format and the design rules.
-->

One or two sentences: what the user gets, and why these steps in this order.

## 1. Ask first (one message, only what's missing)

- …

## 2. `<step-id>`: <what this step does>

Prompt template (for fal steps that take a prompt), with `{slots}`:

```
…
```

Check before continuing: … (what a bad result looks like, and what to do about it)

## 3. `<step-id>`: …

## Report

What to hand back: files, sizes, the total cost (`fal runs list`), and anything that went wrong.
