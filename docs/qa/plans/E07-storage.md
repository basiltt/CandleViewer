# E07 Storage — Black-Box QA Test Plan

Ticket: E07-Q01 (issue #224). Owner: QA/SDET, reviewed by backend lead + second QA before
Definition of Done is met (`docs/plan/02-definition-of-ready-done.md` §3/§4).

Scope: the storage module (`M10`, `services/api/candleviewer/storage/`) across its three tiers —
Postgres (relational, E07-T02), QuestDB (hot, E07-T03), Parquet/DuckDB (cold, E07-T04) — plus the
`source_tier=auto` router (E07-T05). This plan is **black-box**: every case is phrased against the
`MarketDataRepository` / `ColdTierRepository` / `RelationalRepository` Protocols' observable
behaviour (`docs/plan/27-adrs/ADR-0003-storage-tiers.md`), never against an implementation's
internals. Perf/load (E07-Q03), chaos/failure injection (E07-Q04) and security controls (E07-X02)
are explicitly out of scope here.

## 1. Test approach

The same **contract-test suite** (`services/api/tests/contract/storage/`) is parametrised over
implementations — one `pytest.fixture(params=[...])` yields `fake` today and will add
`questdb`/`postgres`/`cold` as their real engines are wired up by E07-T02/T03/T04. This is the
mechanism the acceptance criteria calls out: the suite must pass **unchanged** against every
implementation, which is what proves the repository abstraction ADR-0003 depends on. Real-engine
runs use `testcontainers` and are marked `@pytest.mark.integration`
(`services/api/tests/integration/storage/`), gated by the `integration` CI job
(`.github/workflows/_job-integration.yml`); fake-only runs are marked plain and run in the fast
per-PR `contract`/`unit` jobs.

Heavy cases (100k-row replay, full symbol-day) are `@pytest.mark.slow` and deselected from the
per-PR gate, run nightly (`docs/plan/03-testing-strategy.md` §11, "Performance notes" of this
ticket).

## 2. Traceability matrix — E07 acceptance criteria → plan case

| Source ticket | AC (paraphrased) | Plan case(s) |
|---|---|---|
| E07-T02 | Postgres migration up/down/up round-trips cleanly | §4 PG-01 |
| E07-T02 | Role/privilege matrix enforced (no app role can `DROP`/superuser) | §4 PG-02 |
| E07-T02 | `UnitOfWork` commit/rollback boundaries are transactional | §4 PG-03, PG-04 |
| E07-T02 | Seed data re-run is idempotent | §4 PG-05 (real engine: `test_seed_idempotency.py`) |
| E07-T03 | DDL runner applies all tables with WAL + `DEDUP UPSERT KEYS`, idempotent re-run | §4 QDB-01 |
| E07-T03 | ILP writer + PGWire reader round-trip trades/bars/etc. without float or timestamp drift | §4 QDB-02, CS-01..CS-06 |
| E07-T03 | Replaying the same batch twice/thrice leaves row counts unchanged (dedup) | §4 QDB-03, CS-07 |
| E07-T03 | Schema drift on a live table is detected and raises | §4 QDB-04 |
| E07-T04 | Export → verify → query round-trips exactly (the §5 lifecycle scenario) | §4 CT-01 (fake now; real engine added when E07-T04 lands) |
| E07-T04 | Checksum mismatch on a poisoned export raises, never silently returns `False` | §4 CT-02 |
| E07-T04 | Manifest listing is scoped and ordered ascending by partition start | §4 CT-03 |
| E07-T05 | `source_tier=auto` straddling range yields the union of hot+cold with no dup/gap at the seam | §4 RT-01 (added when E07-T05 lands; router does not exist yet) |
| E07-T05 | Retention `apply()` refuses a pinned range | §4 CT-04 (already covered against the fake; real engine case added with E07-T05) |

Cases in this plan **not** sourced from any single ticket (negative/edge coverage this plan adds
on top, per the acceptance criteria's explicit "additionally contains cases no ticket listed"):
CS-08 (empty range), CS-09 (range entirely in the future), CS-10 (unknown symbol), CS-11
(single-row partition), CS-12 (month-boundary partition), CS-13/14/15 (hot/cold boundary ±1 µs).

## 3. Observable-behaviour case groups

1. **Write-read fidelity** — what goes in comes out unchanged: value equality (`Decimal`-precision
   strings compared as strings/exact, never as floats — a `DOUBLE` round-trip must be lossless),
   `ts_us` compared as integers (never `datetime`, which would hide a µs truncation), symbol
   scoping, and ascending-order guarantees per `MarketDataRepository`'s ordering contract.
2. **Idempotency / dedup** — every stream with a documented natural key
   (`(symbol, trade_id)` trades, `(symbol, seq)` deltas/snapshots, `(symbol, ts_us)` tickers,
   `(symbol, family, param, ts_us)` bars) is stable under replay: 1x, 2x, 3x writes of an
   identical batch produce identical row counts and identical last-write-wins content on a
   changed duplicate.
3. **Tier routing** — hot-only, cold-only, and straddling ranges over the hot/cold seam; the
   merged read has zero duplicate natural keys and zero gaps versus the union of both tiers.
4. **Lifecycle** — write → export → verify → drop → cold-tier read returns the same rows (row
   count and a checksum over sorted rows equal to pre-export hot-tier values).
5. **Safety invariants** — retention pins block `apply()`; verification failure raises rather
   than returning `False`; schema drift raises rather than silently reading a wrong shape.
6. **Failure surfaces** — a tier being unavailable, a poisoned export, a drifted schema, all
   surface a stable `StorageError.code` (`services/api/tests/unit/storage/test_errors.py` already
   asserts the code table is frozen; this plan's cases assert the *repository* method raises the
   right subclass, not just that the code exists).
7. **Observability** — the metrics this epic promises are actually emitted with the promised
   label sets: `questdb_write_seconds`, `storage_export_rows_total{stream,result}`,
   `storage_retention_skipped_total{reason}`. A metric named in a ticket's DoD but never emitted
   is a defect this suite catches (added as each metric's emitting code lands).

## 4. Case list

### Contract suite (`tests/contract/storage/test_market_data_contract.py`, param: `fake` now,
`questdb`/`postgres`/`cold` added by their owning tickets)

- CS-01 write-then-read trades round-trips exactly (existing)
- CS-02 read orders ascending by `ts_us` regardless of write order (existing)
- CS-03 read filters by range, inclusive-start/exclusive-end (existing)
- CS-04 write dedups on `(symbol, trade_id)`, last-write-wins (existing)
- CS-05 read scoped by symbol (existing)
- CS-06 write-then-read bars round-trips exactly (existing)
- CS-07 replaying an identical trade batch twice/thrice leaves row count unchanged (new)
- CS-08 empty range (`start_us == end_us`) returns `[]`, never raises (new)
- CS-09 a range entirely in the future (no data yet written that far forward) returns `[]` (new)
- CS-10 a symbol with no data at all returns `[]` for every `read_*` method (new)
- CS-11 a single-row partition round-trips (degenerate case, not just N≥2 rows) (new)
- CS-12 a range spanning a calendar-month boundary preserves ordering and count (new)
- CS-13/14/15 `ts_us` exactly at a caller-supplied boundary (`boundary-1`, `boundary`,
  `boundary+1`) resolves inclusive-start/exclusive-end correctly at the edges (new)
- CS-16 book-delta dedup on `(symbol, seq)`, ordered `(ts_us, seq)` (new)
- CS-17 `latest_ticker` returns `None` before any write, then the highest-`ts_us` row after
  several out-of-order writes (new)

### Cold-tier contract cases (`tests/contract/storage/test_cold_tier_contract.py`, new file,
param: `fake` now)

- CT-01 export → verify → query lifecycle: `verified` is `False` until `verify_checksums`
  succeeds, then `True`; `query` returns exactly the seeded rows in range
- CT-02 `verify_checksums` on a poisoned run raises `StorageExportVerifyFailed`, never returns
  `False`
- CT-03 `list_manifest` is scoped to `(symbol, stream)` and ordered ascending by
  `partition_range.start_us`
- CT-04 retention `apply()` raises `StorageRetentionBlockedByPin` for a pinned
  `(symbol, stream)` and leaves already-applied decisions untouched; a `skip` decision on a
  pinned stream is allowed through

### Real-engine integration (`tests/integration/storage/`, `@pytest.mark.integration`, needs
Docker; not run in this sandbox — "not run locally: no docker", exercised by CI's `integration`
job)

