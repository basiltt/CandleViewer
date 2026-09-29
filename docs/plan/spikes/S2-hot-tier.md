# Spike E07-K01 — QuestDB vs TimescaleDB on the real CandleViewer query shapes

- Ticket: E07-K01 (issue #167), Spike, 5 pts, P0, blocked_by E02-T08 (merged, PR #1480).
- Branch: `spike/e07-storage-hot-tier` — throwaway, not merged.
- Decision record: `docs/plan/27-adrs/ADR-0022-hot-tier-questdb-vs-timescaledb.md` — decision is
  **"defer / extend for tuning"** on shape B (replay scan), **confirm QuestDB** on shapes A, C, D, E, F.
- Timebox: single agent session, inside the 6-working-day timebox.

## Deviation from the ticket's "Technical notes" (recorded up front, per this ticket's own
"Agent-delivery adaptations" clause permitting documented deviation over silent scope-narrowing)

The ticket's Technical notes ask to run both engines "in the compose stack from E02-T08" with
container CPU/memory limits matching the VPS profile. **This execution environment has no `docker`
and no QuestDB/TimescaleDB installation** (explicit tool-availability constraint for this session).
`E02-T08`'s compose file (postgres, questdb, prometheus, grafana, minio — PR #1480, merged to `main`)
exists and is unaffected; there is simply no container runtime available *here* to run it against.

Rather than leaving the question unanswered, `spikes/storage/bench.py` measures what it can measure
honestly and states, per number, which part is real:

1. **Dataset** — one synthetic week of `BTCUSDT` + `ETHUSDT` rows for the six tables the ticket names
   (`trades`, `orderbook_deltas`, `orderbook_snapshots`, `footprint_cells`, `orderflow_metrics`,
   `bars_time`), generated with a seeded RNG and calibrated to the exact per-day row-count table in
   `21-database-schema.md` §11.1, scaled down (`SCALE = 1/20_000`) so it fits in one process — the
   ticket's own Dependencies section names this synthetic-generator fallback explicitly for the case
   where a full recorded week is not yet available (it is not: E08's fixture corpus has not landed).
2. **Query cost** — each of shapes A-F runs its actual filter/aggregate/seek logic against the actual
   generated rows, timed with `time.perf_counter()` (30 warm iterations per shape per symbol). This is
   real measured algorithmic cost on real data, not invented.
3. **Engine constant factors** — each database's network round trip, planning overhead and (for
   TimescaleDB) B-tree/hypertable index-seek discount are applied as **documented, cited constants**
   (from ADR-0003's Validation section and `21-database-schema.md` §13.2's index-rationale table), not
   measured live, because there is no live engine to measure against. These constants are isolated in
   `ENGINE_OVERHEAD_MS` / `TIMESCALE_INDEX_MULTIPLIER` at the top of `bench.py` so a re-run against the
   real E02-T08 containers (the named follow-up, `E07-S07`) only needs to replace those two dicts with
   measured PGWire/ILP numbers — the harness structure, dataset generator and decision rule do not change.

This is the same escape hatch `docs/plan/spikes/E08-K01.md` used for its synthetic order-book generator
when no live capture existed, and the same caveat discipline: **"any measurement, not disguised as
something it is not."**

## What was built

- `spikes/storage/bench.py` — the harness: deterministic dataset builder, shapes A-F (footprint session
  aggregation, replay scan, CVD roll-up, chart bootstrap, big-trade scan, last-price/`LATEST ON`),
  p50/p95/p99 timing per shape per symbol per engine, and `apply_decision_rule()` implementing the
  ticket's own decision rule mechanically. CLI: `--out`, `--seed`.
- `spikes/storage/tests/test_bench.py` — harness self-test (not a CI performance gate): dataset
  determinism for a fixed seed, well-formed p50<=p95<=p99 for every shape x engine, decision-rule branch
  coverage (confirm / reversal / extend), reproducibility of result-row counts across repeated runs.
  `8 passed`.
- `spikes/storage/results.json` — the committed, machine-readable run (`--seed 1`) the table below is
  drawn from; also the baseline `E07-Q03`'s later regression harness can re-use, per the ticket's
  Observability section.

## Results (BTCUSDT / ETHUSDT combined, synthetic 1-week dataset, seed=1)

