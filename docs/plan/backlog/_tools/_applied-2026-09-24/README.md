# One-shot migration scripts — ALREADY APPLIED, DO NOT RE-RUN

These scripts performed the 2026-09-24 re-plan for full `xstate-statemachine==0.9.1` adoption
(ADR-0016 Accepted; `docs/plan/29-statechart-adoption-plan.md`). They prepend banners and adjust
estimates and are **not idempotent**: re-running would double-prepend and double-apply deltas.

Kept for audit only. The live tooling is `../validate.py` (validator / level-loader) and
`../sync_sprint_plan.py` (regenerates 31-sprint-plan.md from all-tickets.json).
