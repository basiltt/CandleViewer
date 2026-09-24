# ADR-0003 — Three-tier storage (QuestDB hot, Parquet/DuckDB cold, Postgres relational)

- Status: **decided**
- Date: 2026-09-14
- Deciders: Owner (delegated), Architect, Backend lead, DevSecOps
- Consulted: `docs/research/11-backend-tech.md` §6, `docs/research/22-architecture-options.md` §3, `docs/research/24-owner-decisions.md` decision #2
- Related: `docs/plan/21-database-schema.md`, ADR-0015

## Context and problem statement

CandleViewer must store three very different kinds of data: (a) a firehose of ticks and L2 deltas plus derived bars/footprint/heatmap for recorded symbols (~7 GB/day raw, ~1–1.5 GB/day compressed for two symbols at 200 depth — an unverified first-principles estimate); (b) long-lived archives for replay and analytics; (c) strongly relational, transactional state — users, roles, accounts, encrypted keys, per-account profiles, rules, OMS orders/executions/positions, journal and a tamper-evident audit log. No single engine is good at all three at this scale without compromise.

## Decision drivers

- Order-flow query shapes map directly onto time-series primitives (`SAMPLE BY`, `ASOF JOIN`, `LATEST ON`).
- OMS and audit need real ACID transactions, foreign keys and constraints.
- Replay must scan long contiguous ranges cheaply.
- Single-box operations: every added daemon is an operational cost.
- Vendor benchmark claims are disputed (a ClickHouse maintainer's rebuttal showed indexed ClickHouse beating QuestDB on disk by ~3×), so the choice must be reversible.

## Considered options

1. **Three tiers: QuestDB (hot) + Parquet/DuckDB (cold) + Postgres (relational)**.
2. **TimescaleDB for everything** — one Postgres instance, hypertables for time series.
3. **ClickHouse (hot+cold) + Postgres (relational)**.
4. **Postgres only** — simplest possible.

## Decision outcome

**Chosen: option 1**, matching the owner's delegated decision.

| Tier | Engine | Contents | Retention |
|---|---|---|---|
| Hot | QuestDB 8.x (ILP ingest, PGWire query) | trades, book deltas, book snapshots, tickers, liquidations, bars, footprint cells, heatmap columns | `CV_RECORDER_HOT_DAYS` (default 7) |
| Cold | Parquet (date/symbol partitioned) + embedded DuckDB | archive, long replay, journal analytics | `CV_RECORDER_RETENTION_DAYS` (default 30), pinned = forever |
| Relational | Postgres 16 | users, roles, sessions, accounts, encrypted keys, profiles, rules + versions, trade groups, orders, executions, positions cache, journal, audit (hash-chained), coverage gaps, feature flags | indefinite |

Binding structural rule: **all storage access goes through repository interfaces** in `services/api/candleviewer/storage/`. No module issues SQL or ILP directly. This is what makes the hot tier swappable.

### Consequences

Positive:
- Each engine does what it is good at; ingest throughput and relational integrity do not compete for the same WAL.
- QuestDB's time-series SQL maps onto footprint/profile/CVD queries with far less application code than a generic store.
- Parquet is an open, portable archive format — an exit hatch even if every database choice changes.
- Postgres gives the OMS and the audit log the transactional guarantees they require; the audit log's hash chain plus `REVOKE UPDATE, DELETE` is enforceable there.

Negative / risks:
- Three engines to operate, back up and monitor. Mitigated by compose-managed services, a backup sidecar, and dashboards per tier.
- Cross-tier joins (e.g. "show the book at the moment of this fill") need application-level correlation rather than a single SQL statement. Accepted: the replay engine already reconstructs state from the hot/cold tiers.
- QuestDB's claimed advantages are disputed for our workload. Mitigated by spike S2 and the repository abstraction.

### Reversal path

If spike S2 shows QuestDB failing our real footprint/replay query shapes, the hot tier moves to **TimescaleDB**, which collapses hot+relational into one Postgres deployment. Because all access is behind repositories and all schema lives in `21-database-schema.md`, this is a bounded change (new repository implementation + migration + re-ingest from Parquet), not a redesign. This ADR is then amended, not superseded.

### Why not the alternatives

- **TimescaleDB for everything**: genuinely attractive operationally, and it remains the designated fallback. Rejected as the default because the tick/L2 firehose and the OMS transaction path would share one WAL and one instance, and the owner's delegated preference was feature richness for the order-flow query shapes.
- **ClickHouse**: the best compression/throughput ceiling, but cluster-oriented and over-engineered to operate for a single-user, single-box deployment.
- **Postgres only**: simplest, but the L2 delta rate at 200 depth would dominate the same instance the OMS depends on — an unacceptable coupling between market-data load and order-entry reliability.

## Validation

- Spike S2: run the real footprint, profile, CVD and replay-scan queries against both QuestDB and TimescaleDB on a week of recorded BTCUSDT/ETHUSDT data; record p95 per query shape.
- Spike S6: instrument the recorder for 7 days to replace the GB/day estimate before finalising retention and disk sizing.
- Monthly restore drill (Postgres PITR + Parquet tree) as a PRR checklist item.
