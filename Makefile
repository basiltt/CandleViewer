.PHONY: governance dev test gen up

# E02-T01: root convenience targets delegating to pnpm/uv (20-architecture.md
# §5 Tooling). Thin wrappers only — the pnpm/turbo task graph and the uv/ruff
# commands remain the single source of truth (AGENTS.md §4); this Makefile
# never redefines what they do.
dev:
	pnpm --filter @candleviewer/web dev

test:
	pnpm test
	uv run --project services/api pytest -m "not integration"

gen:
	pnpm generate

up:
	docker compose -f infra/docker-compose.dev.yml up -d

# GOV-001 (CODEOWNERS coverage check) + GOV-002 (rule-reference link check) +
# GOV-003 (single-source-of-truth duplication check). Stdlib-only Python; runs
# before any package manager is scaffolded (E02). Wired into the `governance`
# job invoked by `pr-metadata` (job creation: E01-Q02). See CONSTITUTION.md
# C-16.4 / C-16.5, C-8.1 / C-10.1.
governance:
	python scripts/check_codeowners_coverage.py --repo-root .
	python scripts/check_rule_refs.py --repo-root .
	python scripts/check_sot_duplication.py --repo-root .
