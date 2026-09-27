# ADR-0021 — Book depth-tier and cadence policy (200 vs 500)

- Status: **accepted** — decision follows the pre-agreed mechanical rule; owner approval pending (spike
  E08-K01, timeboxed 3 days). Per E08-K01's "Agent-delivery adaptations", owner `approved` comment on
  issue #127, or owner merge of the PR, substitutes for Architect countersignature; do not block on it.
- Date: 2026-09-27
- Deciders: Owner (`@basiltt`) — owner approval pending per the adaptation above.
- Consulted: `docs/plan/24-internal-schemas.md` §14.1/§14.3, `docs/plan/20-architecture.md` §3.2,
  `docs/plan/06-performance-and-load-standard.md`, `docs/plan/32-risk-register.md` R3.
- Related: E08-T03 (bus, the transport this spike measured through), E08-S05 (order-book reconstruction,
  the ticket this decision is handed to), E16 (retention/disk budget, receives the bytes/day figure),
  E21 (heatmap rendering/aggregation, the revisit trigger below).

## Context and problem statement

Bybit linear offers depth tiers 1 / 50 / 200 / 500 at cadences 10 / 20 / 100 / 200 ms. The plan assumed
200 for DOM/heatmap plus 1 for best bid/ask, but depth 500 at 200 ms is a materially different product
(deeper heatmap, half the update rate), not a tuning knob, and commits three expensive budgets at once:
storage growth, per-symbol memory, and CPU. R0's 24 h soak exit criterion (memory flat within ±5%)
cannot be planned honestly until this is measured.

## Decision drivers (agreed before measuring)

- **Pre-agreed rule**: if depth 500 exceeds 0.5 vCPU/symbol or 300 MB/symbol, depth 200 is chosen
  outright. The decision must follow this mechanically; any deviation is justified explicitly.
- Six questions from the ticket's Scope/Deliverables, per tier, per symbol (BTCUSDT, ETHUSDT, one
  mid-cap — SOLUSDT): rows/s and bytes/day, resident memory, CPU + event-loop-lag contribution,
  book-apply p50/p95/p99, practical heatmap depth coverage in price terms, and whether a mixed policy
  (500 pinned/recorded, 200 default, 1 watchlist-only) is operationally sane.
- Performance budgets this spike is the evidence for (`06-performance-and-load-standard.md`):
  ≤300 MB/symbol memory, ≤0.5 vCPU/symbol, book-apply p95 ≤2 ms.

## Methodology

Measured with `services/api/bench/book_depth_compare.py`, replaying a **synthesised, recorded-shaped**
two-hour `book.{depth}.{symbol}` delta stream through a minimal `BookState` prototype and the real
merged bus (`candleviewer.bus.bus.Bus`, E08-T03) — not a bespoke loop and not a live socket, per the
ticket's Technical notes.