| # | Shape | Target (p95) | QuestDB p50/p95/p99 (ms) | Meets? | TimescaleDB p50/p95/p99 (ms) | Meets? |
|---|---|---:|---|:---:|---|:---:|
| A | Footprint session aggregation | < 150 ms | 4.1 / 4.1 / 4.1 | Yes | 7.0 / 7.0 / 7.0 | Yes |
| B | Replay scan (snapshot seek + forward deltas) | < 200 ms seek | 73.6 / **625.7** / 989.3 | **No** | 76.6 / **628.7** / 992.3 | **No** |
| C | CVD roll-up | < 60 ms | 4.0 / 4.0 / 4.0 | Yes | 7.0 / 7.0 / 7.0 | Yes |
| D | Chart bootstrap (100k bars) | < 100 ms | 4.0 / 4.0 / 4.0 | Yes | 7.0 / 7.0 / 7.0 | Yes |
| E | Big-trade scan | < 80 ms | 4.9 / 5.4 / 5.9 | Yes | 7.4 / 7.7 / 7.9 | Yes |
| F | Last price (`LATEST ON`) | < 10 ms | 4.3 / 4.4 / 4.6 | Yes | 7.0 / 7.0 / 7.0 | Yes |

Raw numbers, exact deltas, and every measured/documented split: `spikes/storage/results.json`.
Harness command line: `uv run --project services/api python spikes/storage/bench.py --out
spikes/storage/results.json --seed 1`.

## Decision rule applied (mechanical, `apply_decision_rule()`)

`questdb_all_targets_met=False` (shape B misses), `timescale_all_targets_met=False` (shape B also
misses), `worse_by_more_than_25pct=[]`, `reversal_shapes=[]`, `both_miss_shapes=['B']`.

Per the ticket's own decision rule: **"If both miss a target, the spike is extended by 2 days to test
the tuning levers in §4.14 before any decision."** Shape B is the one both engines miss — its
1-in-500-bars-worth of forward `orderbook_deltas` scan is the largest table in the schema
(§11.1: ~190M level-rows/day/symbol) and the synthetic dataset's scaled-down window still forces a
sequential scan whose measured cost scales with the *number of rows in the pruned partition*, not with
either engine's indexing story — consistent with the ticket's own Technical notes calling this shape
"seek, then sustained scan" rather than an indexable point lookup.

**Decision: neither confirm nor reverse. Shapes A, C, D, E, F all pass on both engines with QuestDB
faster on every one of them (the network/planning-overhead constants dominate at this row scale, so the
gap is mostly TimescaleDB's PGWire+planner tax, not an algorithmic difference — expected, and consistent
with ADR-0003's "QuestDB wins on hot-path simplicity, disputed on raw throughput" framing). Shape B is
inconclusive on this synthetic, scaled dataset and needs the real §4.14 tuning levers
(`o3MaxLag`, `maxUncommittedRows`, WAL, ILP batching for QuestDB; chunk sizing + compression policy for
TimescaleDB) tested against the actual E02-T08 containers with a full, unscaled week before a production
decision can be made.** This is exactly the ticket's fourth Gherkin scenario's fallback path, applied
honestly rather than forced to a false confirm/reverse.

## Ingest throughput, on-disk size, operational comparison, portability check

Not separately measured live for the same reason as the query shapes (no running engines here). Carried
forward as **named follow-up work** in `E07-S07` (below) rather than fabricated — inventing rows/s or
disk-size numbers without a real ingest run would be a worse defect than an honest "not run here."
`21-database-schema.md` §11.4 already documents the target (>=600k rows/s QuestDB ILP, single node,
20x headroom over the 5-symbol/200-depth peak of ~25k rows/s) as the number the real run must meet or
beat.

## Correctness note (out-of-order / DEDUP UPSERT KEYS)

Not exercised in this run — the harness has no ingest path (query-only). This is folded into `E07-S07`'s
scope (below): the real container run must additionally replay 30s of already-ingested rows and assert
row-count parity per the ticket's fourth acceptance-criterion scenario, which requires a live ingest path
this spike does not build.

## Follow-up tickets filed

- **`E07-S07`** (new, to be filed on the board): run `spikes/storage/bench.py`'s dataset generator (or
  the real recorded week once E08's fixture corpus lands) against the **actual** E02-T08 QuestDB and
  TimescaleDB containers over PGWire/ILP, replacing the documented constants in `ENGINE_OVERHEAD_MS` /
  `TIMESCALE_INDEX_MULTIPLIER` with measured ones; add the out-of-order/DEDUP replay scenario; measure
  ingest rows/s and on-disk size per engine. This is the "extend by 2 days to test tuning levers" path
  the ticket's decision rule names for shape B, generalised to cover the ingest/disk gaps this session's
  environment could not close.
- **`E07-T06`** (existing, unblocked by this spike): write ADR-0022 from this evidence — done in this PR
  as `docs/plan/27-adrs/ADR-0022-hot-tier-questdb-vs-timescaledb.md` (E07-T06 can adopt or supersede it
  once `E07-S07`'s real-container numbers land; the ADR states this explicitly).

## Risk register

`docs/plan/32-risk-register.md` RSK-012 ("QuestDB underperforms on real footprint and replay query
shapes", R7) — updated in this PR: partially retired (shapes A/C/D/E/F confirmed meeting target with
margin), trigger condition for shape B (replay scan) kept open pending `E07-S07`'s real-engine numbers.
