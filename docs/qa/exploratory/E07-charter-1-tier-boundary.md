# E07-C1 Charter: tier boundary

- Ticket: E07-Q02 (#273) · Format: session-based test management · Date: 2026-10-02
- Tester: AI agent (sprint01-r4). **Deviation:** no docker/scratch compose stack and no 90-minute human timebox were available. The session was executed as a scripted-probe exploration against the in-memory fakes/ports of `TierRouter` and `Reaper` (probe script quoted inline); real-engine behaviour (QuestDB/Parquet) is unverified and listed under Questions. Duration: ~20 min probing, not 90.
- No credentials used.

## Charter
Explore reads whose ranges interact with the hot/cold boundary, with the boundary moving underneath them, to discover gaps, duplicates or ordering breaks.

## Areas covered
Straddle merge ordering; hot-wins-ties; clock stepping backwards by 3 days; boundary vs a range of [now-31d, now-29d) with hot_retention=30d.

## Observations / findings
- F1 (P2, **BUG-A**) Accelerated retention vs router boundary: the reaper halves `hot_days` when free disk < threshold (a 20-day-old exported hot partition is dropped), but `TierRouter.boundary_us` keeps using the full `hot_retention` (30 d). A read for that 20-day range resolves `hot`, so the router serves nothing for it (data exists only in cold). Repro: reaper `free=8%`, partition aged 20 d, TierRouter hot_days=30 -> `resolve()` = `hot`. Expected: `both`/`cold`. Owner: E07-T05.
- Clock stepping back 3 d flips `both` -> `hot` for the same range (boundary moves back); consequence is the same class as F1 if hot rows were already dropped. Router has no monotonic-clock guard. Info/P3.
- Ties: on equal natural key the hot row wins; output order for equal `ts` but different keys is stable. OK.
- Not exercised (needs real engine): read concurrent with `DROP PARTITION`; `hot_retention` change mid-scan.

## Questions
Should router boundary be derived from the same source as the reaper's effective (accelerated) window?

## Follow-ups (promote to E07-Q01 suite)
1. `test_router_resolves_cold_when_reaper_accelerated_window_shrinks` (xfail until BUG-A fixed).
2. `test_router_clock_step_back_does_not_lose_rows`.
