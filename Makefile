.PHONY: governance dev dev-down test gen gen-check up down reset arch security

# E02-T01: root convenience targets delegating to pnpm/uv (20-architecture.md
# §5 Tooling). Thin wrappers only — the pnpm/turbo task graph and the uv/ruff
# commands remain the single source of truth (AGENTS.md §4); this Makefile
# never redefines what they do.
#
# E02-T12: the full dev loop promised by 20-architecture.md §5 — bring up the
# compose stack against `demo` with the synthetic feed (`CV_FEED=synthetic`,
# no Bybit credentials needed), then start the web Vite dev server against
# it. Teardown is `make dev-down` (equivalent to `make down`, named
# separately so the pairing with `make dev` is obvious to a new joiner).
dev:
	$(MAKE) up
	pnpm --filter @candleviewer/web dev

dev-down:
	$(MAKE) down

test:
	pnpm test
	uv run --project services/api pytest -m "not integration"

gen:
	pnpm generate

# E03-T05: generated-code freshness gate (ADR-0013 binding rule 3). Runs
# `make gen` twice to assert determinism (CI-GEN-003), then fails on any
# diff/untracked output under packages/protocol (CI-GEN-001/002). Same
# script `.github/workflows/_job-gen.yml` invokes in CI.
gen-check:
	python tools/ci/check_gen_freshness.py

# E02-T08: local compose stack (`core` + `obs` profiles by default; add
# `--profile cold` for MinIO). `up` waits for all-healthy via
# infra/scripts/healthcheck.sh; `down` stops containers but keeps volumes;
# `reset` also removes named volumes for a clean-state rebuild.
up:
	docker compose -f infra/docker-compose.dev.yml --profile core --profile obs up -d
	infra/scripts/healthcheck.sh core obs

down:
	docker compose -f infra/docker-compose.dev.yml --profile core --profile obs --profile cold down

reset:
	docker compose -f infra/docker-compose.dev.yml --profile core --profile obs --profile cold down -v


# E02-T06: module-boundary architecture gate (CONSTITUTION.md §3, C-3.1..C-3.5,
# §9 #18). Regenerates/checks services/api/.importlinter against
# docs/plan/module-contracts.toml, runs dependency-cruiser (frontend) and
# import-linter (backend). Wired into `pnpm verify`.
arch:
	pnpm arch

# E02-X02: single local entry point for everything the security lane
# (.github/workflows/_job-security.yml) runs, reduced through the same
# tools/ci/security_gate.py policy. Tools unrunnable on this machine
# (no Windows semgrep wheel, no docker) report SKIPPED with a reason
# rather than being silently treated as clean (CI-SEC-005 semantics).
security:
	python tools/ci/run_security_local.py

# GOV-001 (CODEOWNERS coverage check) + GOV-002 (rule-reference link check) +
# GOV-003 (single-source-of-truth duplication check). Stdlib-only Python; runs
# before any package manager is scaffolded (E02). Wired into the `governance`
# job invoked by `pr-metadata` (job creation: E01-Q02). See CONSTITUTION.md
# C-16.4 / C-16.5, C-8.1 / C-10.1.
governance:
	python scripts/check_codeowners_coverage.py --repo-root .
	python scripts/check_rule_refs.py --repo-root .
	python scripts/check_sot_duplication.py --repo-root .
