---
description: Run the Definition-of-Done checklist (C-11.2) against the current branch and report pass/fail per item.
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*), Bash(gh issue view:*), Bash(pnpm:*), Bash(uv run:*), Bash(pytest:*), Bash(ruff:*), Bash(black:*), Bash(mypy:*), Bash(lint-imports:*), Bash(alembic:*), Bash(gitleaks:*), Read, Grep, Glob
---
# /ready-check

Evaluate the current branch against DoD (C-11.2, `docs/plan/02-definition-of-ready-done.md`). Do not fix anything;
report. Output a table: item | PASS/FAIL/N/A | evidence.

1. **Branch & scope:** name matches C-4.4; derive issue # from branch/commits; `git diff --stat origin/main...HEAD`
   ≤400 changed LOC excl. lockfiles/generated (C-4.8); every changed file is in the ticket write set (C-4.9).
2. **Commits:** conventional commits (C-4.10); breaking changes have `!` + footer (C-4.11); no merge commits.
3. **Acceptance criteria:** for each AC in the issue, name the test that proves it. Missing ⇒ FAIL.
4. **Checks (run only those affected by changed paths; commands from `AGENTS.md` §4):**
   - `services/api/**`: `ruff check .`, `black --check .`, `mypy --strict .`, `pytest -m "not integration" --cov=. --cov-fail-under=85`, `lint-imports`
   - migrations: one new revision only; `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
   - statechart: `tools/lint_statecharts.py`, `pytest tests/xstate_contract`, `machine_hashes.lock` updated
   - TS packages: `pnpm lint`, `pnpm typecheck`, `pnpm test:cov`, `pnpm size`
   - chart engine: `pnpm --filter @candleviewer/chart-engine bench` (≤5% regression)
   - UI: Storybook story for each touched CMP-*; `pnpm test:a11y`
   - contracts: `pnpm generate` produces no diff
   - always: `gitleaks protect --staged --redact`
   If a command does not exist yet (pre-INFRA-001), mark N/A with the reason — never invent one.
5. **Docs:** docs named in the ticket updated; `AGENTS.md` §4 updated if scripts changed; ADR if required.
6. **Safety:** no secrets in diff; no flag gating a safety invariant (C-4.14); every `C-x.y` cited exists in CONSTITUTION.md.
7. **Feature flags:** multi-PR features behind a flag (C-4.13).

Finish with `READY FOR PR` or `NOT READY` + the ordered fix list.
