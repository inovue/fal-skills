PYTEST = uv run --quiet --with pytest --with "fal-client>=1.0,<2" --with httpx --with jsonschema --with pillow pytest
SKILL_LINK = $(HOME)/.claude/skills/fal-skill-creator

.PHONY: test test-live lint validate link unlink
test:            ## offline tests (no key, no network, no cost)
	$(PYTEST) -q tests

test-live:       ## includes one real flux/schnell call (~$$0.003)
	FAL_LIVE=1 $(PYTEST) -q tests

lint:
	uvx ruff check skills tests

validate:        ## check SKILL.md frontmatter against the Agent Skills spec
	uv run --quiet --with pyyaml python scripts/validate_skills.py

link:            ## load this working copy as a global Claude Code skill (disable the plugin copy first)
	ln -sfn $(CURDIR)/skills/fal-skill-creator $(SKILL_LINK)
	@echo "linked: $(SKILL_LINK) -> $(CURDIR)/skills/fal-skill-creator"

unlink:          ## remove the global link (then re-enable the plugin copy)
	rm -f $(SKILL_LINK)
