# E07-C4 Charter: operator's mental model

- Ticket: E07-Q02 (#273) · Format: session-based test management · Date: 2026-10-02
- Tester: AI agent (sprint01-r4). **Deviation:** no docker/scratch compose stack and no 90-minute human timebox were available. The session was executed as a scripted-probe exploration against the in-memory fakes/ports of `TierRouter` and `Reaper` (probe script quoted inline); real-engine behaviour (QuestDB/Parquet) is unverified and listed under Questions. Duration: ~20 min probing, not 90 (waiver requested, see E07-waiver.md; probe cases are committed as promoted tests in services/api/tests/unit/storage/retention/test_exploratory_promoted.py).
- No credentials used.

## Charter
Read the storage state as an operator would from the E07-D01 design and the real payload; find where system truth and the screen story diverge.

## Observations / findings
- Operator-visible sources reviewed from code only: `retention.skip/purge/dry_run` audit, `STORAGE_ACCELERATED_RETENTION` event, `storage_disk_free_ratio`, `storage_retention_*` metrics.
- F4 (P3, **BUG-D, #1699**, observability gap): accelerated mode emits per-symbol WARNING events but nothing tells an operator the *effective hot window* shrank, so a "missing recent data on hot" report (see F1) cannot be explained from operator surfaces.
- `projected_full_at`, per-symbol figures during export and unreachable-tier display: **not assessable** - E07-D01/D02 payload and UI not available in the repo state tested.

## Follow-ups
1. Add effective hot window to the accelerated event detail; test in E07-Q01 (BUG-D #1699). Charter 4 is only partially assessable (D01/D02 absent): re-run when E07-D01 lands.
