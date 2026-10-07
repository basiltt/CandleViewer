# ADR-0034 — Indicator compute placement (`client_worker` vs `server`) and the worker-mirror parity contract

- Status: **proposed** (owner ratification pending; finalised by E13-T04).
- Date: 2026-10-08
- Deciders: Owner (`@basiltt`) — owner approval pending (Architect + backend lead collapse to the owner per the
  agent-delivery adaptations).
- Numbering note: 0031 is reserved by E45-K01 (`ADR-0031-resilience-and-chaos`, not on `main`); 0033 is the last
  on `main`, so this is the next free number.
- Related: E13-K01 (#348, this spike), E13-T01, E13-T02, E13-T04, E13-S08, E13-Q03, E13-Q05, E13-X01;
  `26-chart-engine-design.md` O4, §3.12, §7, §14; `24-internal-schemas.md` §7.2; ADR-0007 (rule IR);
  `06-performance-and-load-standard.md` §4.3.
- Evidence: [`spikes/e13-o4.md`](../spikes/e13-o4.md) (benchmark, parity and
  assignment tables); throwaway prototypes on `spike/e13-indicator-compute` @ `1e7cfbd`.

## Context and problem statement

O4 asks whether indicator computation belongs in the engine worker or the backend. It is constrained: the rule
engine is server-side, so any rule-referenced indicator is computed authoritatively in the backend, and the worker
copy is a display-only mirror that must match it "bit-for-bit" (§14). E13-T01/T02 need a `compute` value for each
of the 28 v1 indicators and the shape of the parity test.

## Decision drivers

- §4.3: ≤ 2 ms/frame for indicator-pane redraw; SCR-034 first visible window ≤ 250 ms at 100k bars.
- §7 memory table: ≤ 8 MB for profile/indicators/drawings per chart instance.
- One kernel, one result (US-IND-002); rule engine never depends on a browser (C-2.16 keeps the engine
  exchange- and network-free, so it cannot be a rule input source anyway).
- Parity must be testable deterministically on recorded data across a densified gap.

## Considered options

1. Everything `server`, delivered as derived series over the market-data WS.
2. Everything `client_worker`, backend recomputes only what rules reference.
3. **Rule-eligible → `server` (+ optional bit-identical worker mirror); all other v1 indicators → `client_worker`
   unless they exceed the §4.3 budgets.**

## Decision outcome

Chosen: **option 3**.

1. **Placement.** `compute = server` iff the indicator is rule-eligible in `24-internal-schemas.md` §7.2 (today:
   `sma`, `ema`, `rsi`, `atr`, `adx`, `vwap`(+σ bands), `cvd`, `volume`/`bar_volume`, `zigzag` via `swing_high`/`swing_low`) — 9 indicators. The other
   19 v1 indicators are `client_worker`. Measured worker cost at 100k bars: worst full compute 14.8 ms
   (Ichimoku), worst incremental 0.12 µs per closed bar, ten indicators 86 ms full / 1.8 µs per bar — no
   indicator exceeds a budget, so none is `server` on performance grounds. The per-indicator table in the note is
   the seed data for `GET /api/v1/indicators`.
2. **Eligibility drives placement, never the reverse.** Registering a `client_worker` indicator as a rule metric
   (E13-S08 or later) flips it to `server` in the same PR.
3. **Parity stays bit-for-bit.** Measured: scalar Python kernels with the TS operation order agree with the TS
   worker kernels on every value (0 non-identical over 23 output series, recorded window with a 15-bar densified
   gap and 100k synthetic bars). The `abs(a-b) <= 1e-8*max(1,abs(a))` fallback is **not** adopted, so
   `26-chart-engine-design.md` §14 wording is unchanged. Binding kernel rules: IEEE-754 binary64 throughout;
   identical operation order on both sides; the allowed operation set is **only `+ − × ÷ sqrt min max floor`**
   (all correctly rounded / exact in IEEE-754); **`pow`, `exp`, `log` are banned** in mirrored kernels because they are
   libm-dependent and not guaranteed identical across CPython and V8. Indicators that need them (e.g. `realized_vol`-style
   log-return metrics) must declare an explicit epsilon in their own ADR amendment when they arrive; no
   reassociated (prefix-sum / pairwise) or one-pass-variance forms in a `server` kernel — the vectorised VWAP
   σ prototype diverged by up to 0.64 absolute (3.2e-5 relative on the ±3σ band), failing even the epsilon.
   Parity tests assert NaN-aware exact equality.
4. **Worker memory is bounded by retention, not by placement.** Full-history f64 outputs for ten indicators at
   100k bars measured 46.5 MiB (61 series × 100k × 8 B, plus scratch) against the 8 MB allocation that is shared
   with profile + drawings; E13-T01 retains outputs only for a window around the
   viewport, sized by `bars_window ≤ budget_bytes / (output_series × 8)` (e.g. a 4 MiB indicator share at 61 series
   ≈ 8.6k bars), and recomputes off-window ranges from the BarStore.

### Consequences

- Good: no WS derived-series channel is needed for chart-only indicators; rule inputs remain browser-independent;
  the parity contract stays the simplest possible (equality).
- Bad: backend kernels cannot use the obvious numpy vectorisation for sum/variance-based indicators; the server
  scalar kernel is 30–40x slower than the worker (Ichimoku 496 ms/100k in CPython) — acceptable because it is
  incremental per closed bar (≤ 5 µs/bar) and memoised per `(symbol, spec_hash, params)`.
- Risk: authenticated users can trigger backend compute by adding `server` indicators — caps belong to E13-X01.
- **ADR-0007 amendment: not required** — this decision does not change which indicators are rule-eligible.
- **§14 amendment: not required** — bit-for-bit is retained.

### Why not the alternatives

- Option 1 adds WS load and a server round-trip for 20 indicators that the worker computes 17x under budget.
- Option 2 contradicts O4's hard constraint (rules must not depend on a browser) for rule-referenced indicators.

## Open items (owner accepts at ratification)

- The #348 Gherkin AC "measured on reference hardware in Electron" is **open**: the spike measured Node 20 `worker_threads`
  on a shared dev laptop. Handed off to E13-Q03; margins are ≥ 17x.
- The indicator share of the shared 8 MB profile/indicators/drawings allocation is set by E13-T01.

## Validation

- E13-Q05 parity pack: exact-equality assertion on the recorded window (punched gap) and the seeded 100k set; swap in
  a recorder symbol-day when E16 lands.
- E13-Q03: re-measure the benchmark table in Electron on reference hardware; a regression past §4.3 for any
  `client_worker` indicator moves it to `server` per this ADR without a new spike.
- Metrics: `indicator_compute_seconds{indicator,where}`, `indicator_parity_mismatch_total{indicator}` (any non-zero
  is an ERROR), proposed `indicator_output_bytes{where}`.
