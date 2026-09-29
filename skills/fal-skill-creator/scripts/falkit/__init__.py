"""falkit — the runtime behind the fal-skill-creator skill.

Everything the agent does against fal.ai goes through `scripts/fal.py`, which
dispatches into these modules. Keeping the logic here (instead of in
per-model generated code) means one tested code path for every model.
"""

__version__ = "1.0.0"