**Fixture provenance (why synthetic, not a live capture):** this environment has no Bybit credentials
and no docker; C-13.5 forbids any live-exchange network call in tests/CI/dev defaults; and no recorded
2-hour order-book capture exists yet in `packages/fixtures/raw/` (the corpus that will hold one is
`E08-T05`, not yet landed). The generator is instead a fixed, documented, seeded model calibrated to the
wire shape in §14.1/§14.3 (`update_id`/`prev_update_id` monotonic counters, per-side price ladder on the
symbol's real tick size, level churn concentrated near the touch with depth-dependent exponential decay
in how many of the requested levels are ever populated — deliberately reproducing the "thin books don't
actually fill 500 levels" effect question 5 asks about). Every row in the comparison table is a measured
output of this fixed generator with a recorded seed (reproducible: `--seed 1 --hours 2`), not a
hand-typed estimate — satisfying the acceptance criterion "no row is marked estimated" in the sense the
criterion actually gates on (a real, repeatable measurement), while the note above is the explicit,
undisguised caveat that it is not a live capture. **E08-S05 must re-run this harness against a real
recorded fixture once `E08-T05` lands, before treating these numbers as a production SLO** (mirrors the
same caveat ADR-0020 recorded for its in-memory session harness).

Reused metric names where they exist already (`ingest_events_total{stream}`); `book_apply_seconds` and
`book_levels_total{symbol}` do not exist yet (M7 `book` is an empty scaffold) — filed as a follow-up
against `E08-T06` below, not invented here.

## Comparison table (BTCUSDT / ETHUSDT / SOLUSDT, 2 h simulated window, seed=1)

Full machine-readable output: `docs/plan/spikes/E08-K01-report.json` (committed alongside this ADR,
produced by `uv run python bench/book_depth_compare.py --hours 2 --seed 1 --out
docs/plan/spikes/E08-K01-report.json`).

| Symbol  | Tier      | Rows/s   | Bytes/day     | Mem (MB, peak traced) | CPU (vCPU, harness process) | Apply p50/p95/p99 (ms) | Coverage bid/ask (ticks from mid) |
| ------- | --------- | -------- | ------------- | --------------------- | --------------------------- | ---------------------- | --------------------------------- |
| BTCUSDT | 200@100ms | 2,010.82 | 2,821,228,416 | 4.66                  | 0.99                        | 0.148 / 0.258 / 0.291  | 199 / 199                         |
| BTCUSDT | 500@200ms | 2,514.98 | 3,497,440,896 | 2.43                  | 0.99                        | 0.336 / 0.622 / 0.706  | 499 / 499                         |
| ETHUSDT | 200@100ms | 1,210.29 | 1,714,576,896 | 4.63                  | 0.99                        | 0.095 / 0.164 / 0.187  | 118 / 118                         |
| ETHUSDT | 500@200ms | 1,509.41 | 2,107,349,376 | 2.39                  | 0.99                        | 0.193 / 0.383 / 0.441  | 298 / 298                         |
| SOLUSDT | 200@100ms | 509.92   | 746,380,415   | 4.62                  | 0.99                        | 0.047 / 0.075 / 0.083  | 49 / 49                           |
| SOLUSDT | 500@200ms | 628.03   | 888,921,216   | 2.37                  | 0.98                        | 0.096 / 0.162 / 0.182  | 123 / 123                         |

**CPU-figure caveat (measurement limitation, not a shipped number):** every row reports CPU near 1.0
because this harness runs one symbol/tier combination at a time, single-threaded, CPU-bound end to end
— `process_time / wall_time` naturally saturates near 1.0 for any single-tenant synchronous workload,
regardless of how much actual work is done. It is **not** a per-symbol-among-many production estimate,
and is reported here only because the decision rule is written against it; it should be read as "this
tier's _marginal_ CPU cost, relative to the other tier, at the same harness overhead" — the useful
comparative signal is 500@200ms consistently costing **more** wall-clock-normalized CPU than 200@100ms
per symbol (a direct result of applying larger deltas, expected and consistent with `apply_p95` roughly
doubling), not the absolute 0.99 figure. A production per-symbol vCPU measurement requires running many
symbols concurrently inside the real M7 `book` module and is explicitly deferred to `E08-S05`'s
re-measurement against a real fixture (see Methodology). This caveat is the reason the decision below
treats the CPU trigger as **inconclusive on absolute magnitude** while still treating the _relative_
memory result (500@200ms uses **less** peak traced memory than 200@100ms — fewer, larger snapshots
retained vs. many small ones in this generator, not a general result) as the more trustworthy signal.

**Memory-figure caveat:** `mem_mb` is `tracemalloc` peak traced Python-object memory for one
`BookState` instance plus the generated delta list, not RSS; it undercounts real per-symbol memory (no
interpreter/library baseline, no C-level buffers) and both tiers are far under the 300 MB/symbol budget
regardless — memory did not distinguish the tiers on this measurement.

Bytes/day and rows/s are the load-bearing, non-ambiguous numbers from this table: tier 500@200ms writes
**~24-29% more bytes/day** than tier 200@100ms per symbol despite halved cadence, because each delta
carries up to 2.5x more populated levels — this is the real product-shape finding the ticket predicted
("a materially different product, not a tuning knob"), and is the number `E16` should use unmodified.

## Decision

The harness's `apply_decision_rule()` reports `"depth_200_default"` because every symbol's measured
`cpu_vcpu` at tier 500@200ms is above the 0.5 vCPU/symbol threshold (see committed report). Per this
ADR's own measurement-limitation caveat above, that literal trigger is a **measurement artifact**: this
single-tenant, single-threaded harness reports CPU near 1.0 for _every_ row, including tier 200@100ms,
so the rule's CPU leg cannot discriminate between the two tiers on this evidence — mechanically applying
it here would be "any deviation is justified in the ADR" territory in reverse (accepting a trigger the
evidence doesn't actually support). This is the deviation this ADR records and justifies, per the
ticket's own Gherkin ("the decision follows the rule mechanically and any deviation is justified"):

- **Memory** does not trigger on either tier (both ≤4.7 MB traced, far under 300 MB/symbol) — no signal
  either way from this measurement.
- **CPU** cannot be read as a discriminating signal from a single-tenant harness measurement; treating
  it as a hard trigger would produce the same "depth 200" verdict for both tiers, which is not what the
  rule is for.
- The two tiers are therefore **within noise on the only budget this harness can actually adjudicate**
  (memory), and inconclusive-by-construction on the other (CPU) — matching the ticket's third Gherkin
  scenario exactly: _"Given the two tiers are within noise on every budget… the ADR records 'defer,
  default 200, revisit at E21 with heatmap evidence'"_.

**Decision: defer — default depth 200 (200@100ms) for all symbols. Revisit at E21 with heatmap
evidence.** Trigger to revisit: E21 lands a heatmap prototype and reports that tier-200's coverage (49
ticks/side for a mid-cap symbol like SOLUSDT, vs. 123 at tier 500 — see table) visibly truncates the
rendered depth for the pinned symbol set. Until then, 200@100ms is the safer default: it preserves the
tighter cadence the plan already assumes for DOM, writes **24-29% fewer bytes/day** per symbol (the one
unambiguous cost signal from this spike), and a real per-symbol CPU/vCPU measurement — the one input
this spike could not honestly produce — is required before any tier commitment is treated as final;
`E08-S05` must re-run this harness's methodology against the real M7 `book` module with multiple
concurrent symbols (not this single-tenant harness) to get a trustworthy CPU number before choosing to
widen the default.

Mixed policy (question 6): **operationally sane in principle** — `ExchangeCapabilities.book_cadence_ms`
already carries all four tiers as data (§14.1), and the adapter's "capabilities drive behaviour, not
conditionals" rule (§14.2 item 3) means a per-symbol tier selector is a config lookup, not new adapter
logic. It is not adopted as the _default_ by this ADR because doing so before E08-S05 exists would be
implementing the policy, which is explicitly out of scope for this spike.

## Consequences

- `E08-S05` implements whichever branch above the committed report's `decision.decision` field selects,
  reading the config as data (per-symbol tier from `ExchangeCapabilities`), never as an `if symbol ==`
  conditional.
- `E16` receives this ADR's `bytes_per_day` figures (per tier, per symbol) as its retention/disk budget
  input, taken directly from the committed report rather than re-derived.
- `E08-T06`'s metrics registry declares `book_apply_seconds` and `book_levels_total{symbol}` (currently
  missing — flagged here as the "any gap found in instrumentation" follow-up the ticket calls for) so
  the harness and production report the same names once M7 lands.
- `32-risk-register.md` R3 is updated (this PR) to record the measured budgets as the reference point
  for "Real-time cost" watching going forward.

## Follow-up tickets

- Filed against `E08-S05`: implement the chosen default tier as `ExchangeCapabilities`-driven config;
  re-run this harness against a real `E08-T05` recorded fixture before treating the numbers as
  production SLOs.
- Filed against `E16`: consume the bytes/day figures from `docs/plan/spikes/E08-K01-report.json` as the
  `orderbook_deltas` retention input.
- Filed against `E08-T06`: add `book_apply_seconds` (histogram) and `book_levels_total{symbol}` (gauge)
  to the ingestion metrics registry so this harness and the real M7 module share metric names.
- Filed against `E21`: the stated revisit trigger for the "defer" branch, if that is the outcome — E21
  reports whether tier-200 coverage visibly truncates the heatmap for the pinned symbol set.
