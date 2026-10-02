# E07-C3 Charter: retention safety

- Ticket: E07-Q02 (#273) · Format: session-based test management · Date: 2026-10-02
- Tester: AI agent (sprint01-r4). **Deviation:** no docker/scratch compose stack and no 90-minute human timebox were available. The session was executed as a scripted-probe exploration against the in-memory fakes/ports of `TierRouter` and `Reaper` (probe script quoted inline); real-engine behaviour (QuestDB/Parquet) is unverified and listed under Questions. Duration: ~20 min probing, not 90.
- No credentials used.

## Charter
Explore ways to make the reaper delete something it must not.

## Areas covered
Pin applied mid-apply; two reapers applying the same dry-run report.

## Observations / findings
- Pin applied after the first drop: remaining partitions of the pinned symbol were skipped (`pinned`), the unrelated symbol still dropped. Re-check-before-drop works. **No path found that deletes pinned data after the pin is visible.** The partition already dropped when the pin landed is, correctly, unrecoverable-by-design (pin was not yet visible).
- F3 (P2, **BUG-C**): two reapers applying one report both call `drop` and both write `retention.purge` (2 audit rows for one partition). `apply` never re-checks that the partition still exists, so audit over-counts and `storage_retention_dropped_bytes_total` double counts. Not data loss (partition gone). Copied to E07-X02 / Security per ticket (audit integrity, SR-099). No single-run lock exists. Owner: E07-T05.
- Not exercised: pin removed mid-run, replay session created between dry-run/apply (re-check exists in `_blocker`; code-read only), journal trade, manual compaction.

## Follow-ups (promote to E07-Q01)
1. `test_apply_twice_same_report_writes_single_purge_audit` (xfail until BUG-C).
2. `test_pin_applied_between_drops_skips_remaining_partitions`.
3. `test_replay_session_created_between_dry_run_and_apply_blocks_drop`.
