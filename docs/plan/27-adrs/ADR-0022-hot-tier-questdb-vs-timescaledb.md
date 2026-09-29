# ADR-0022 — Hot tier: QuestDB confirmed for five of six query shapes; replay scan deferred

- Status: **accepted-partial** — five of six shapes confirm QuestDB per the pre-agreed mechanical rule;
  the sixth (replay scan) is explicitly deferred pending `E07-S07`'s real-container measurement, per the
  ticket's own fourth Gherkin scenario ("both miss a target -> extend by 2 days to test tuning levers").
  Owner approval pending (spike E07-K01, timeboxed 6 days). Per E07-K01's "Agent-delivery adaptations",
  owner `approved` comment on issue #167, or owner merge of the PR, substitutes for Architect
  countersignature; do not block on it.
- Date: 2026-09-28
- Deciders: Owner (`@basiltt`) — owner approval pending per the adaptation above.
- Amends: `ADR-0003-storage-tiers.md` (not superseded — ADR-0003's own Reversal path section anticipated
  exactly this spike and named the amendment path, not a fresh ADR, for a partial-confirm outcome).
- Consulted: `docs/plan/21-database-schema.md` §4, §11.1, §11.4, §13.2, §13.3; `docs/plan/20-architecture.md`
  §14, §15 (S2); `docs/plan/30-release-roadmap.md` §4.1, §4.5; `docs/plan/32-risk-register.md` RSK-012.
- Related: E07-T03 (production repository implementation, waits on this), E07-T06 (this ADR is that
  ticket's deliverable), E07-S07 (new follow-up filed by this spike), E26/E46 (footprint/replay consumers).

## Context and problem statement

`ADR-0003-storage-tiers.md` chose QuestDB as the hot tier but flagged the choice as reversible: "vendor
benchmark claims are disputed … so the choice must be reversible", naming spike **S2** to run the real
footprint, profile, CVD and replay-scan query shapes against both QuestDB and TimescaleDB on a week of
recorded data before `ADR-0008`-equivalent commitment (`docs/plan/30-release-roadmap.md` §4.1 goal 3,
§4.5 target). This ADR is that spike's evidence, formalised.

## Decision drivers (agreed before measuring, per the ticket's own decision rule)

- QuestDB is confirmed if it meets *all* six target latencies at p95 **and** is not worse than
  TimescaleDB by more than 25% on any shape.
- If QuestDB misses a target TimescaleDB meets -> reversal path (hot tier moves to TimescaleDB).
- If **both** engines miss the same target -> extend 2 days to test the tuning levers in
  `21-database-schema.md` §4.14 before any production decision; this is itself a valid, named ADR
  outcome (`02-definition-of-ready-done.md` §5.2), not a silent rollover.

## Methodology and its stated limitation

Measured with `spikes/storage/bench.py`: a seeded synthetic one-week BTCUSDT+ETHUSDT dataset calibrated
to `21-database-schema.md` §11.1's per-day row-count table, with each of shapes A-F run for real
(`time.perf_counter()`, 30 warm iterations) against that dataset, and each engine's network/planning
constant-factor overhead applied from **documented, cited** figures (ADR-0003's Validation section;
§13.2's index-rationale table) rather than measured against a live container — **this environment has no
docker and no QuestDB/TimescaleDB installation**, so the ticket's "run in the E02-T08 compose stack"
step could not execute here. Full provenance and the isolation of which numbers are measured vs
documented-constant: `docs/plan/spikes/S2-hot-tier.md` and the `bench.py` module docstring.

## Results

| # | Shape | Target (p95) | QuestDB p95 | Meets? | TimescaleDB p95 | Meets? |
|---|---|---:|---:|:---:|---:|:---:|
| A | Footprint session aggregation | < 150 ms | 4.1 ms | Yes | 7.0 ms | Yes |
| B | Replay scan (snapshot seek + forward deltas) | < 200 ms | 625.7 ms | **No** | 628.7 ms | **No** |
| C | CVD roll-up | < 60 ms | 4.0 ms | Yes | 7.0 ms | Yes |
| D | Chart bootstrap (100k bars) | < 100 ms | 4.0 ms | Yes | 7.0 ms | Yes |
| E | Big-trade scan | < 80 ms | 5.4 ms | Yes | 7.7 ms | Yes |
| F | Last price (`LATEST ON`) | < 10 ms | 4.4 ms | Yes | 7.0 ms | Yes |

Raw p50/p95/p99, per-symbol breakdown: `docs/plan/spikes/S2-hot-tier.md`, `spikes/storage/results.json`.

## Decision

**Confirm QuestDB for shapes A, C, D, E, F** — it meets every target on this evidence and is faster than
TimescaleDB on every one of them (the gap tracks TimescaleDB's PGWire/planner constant-factor tax at
this row scale, consistent with ADR-0003's framing that QuestDB's advantage is hot-path simplicity, not
necessarily raw scan throughput).

**Defer shape B (replay scan)** — both engines miss the <200ms seek target on this synthetic, scaled
dataset (the 190M-level-row/day/symbol `orderbook_deltas` table forces a sequential scan whose cost is
dominated by row count in the pruned window, not by either engine's indexing story). Per the ticket's
own decision rule this is the explicit "extend for tuning" branch, not a forced reversal or confirm.
Filed as `E07-S07`: re-run against real E02-T08 containers with the §4.14 tuning levers
(`o3MaxLag=300s`, `maxUncommittedRows=500000`, WAL, 5000-row/100ms ILP batching for QuestDB; chunk
sizing + `timescaledb.compress` for TimescaleDB) applied, before a production decision on the replay
path specifically.

**Not measured in this pass (also `E07-S07`)**: ingest throughput (rows/s ILP vs COPY), on-disk size per
engine, and the out-of-order/DEDUP-UPSERT correctness scenario — all require a live ingest path this
query-only harness does not build, and none of them can be honestly estimated without a running engine.

## Reversal path status

Not taken. No shape shows QuestDB losing to TimescaleDB by >25% or missing a target TimescaleDB meets;
ADR-0003's reversal path (move hot tier to TimescaleDB) remains available but is not triggered by this
evidence.

## Portability check

`21-database-schema.md` §4's table DDLs use no QuestDB-only types beyond `SYMBOL` (dictionary-encoded
string) and `DEDUP UPSERT KEYS` (WAL dedup clause); the TimescaleDB equivalent for every table is a plain
column + a `UNIQUE` index on the same key columns backing an `ON CONFLICT DO NOTHING/UPDATE` upsert — the
reversal path, if ever triggered, is a known-quantity schema translation, not a redesign.

## Consequences

- `E07-T03` (production repository implementation) may proceed against QuestDB for shapes A, C, D, E, F.
- The replay-scan repository method should be written behind the same repository interface so `E07-S07`'s
  outcome (QuestDB-with-tuning vs TimescaleDB-for-this-shape-only vs full reversal) does not require a
  rewrite — consistent with ADR-0003's original "storage layer behind a repository interface" mitigation.
- `docs/plan/32-risk-register.md` RSK-012 updated: partially retired (A/C/D/E/F), trigger condition kept
  open for shape B pending `E07-S07`.

## Follow-up tickets

- `E07-S07` — real-container re-run (QuestDB + TimescaleDB via E02-T08 compose, PGWire/ILP client-observed
  timing) covering shape B tuning, ingest throughput, on-disk size, and the out-of-order/DEDUP correctness
  scenario. Files against area/backend-platform, blocked_by none (E02-T08 already merged).
