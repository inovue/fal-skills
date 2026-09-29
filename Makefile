PYTEST = uv run --quiet --with pytest --with "fal-client>=1.0,<2" --with httpx --with jsonschema pytest

.PHONY: test test-live lint validate
test:            ## offline tests (no key, no network, no cost)
	$(PYTEST) -q tests

test-live:       ## includes one real flux/schnell call (~$$0.003)
	FAL_LIVE=1 $(PYTEST) -q tests

lint:
	uvx ruff check skills tests

validate:        ## check SKILL.md frontmatter against the Agent Skills spec
	uv run --quiet --with pyyaml python scripts/validate_skills.py
