# ADR-0015 — Recording and retention policy

- Status: **decided**
- Date: 2026-09-14
- Deciders: Owner (decision #4), Architect, Backend lead, DevSecOps
- Consulted: `docs/research/24-owner-decisions.md` decision #4 and cross-cutting consequence #4, `docs/research/08-crypto-data-metrics.md` §1, `docs/research/23-views-and-screens.md` (recorder dependency note), `docs/research/11-backend-tech.md` §6.1
- Related: ADR-0003, `docs/plan/21-database-schema.md`, `docs/plan/20-architecture.md` §3.8

## Context and problem statement

Bybit's REST API offers no deep history for the tape or the order book — recent trades are capped at 1,000 and there is no historical L2 or liquidation endpoint at all. Every order-flow surface that needs history (volume/delta profile composites, long-lookback CVD, the heatmap trail, replay, journal post-mortems) is only as deep as **our own recorder has run**. Recording everything is simple and wrong: at roughly 7 GB/day raw (~1–1.5 GB/day compressed) for two symbols at 200 depth, an unbounded recorder fills a personal machine quickly and silently.

## Decision drivers

- Owner decision: a user-managed recorded-symbols list, **empty by default**, plus automatic recording of any symbol with an open chart or an open position.
- Disk growth must be predictable and visible, not discovered when the disk fills.
- History gaps must be honest: the UI must show where data does not exist rather than interpolating.
- Live views must work for any symbol regardless of recording state.
- Storage estimates are unverified first-principles numbers and must be replaced by measurement.

## Considered options

1. **Opt-in list + auto-record triggers + tiered retention with pinning and a disk budget.**
2. **Record everything subscribed, forever.**
3. **Record nothing; rely on REST backfill.**
4. **Record only derived aggregates** (bars, footprint) and discard raw ticks and book deltas.

## Decision outcome

**Chosen: option 1.**

1. **Effective recorded set** = explicit user list ∪ symbols with an open chart ∪ symbols with an open position. Auto-recorded symbols are marked as such and are the first candidates for retention pressure; explicit-list symbols are protected from automatic eviction.
2. **Streams recorded per symbol**: raw `publicTrade`, raw book deltas and snapshots, `tickers`, `allLiquidation`, plus derived bars, footprint cells and heatmap columns. **Raw ticks and book deltas are the source of truth** — derived series are recomputable, and keeping the raw stream is what allows a new bar type or a new metric to be backfilled over existing history.
3. **Tiering**: hot in QuestDB for `CV_RECORDER_HOT_DAYS` (default 7), then a nightly verified export to Parquet and a drop from the hot tier. Cold Parquet is retained for `CV_RECORDER_RETENTION_DAYS` (default **30**, per the research proposal), with per-symbol overrides.
4. **Pinning**: `pinned = true` on a symbol or an explicit date range means never delete. Pins are shown with their disk cost so the user sees the price of keeping them.
5. **Raw WS payloads** (the untouched exchange JSON, redacted) are kept for 7 days only, for forensic comparison when a normalizer bug is suspected.
6. **Disk budget** (`CV_DISK_CAP_GB`, default 500): the Admin UI shows measured GB/day per symbol and the projected 30-day footprint. At 80 % usage an alert fires; at **90 % auto-recording stops accepting new symbols** (explicit-list symbols keep recording); at 95 % recording halts entirely with a critical alert. Pinned data is never deleted automatically — the system stops recording rather than discarding what the user asked to keep.
7. **Coverage is first-class data.** A `coverage` table records, per symbol and stream, the intervals actually captured. Replay, profile composites and journal post-mortems query it and render gaps as explicitly hatched, labelled regions. **No interpolation, ever** — a gap that looks like data is worse than a gap that looks like a gap.
8. **Backpressure**: if QuestDB is unavailable, the recorder spills to a bounded on-disk WAL (1 GB) and replays it on recovery; beyond that it stops recording the lowest-priority (auto-recorded, unpinned) symbols first and alerts.
9. **Deletion is auditable**: every retention run logs what it deleted and why, and the log is retained after the data is gone.

### Consequences

Positive:
- Nothing is recorded until the user acts, which matches the owner's explicit instruction and keeps a fresh installation weightless.
- Disk growth is visible before it is a problem, and the degradation path stops recording rather than losing pinned history.
- Keeping raw ticks means future metrics can be backfilled over existing history — the single most valuable property of the whole policy.
- Explicit coverage tracking makes every history-dependent view honest, which the research flagged as a recurring UX risk across views 3, 6–10, 12 and 17.

Negative / risks:
- Users will inevitably want history for a symbol they only just started recording, and it will not exist. Mitigated by making this explicit in the UI from the first run: empty-state screens explain that history begins when recording begins, and the recorded-list screen is prominent in onboarding.
- Auto-recording on chart open can surprise a user who browses many symbols. Mitigated by a short grace period (a symbol must be open 60 s before auto-recording starts), a visible recording indicator, and a one-click stop.
- The GB/day estimate may be off by 2–3×. Mitigated by spike S6 (7-day instrumentation) replacing the estimate before retention defaults are finalised.

### Why not the alternatives

- **Record everything forever**: fills a personal machine in weeks and makes the recorder the system's dominant operational cost for data the user never asked for.
- **Record nothing**: impossible — Bybit provides no historical L2, no historical liquidations and only a shallow tape, so profiles, replay and the heatmap trail would simply not exist as features.
- **Derived aggregates only**: cheaper, but it permanently forecloses backfilling any new metric or bar type over past history, and it makes tick-level replay impossible. For a product whose thesis is order-flow detail, discarding the raw tape is the wrong trade.

## Validation

- Spike S6: instrument the recorder against BTCUSDT and ETHUSDT for 7 days; publish measured GB/day per stream and adjust `CV_DISK_CAP_GB`, hot-tier sizing and retention defaults accordingly.
- Retention tests: a symbol crossing the retention boundary is rolled off and dropped exactly once; a pinned symbol never is; a coverage row is written for every capture interval.
- Disk-pressure chaos test: fill the volume to 85 %, 91 % and 96 % and assert each documented behaviour, including that pinned data survives.
