# {{name}}

<!--
This file becomes the body of the exported skill. Write it for an agent that has never seen this workflow.
Put each prompted step's template here as a ```template <name> block and name it in the step's "template"
field in workflow.json. Write it with the step's profile's prompting.md open: follow its key rules and prompt
structure, and keep only what this workflow adds (layout, consistency constraints, what the next step needs).
See references/workflows.md in fal-skill-creator for the format and the design rules.
-->

One or two sentences: what the user gets, and why these steps in this order.

## 1. Ask first (one message, only what's missing)

- …

## 2. `<step-id>`: <what this step does>

Template (the profile's key rules applied: …):

```template <step-id>
…{slot}…
```

- `{slot}`: what goes here, and a default when the user doesn't say.

Check before continuing: … (what a bad result looks like, and what to do about it)

## 3. `<step-id>`: …

## Report

What to hand back: files, sizes, the runs used (`fal runs list`), and anything that went wrong.
