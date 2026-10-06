# ADR-0033 — Renko brick sizing and series rebuild semantics

- Status: **proposed** (owner ratification pending, decision item on #1778).
- Date: 2026-10-07
- Deciders: Owner (`@basiltt`) — owner approval pending.
- Numbering note: the ticket (E12-K01, #525) says "ADR-0014"; 0014 is taken (Observability) and 0031 is an
  unexplained gap, so this is the next free number after 0032.
- Related: E12-K01 (#525, this spike), E12-T01 (#344, `BarSpec`), E12-S04 (Renko builder), E12-S12
  (rebuild API), E12-T05 (param parsing), E12-T07 (rebuild CI budget), `24-internal-schemas.md` §3.1/§3.3/§3.4,
  `22-api-openapi.yaml` `/market/bars`, `23-ws-protocol.md` §6.1, `30-release-roadmap.md` §12.
- Evidence: `services/api/bench/renko_rebuild/` (harness), `docs/research/e12/renko-rebuild-results.json` (raw run).

## Context

Two questions blocked E12-S04 / E12-S12: what `renko` + `atr:14` means given that `BarSpec` has only
`range_ticks`, and whether "rebuild of 1M prints <= 10 s, cancellable" is reachable and how cancellation works.

## Decision 1 — ATR bricks: defer `atr:*` to R2; R1 accepts integer ticks only

The contract disagreement is real: `22-api` (param table) and `23-ws` §6.1 promise `atr:14`, while
`24-internal-schemas` §3.1 has no ATR field and says nothing about the source series or cadence.

**R1 rule:** `renko.param` is a base-10 integer tick count (`^[1-9][0-9]{0,8}$`). Anything else, including
`atr:14`, is rejected with HTTP 422 `validation_failed` (WS: the matching subscribe error), `detail` =
`"ATR bricks are not available yet. Enter a brick size in ticks."` (the UI renders this as text, no silent
fallback). `BarSpec` is unchanged in R1; `atr` stays a reserved word in the param grammar.

**Doc changes proposed** (separate contract-first PR, not in this spike — governed files, C-6.1):

1. `22-api-openapi.yaml` `/market/bars`: renko row becomes "brick size in ticks (`atr:N` reserved, R2)";
   drop `atr:14` from the `param` examples; add the 422 example above.
2. `23-ws-protocol.md` §6.1: same wording for `renko`.
3. `24-internal-schemas.md` §3.3: add the R2 reservation below as a paragraph.

**Why defer rather than ship:** ATR over the renko series is circular, so a coherent form needs a second
series, a warmup rule and a freeze rule — three new contract surfaces on a rung-2 (cuttable) feature. Deferral
costs nothing the roadmap promised for R1 (fixed-size Renko is intact).

**R2 reservation (the only coherent design; prototyped and verified):**

| Aspect               | Rule                                                                                                                                                                                                                                                                                                                                       |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| (a) Source series    | ATR is Wilder ATR(`period`) over a **fixed 1m time series** of the same symbol/`price_source`, built from the same `TradeEvent`s. Never the renko series.                                                                                                                                                                                  |
| (b) Cadence          | **Frozen at series construction**: brick size = `max(1, ATR_last_closed_1m_bar_before_series_start * mult)` in integer ticks, resolved once. No per-brick or per-minute recompute. A new size means a new series (new `spec_hash`).                                                                                                        |
| (c) BI-4 / BI-5      | Hold, because the resolved size is a plain integer in the spec and a pure function of the (recorded) lookback trades; the builder never sees ATR. A drifting live ATR fails BI-5 whenever history is not replayed (verified, below).                                                                                                       |
| (d) `BarSpec` fields | Add `renko_atr_period: int \| None` (2..100), `renko_atr_mult_x100: int` (default 100), `renko_atr_source_interval_ms: int` (default 60000) **and** the resolved `range_ticks`. All are in `spec_hash`; the request supplies the first three, the server fills `range_ticks`. Exactly-one validator: `renko_atr_*` only with `kind=renko`. |
| Warmup               | Fewer than `period + 1` closed 1m bars before the start -> 422 (never a default size).                                                                                                                                                                                                                                                     |

Security note (E12-T05): the R1 integer pattern and the R2 `atr:<2..100>(:<mult>)?` pattern are whitelisted
regexes with bounded length (`maxLength: 24` already), not a parser.

Evidence (seeded, 400k trades, `atr_experiment`): frozen brick 176 ticks, 301 bricks, BI-4/BI-5 hold over 10
random cuts; live-drifting ATR resumed from a restart without history reproduces **a different series**
(BI-5 false).

## Decision 2 — Rebuild: chunked pull in a worker thread with a cancellation token, atomic publish

Cancellation contract for E12-S12 (`rebuild(spec, range, token) -> RebuildResult`):

1. Rows are read in chunks (<= 8 192 rows) in a worker thread (`asyncio.to_thread`); the token (a
   `threading.Event`) is checked between chunks **and** every <= 4 096 rows of building.
2. Output goes to a staging buffer and is published to `bars_*` in one commit at the end; cancel discards
   staging, closes the cursor, writes nothing (acceptance: "no partial rows").
3. `asyncio.Task.cancel()` alone is **not** the mechanism: it only abandons the `await`.

Metrics (E12-S12 ships them from day one): `bar_rebuild_duration_seconds{kind}`,
`bar_rebuild_cancelled_total{kind}`, `bar_rebuild_rows_total{kind}`, `bar_rebuild_cancel_latency_seconds`.

## Measurements

Hardware: Intel64 Family 6 Model 142 (8 logical CPUs), 15.9 GiB, Windows 11, CPython 3.12.3, single process,
no other deliberate load. **Not the 4 vCPU / 8 GB reference VPS**; absolute numbers are indicative.

**Data source (important):** no QuestDB is reachable here (no docker, nothing on :8812), so the read path was
**not** measured against QuestDB. Input is a **synthetic-from-corpus** 1M-trade day (seed 12001): the empirical
qty/side/price-step distributions of the recorded BTCUSDT frames (`packages/fixtures/bybit/2026-10-05`) are
bootstrapped into a random walk, stored as zstd Parquet (8.0 MB) and read via pyarrow in 65 536-row batches
(the cold-path stand-in). Builders are the throwaway prototypes in `bench/renko_rebuild/builders.py`, using
plain ints; they are not the E12-S0x builders (those do not exist yet), so production builders emitting
`Decimal` pydantic bars will be slower — see the follow-up.

Rebuild of 1M trades (median of 5, each in a fresh subprocess; wall includes Parquet read):

| Builder             | Bars out | Wall (s) | Rows/s | Peak RSS (MB) | Read (s) | vs 10 s |
| ------------------- | -------- | -------- | ------ | ------------- | -------- | ------- |
| time (1 m)          | 1 440    | 0.91     | 1.10 M | 83            | 0.036    | pass    |
| tick (1 000)        | 1 000    | 0.82     | 1.21 M | 84            | 0.036    | pass    |
| volume (5 000 lots) | 51 024   | 1.02     | 0.98 M | 106           | 0.036    | pass    |
| range (20 ticks)    | 17 108   | 0.89     | 1.12 M | 91            | 0.038    | pass    |
| delta (2 000 lots)  | 19 188   | 0.92     | 1.09 M | 92            | 0.037    | pass    |
| renko (10 ticks)    | 40 467   | 1.05     | 0.95 M | 98            | 0.037    | pass    |

All six pass with ~10x headroom; **dominant cost is per-trade Python overhead (~96 %)**, not the read (3.5 %)
or the emit. All six in one pass (`BarBuilderSet`) is roughly 5.5 s of summed build time, still < 10 s. Caveat: a proxy for
the PGWire path (materialising 1M Python row dicts + `pa.Table.from_pylist`) cost 0.80 s + 0.68 s on this
machine, i.e. roughly doubling the read side, so the QuestDB path is expected to remain inside 10 s but **this
is unmeasured** and must be re-run when QuestDB is available (follow-up).

Cancellation (renko rebuild, cancel fired at 15-60 % of a ~1.0 s run, 20 trials per row; latency from the
intended cancel instant to "stopped and released"):

| Strategy                                                         | Chunk rows | p50 (ms) | max (ms) | Rows leaked after cancel | 250 ms   |
| ---------------------------------------------------------------- | ---------- | -------- | -------- | ------------------------ | -------- |
| A. `task.cancel()`, builder on the event loop, `await` per chunk | 8 192      | 7.6      | 28.2     | 0                        | pass     |
| A. same                                                          | 65 536     | 150.3    | 188.6    | 0                        | marginal |
| A. same                                                          | 262 144    | 729.0    | 794.1    | 0                        | **fail** |
| A2. `task.cancel()` over `to_thread`                             | 65 536     | 670.3    | 1 062.8  | 809 340 (zombie commits) | **fail** |
| **B. token, chunked pull in thread**                             | 8 192      | 2.2      | 4.5      | 0                        | pass     |
| **B. same**                                                      | 65 536     | 5.8      | 8.8      | 0                        | pass     |
| **B. same**                                                      | 262 144    | 5.5      | 12.8     | 0                        | pass     |

A works only for tiny chunks and stalls the loop for the whole chunk (150 ms at 65 536 rows violates C-2.18's
no-blocking rule). A2 is the trap: the caller sees "cancelled" but the thread keeps running and later commits.
B is chunk-size-insensitive because the token is also polled inside the batch. The PGWire cursor-close
behaviour (does `asyncpg` abort a server-side query promptly?) is **not measured**; B does not depend on it
since it bounds the work per page and closes between pages.

Invariants on the prototypes (50k trades, 20 random cut points each): BI-1, BI-4, BI-5 true for all six.

## Consequences

- E12-S04 builds fixed-size Renko only; param parsing is the integer whitelist; `atr:*` is a 422.
- E12-S12's rebuild API takes a token and publishes atomically; no reliance on task cancellation.
- Descoping note for `30-release-roadmap.md` §12 rung 2 (Renko and range bars -> R2): at risk is **only** the
  builder + UI of two cheap builders (both ~0.9-1.0 s / 1M rows, no new storage); `bars_range`/`bars_renko`
  tables already exist. ATR bricks are already out of R1 by this ADR, so pulling the rung removes no ATR work.
  Cutting rung 2 saves roughly the E12-S03/S04 effort and nothing in the rebuild/cancel path (shared).
- New risk to log in `32-risk-register.md` (not edited here; governed): "rebuild budget unmeasured on QuestDB
  PGWire and on production (Decimal/pydantic) builders".

## Rejected

- ATR over the renko series (circular). Live/per-brick ATR (fails BI-5 without full-history replay). Ship
  `atr:14` in R1 (three new contract surfaces on a cuttable feature). `Task.cancel()` as the sole mechanism.

## Revisit when

QuestDB integration profile is available (re-run `--rows 1000000` through `QuestDbHotTierSource`), or E12-S0x
production builders land and exceed 5 s per builder.
