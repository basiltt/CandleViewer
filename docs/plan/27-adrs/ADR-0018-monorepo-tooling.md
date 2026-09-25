# ADR-0018 — Monorepo tooling: pnpm+Turborepo (JS) and uv+Hatch (Python)

- Status: **Accepted (2026-09-25)**
- Date: 2026-09-25
- Deciders: Owner (`@basiltt`) — see "Agent-delivery adaptations" in ticket E02-K01 (issue #89): owner
  sign-off is recorded via the owner's `approved` comment on the issue or PR merge; this ADR is drafted
  by the implementing agent and awaits that approval.
- Consulted: `docs/plan/20-architecture.md` §5, `docs/plan/30-release-roadmap.md` §4.2/§4.3, `CONSTITUTION.md` §9,
  `docs/plan/02-definition-of-ready-done.md` §5, spike findings `docs/plan/spikes/E02-K01.md`
- Related: E02-T01, E02-T02 (scaffolding tickets that consume this decision), E02-X01 (supply-chain STRIDE model)

---

## Context and problem statement

`docs/plan/20-architecture.md` §5 already names "pnpm workspaces + Turborepo for JS" as the intended
tooling, but leaves the Python packaging/lock tool undecided between `uv`+Hatch and Poetry. Every
subsequent E02/E03 ticket hard-codes whichever choice is made here, so E02-K01 timeboxed a 1-day
practical spike (see `docs/plan/spikes/E02-K01.md` for the full write-up, script and raw numbers) to
close the Python question and to sanity-check the JS choice against this repo's actual gate budgets
(`CONSTITUTION.md` §9; R0 exit criterion 2: commit→dev ≤15 min).

## Decision

1. **JS/TS monorepo: pnpm workspaces + Turborepo.** Confirms the architecture doc's existing choice.
   A throwaway prototype (2 packages with a fan-in dependency + 1 app) ran install, lint, test, build
   and a cross-package task graph correctly out of the box; a warm, fully-cached `turbo run lint test
   build` completed in ~155 ms ("FULL TURBO"), and a cold forced run in ~1.2–3.2 s on this trivial
   skeleton — both far inside the ≤5 min warm / ≤10 min cold gate budgets with headroom for the real
   ruff/mypy/pytest/eslint/tsc/vitest gate. Turborepo's only friction was a v1→v2 config-schema change
   (`pipeline` → `tasks`) and a required `packageManager` field — both one-line fixes, not adoption risks.
2. **Python packaging/lock: `uv` + Hatch.** A throwaway `services/api`-analogue package with the full
   pinned stack named in the ticket (FastAPI/Starlette/uvicorn+uvloop equivalents, numpy, SQLAlchemy 2.0,
   pydantic v2, alembic, duckdb) resolved and installed via `uv sync` in ~15.1 s cold and ~1.9 s warm
   (median of 3). The same skeleton under Poetry took ~50.7 s cold (`poetry lock` ~28.9 s + `poetry
   install` ~21.8 s as two separate steps) and ~2.3 s warm. `uv`'s single-command `sync`, built-in
   editable-install support via `tool.uv.package = true`, and faster cold path make it the better fit for
   the ≤3 min cold-install budget and the ≤15 min total commit→dev budget, especially once mypy-strict and
   the full test suite are added on top of a cold path that is already ~3.4x faster than Poetry's.

## Rejected alternatives

- **Nx** (JS/TS): a real `create-nx-workspace` scaffold was generated for comparison (see spike doc). Nx's
  task-graph/target-inference model is more powerful than Turborepo's (per-project inferred targets, a
  fuller remote-cache product in Nx Cloud) but is materially heavier: ~72 s just to scaffold an empty
  workspace, a 156 MB `node_modules` for the toolchain itself, and a stronger, more opinionated view of
  repo structure that doesn't match CandleViewer's already-fixed layout (`20-architecture.md` §5). For a
  ~6–8 package monorepo with a fixed, already-designed layout, Turborepo's simpler single-file
  `turbo.json` config is the better fit. Reversal cost: low — Nx can adopt a Turborepo-shaped repo later
  (`nx init`) if remote caching or task inference becomes a real pain point; nothing in this decision is
  irreversible.
- **Poetry** (Python): correctness was never in question — the pinned stack installs cleanly — but the
  two-step lock+install cold path is slower and `uv`'s workspace/editable-install story is a more direct
  match for `packages/protocol`-style generated-module consumption inside `services/api`. Reversal cost:
  low-to-moderate — both use standard `pyproject.toml`; migrating means regenerating a lockfile and
  swapping the `[build-system]` backend, no source-code changes.

## Consequences

- E02-T01/T02 (scaffolding tickets) proceed with pnpm+Turborepo and uv+Hatch; both are already implied by
  `20-architecture.md` §5, so no `docs/plan/20-architecture.md` edit is required — this ADR formalizes the
  Python half that document already flagged as pending.
- No new toolchain risk surfaced beyond what's already tracked; `docs/plan/32-risk-register.md` is left
  unchanged (see spike doc "Definition of Done" checklist).
- CI workflow authoring (E03) can now assume `pnpm`/`turbo` and `uv`/Hatch without a placeholder.

## Deviation note

The ticket body names `docs/plan/27-adrs/ADR-0018-monorepo-tooling.md`, which matches the next free
number in `docs/plan/27-adrs/` at merge time (ADR-0001…0017 taken). No deviation was needed.
