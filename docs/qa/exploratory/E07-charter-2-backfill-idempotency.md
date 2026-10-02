# E07-C2 Charter: backfill and replay idempotency

- Ticket: E07-Q02 (#273) · Format: session-based test management · Date: 2026-10-02
- Tester: AI agent (sprint01-r4). **Deviation:** no docker/scratch compose stack and no 90-minute human timebox were available. The session was executed as a scripted-probe exploration against the in-memory fakes/ports of `TierRouter` and `Reaper` (probe script quoted inline); real-engine behaviour (QuestDB/Parquet) is unverified and listed under Questions. Duration: ~20 min probing, not 90.
- No credentials used.

## Charter
Explore repeated and partial ingestion of the same data to discover row-count drift.

## Areas covered
`dedup_merge` with a field-altered row; `orderbook_snapshots` with differing `epoch_id`; natural keys per `natural_keys.py`.

## Observations / findings
- Altered `price` on same `(ts,symbol,trade_id)`: treated as the *same* row, last writer (hot) wins, no divergence signal. This matches `DEDUP UPSERT KEYS(ts, symbol, trade_id)` (intended), but a silent overwrite of a differing payload is not observable by an operator. F2 (P3, **BUG-B**): emit a metric/log when a dedup collision has differing non-key fields. Owner: E07-T05.
- Same `(ts,symbol,depth)` with `epoch_id` 1 vs 2: kept as 2 rows (key includes `epoch_id`) - intended.
- Not exercised (needs real engine): two-symbol interleaved replay; rows older than retention horizon being re-ingested then reaped.

## Questions
Is a row ingested with `ts` older than the retention horizon accepted and then reaped immediately? Needs QuestDB.

## Follow-ups (promote to E07-Q01)
1. `test_dedup_same_key_altered_field_last_writer_wins_documented`.
2. `test_dedup_epoch_id_distinguishes_snapshots`.