- QDB-01 DDL runner applies all tables idempotently (existing:
  `test_ddl_runner_applies_all_tables_idempotently`)
- QDB-02 ILP write → PGWire read round-trips a batch with no float/timestamp drift (implicit in
  `test_write_trades_dedup_replay_is_idempotent`; this plan calls out the fidelity assertion
  explicitly as its own case for traceability)
- QDB-03 replaying an identical batch twice converges to a stable row count via WAL dedup
  (existing: `test_write_trades_dedup_replay_is_idempotent`)
- QDB-04 schema drift on a live table raises `StorageSchemaDrift` (existing:
  `test_schema_drift_detected_when_live_columns_differ`)
- PG-01 Alembic upgrade → downgrade → upgrade round-trips on empty and seeded DB (owned by the
  `migrations` CI job per `60-database-migrations.md` C-5.5; cross-referenced here, not
  duplicated)
- PG-02 role/privilege matrix: no application role can `DROP`/`ALTER` or is superuser (added when
  E07-T02's role grants ship a fixture-driven test; tracked, not yet present)
- PG-03/04 `UnitOfWork` transaction boundaries and savepoints against a real Postgres (added when
  a concrete `RelationalRepository` implementation lands; the fake's state-machine equivalent is
  already unit-tested in `tests/unit/storage/test_fake_cold_and_retention.py`)
- PG-05 seed idempotency (existing: `test_seed_idempotency.py`)

### Full-lifecycle scenario (the exact §5 scenario named in this ticket's Context)

- LC-01 "Recorder: auto-record trigger → QuestDB write → retention/pin logic → Parquet roll-off
  to cold tier → DuckDB query of rolled-off data": one symbol-day fixture replayed through this
  full chain; the DuckDB row count and a checksum over sorted rows must equal the pre-export
  QuestDB values exactly. **Status: scaffolded against the fakes now** (`CT-01` exercises the
  export/verify/query shape); the real end-to-end run needs E07-T04's Parquet exporter and
  E07-T05's retention job, both still open (issues #170, #225) — this case is re-run against real
  engines in the same PR that lands each, per this ticket's own "Dependencies" section ("E07-T04/
  E07-T05 cases are added as those land"). This is not a blocker for E07-Q01: the plan, the
  traceability matrix and the fake-backed contract suite are complete and reviewable now.

### Tier routing (added when E07-T05's router lands, issue #225 — Protocol not yet implemented)

- RT-01 hot-only range: router serves entirely from QuestDB
- RT-02 cold-only range: router serves entirely from the Parquet/DuckDB view
- RT-03 straddling range (the overlap fixture): merged result has zero duplicate natural keys
  and zero missing rows versus the union of both tiers' independent reads

## 5. Mutation exercise

Three seeded defects are used to prove the contract suite would actually catch a real regression,
not just exercise the happy path (`services/api/tests/unit/storage/test_contract_suite_catches_mutations.py`):

1. **Dedup-key mutation**: a mutant `write_trades` that keys on `(symbol, ts_us)` instead of
   `(symbol, trade_id)` — caught by CS-04 (two trades at the same `ts_us` with different
   `trade_id`s silently collapse to one).
2. **Ordering mutation**: a mutant `read_trades` that returns insertion order instead of sorting
   by `ts_us` — caught by CS-02.
3. **Range-boundary mutation**: a mutant `_in_range` that uses `<=` on `end_us` (inclusive-end
   instead of the documented exclusive-end) — caught by CS-13/14/15 (boundary ±1 µs cases).

Each mutant is a small local subclass/monkeypatch inside the test module (never a change to the
shipped `FakeMarketDataRepository`); the test asserts the *unmutated* suite's assertions pass and
the *mutated* one fails, proving detection rather than assuming it.

## 6. Golden fixtures

Per-query-shape golden result sets live under `packages/fixtures/golden/storage/`, one file per
shape (`trades_range.golden.json`, `bars_range.golden.json`, …), each starting from a small,
hand-verifiable canonical case (five trades forming a known aggregate) per
`03-testing-strategy.md` §4.2. Regeneration is only via `--update-golden` plus a written PR
rationale; there is no regeneration tooling change needed in this ticket — the existing
`packages/fixtures` golden-file convention (§4.2) already governs it.

## 7. CI wiring

- Fake-backed contract suite: runs today in the `contract` job
  (`.github/workflows/_job-contract.yml`, `pytest tests/contract -m "not integration"`).
- Real-engine integration suite: runs in the `integration` job
  (`.github/workflows/_job-integration.yml`, `pytest tests/integration -m integration`, Docker via
  `testcontainers`); no network egress beyond the locally-started containers (network guard
  `tests/_ci_network_guard.py`, autouse).
- Flaky policy: a case failing intermittently twice in a week is quarantined the same day with
  `@pytest.mark.flaky` + a linked P1 ticket, per C-9.3 / `40-testing.md`.
- Nothing in this suite needs new CI wiring beyond what E07-T02/T03 already added; this ticket
  adds test *files*, not new jobs.

## 8. Definition of Done tracking

- [x] Plan committed at `docs/qa/plans/E07-storage.md`.
- [ ] Reviewed by backend lead + second QA (owner review step, outside agent scope).
- [x] Traceability matrix complete for every landed E07-T02/T03 AC; E07-T04/T05 cases scaffolded
      and marked pending their own tickets, per this ticket's Dependencies.
- [x] Contract suite green against the fake (this PR); real-engine runs unchanged (existing,
      not modified) — proving the ADR-0003 abstraction as each real engine lands.
- [x] Mutation exercise executed; three seeded defects caught.
- [x] Golden fixtures committed with rationale.
- [ ] QA sign-off recorded on E07-T02/T03/T04 issues — owner/QA action after this PR merges.
