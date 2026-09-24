# -*- coding: utf-8 -*-
"""E33 strategy + UI stories and the docs chore."""

from _e33_epic import REFS_COMMON, MS, PH

TICKETS = []


def add(**kw):
    TICKETS.append(kw)


# ---------------------------------------------------------------- S01 OCO
add(
    key="E33-S01",
    kind="Story",
    title="Emulate OCO: race two legs and settle the loser safely",
    labels=["type/feature", "area/oms-execution", "priority/p0", "security", "perf"],
    component="api",
    phase=PH,
    sprint="Sprint 17",
    priority="P0 Critical",
    perspective="Development",
    risk="R7 Data accuracy",
    estimate=5,
    parent="E33",
    blocked_by=["E33-T01"],
    milestone=MS,
    body="""## Context
**US-ALGO-002 — Emulated OCO (Must):** *"As a trader, I want one-cancels-other behaviour, so that hitting a target cancels the stop and vice versa."* Bybit's OCO is UI-only and explicitly unavailable through the v5 API (`docs/plan/24-internal-schemas.md` §10.2), so we race two orders and settle the loser.

The spec is unusually opinionated here and must be implemented as written: for the plain "TP + SL on a position" case the product uses Bybit's **native attached TP/SL** (`trading-stop` with both sides in one call) — emulated OCO exists for cases native brackets cannot express, e.g. two entry orders at different prices where only one should fill. The builder must say so (SCR-069) and the API must not let a user pick emulation where native is available and safer.

## Scope / Deliverables
- `packages/oms/algo/strategies/oco.py` implementing the `AlgoStrategy` protocol against `OcoParams` (`leg_a: OrderIntent`, `leg_b: OrderIntent`, `mode: cancel_other|reduce_other` default `reduce_other`, `reduce_only: bool = True`) exactly as `24-internal-schemas.md` §10.2.
- Leg submission: both legs submitted with `oco_group_ref` set on the `orders` rows (`21-database-schema.md` §3.3.4) and `reduce_only=True` when the OCO protects a position — which makes a double fill self-limiting at the exchange (Bybit rejects the second with `110017`).
- Settlement on fill of qty `q`: `cancel_other` → cancel the sibling when the winner is fully filled; `reduce_other` (default) → **amend** the sibling down by `q`, preserving its queue position and avoiding a naked window.
- Residual/double-fill handler: net position computed **from executions, not from intent**; excess closed with a reduce-only market order; `warning` alert; journal entry; audit `algo.oco_residual_detected` at high severity.
- Failure ladder: three failed cancel/amend attempts on the loser → run `failed`, `critical` alert, native SL left in place — the failure mode is "an extra working order", never "an unprotected position".
- Orphan sweep: when the position goes flat by any other means, both legs are cancelled within one reconciliation cycle and the run closes with reason `position flat`.
- Guardrail in the create path: an OCO whose two legs are simply a TP and an SL on one position is refused with an explanatory error steering the user to native attached TP/SL.

## Out of scope
The SCR-069 builder UI (E33-S05) and the monitor row (E33-S06). Brackets and TP ladders (E32). Group-level OCO (E34).

## Acceptance criteria
```gherkin
Scenario: Target hit
  Given an OCO pair on an open position
  When the target fills
  Then the stop is cancelled (or amended down, per mode) within 1 second of the fill event
  and the run closes as completed

Scenario: Both legs trigger nearly simultaneously
  Given both legs fill before either settlement lands
  Then the net position is computed from executions, the excess is closed with a reduce-only
  market order, the incident is logged and alerted, and the net exposure never exceeds the intent

Scenario: Disconnected during the fill
  Given the backend is offline when the target fills
  When it reconnects
  Then the reconciler detects the fill from the execution stream, cancels the leftover leg,
  and reports the delay it incurred

Scenario: Cancel rejected because already filled (error)
  Given the cancel of the stop is rejected with "order not found / already filled"
  Then the rejection is treated as evidence of a double fill, the resulting net position is
  computed from executions, and if the position flipped sign a reduce-only correcting order is
  placed and a high-severity incident is raised — never a silent reverse position

Scenario: Crash between fill and cancel (edge)
  Given the process is killed after the fill event is persisted but before the cancel is sent
  When it restarts
  Then the OCO state machine replays from Postgres, sends the cancel with the original
  idempotency key, and completes within 5 seconds of process start

Scenario: Duplicate fill event (edge)
  Given the same fill is delivered twice by the websocket
  Then the idempotency key makes the second settlement a no-op, exactly one audit record
  describes the OCO completion, and no extra rate-limit budget is consumed

Scenario: Position closed manually (edge)
  Given I flatten the position by hand while both legs rest
  Then both legs are cancelled as orphans within one reconciliation cycle and the run closes
  with reason "position flat"

Scenario: Native path preferred (edge)
  Given an OCO request that is simply a take-profit and a stop-loss on one position
  Then it is refused with an explanation pointing at native attached TP/SL, and nothing is sent
```

## Technical notes / design
Settlement latency budget is measured from the **WS execution frame**, not from the REST ack, because the execution stream is the source of truth (E29 / ADR-0006).

Idempotency: every outbound cancel/amend carries a deterministic key derived from `(algo_run_id, slice_seq, intent_sequence)` — US-ALGO-002 NFR. The reconciler is authoritative over the UI.

Error mapping: `110001` order-not-found on the loser's cancel after a winner fill is the *expected* benign race and must not raise; the same code on an untriggered leg is a real fault.

## Test plan
- **Unit**: settlement in both modes; partial-fill amend arithmetic including lot-size rounding; residual computation from executions with duplicate and out-of-order delivery; the three-failure ladder; the native-preferred guardrail; orphan sweep on flat.
- **Integration**: recorded Bybit fixtures for `110017` reduce-only rejection, `110001` cancel-after-fill, and a synthetic simultaneous-fill fixture.
- **Chaos**: kill between fill persist and cancel send — the dedicated seam named in the story; must complete within 5 s of restart.
- **Perf**: fill event → cancel/amend request issued ≤ 300 ms p95 over 1 000 simulated races.
- Coverage ≥ 90 % on `packages/oms/algo/strategies/oco.py`.

## Security notes
Order-placing path → `security`-labelled. Threats: double-fill producing an unintended reverse position (the epic's most consequential integrity risk — mitigated by reduce-only legs, execution-derived netting and the correcting order); repudiation (every leg fill, cancel and residual correction audited); tampering (leg intents revalidated server-side against instrument filters and the account profile). Manual abuse-case check required: attempt an OCO as a `viewer`, and while the kill-switch is engaged.

## Accessibility notes
N/A — backend. The UI obligations live on E33-S05 / E33-S06.

## Performance notes
Fill → opposing-leg settlement request ≤ 300 ms p95 (SCR-069 performance note). Submission of both legs inside budget #4 (p95 < 300 ms per order).

## Observability
Audit `algo.oco_created`, `algo.oco_leg_filled`, `algo.oco_leg_cancelled`, `algo.oco_race_resolved {winner, resolutionMs}`, `algo.oco_residual_detected` (high severity), `algo.oco_cancelled|completed|failed`. Metric `oms_oco_race_resolution_ms` histogram, `oms_oco_residual_total`.

## Definition of Done
- [ ] Every Gherkin scenario covered by a test that names it.
- [ ] Coverage ≥ 90 % on the strategy module; package ≥ 85 %.
- [ ] Chaos seam test in CI and green.
- [ ] `24-internal-schemas.md` §10.2 updated if behaviour diverged.
- [ ] Security review comment; abuse cases executed.
- [ ] Perf benchmark for race resolution recorded.
- [ ] QA sign-off with pass/fail per scenario (E33-Q01).
- [ ] Demoed on demo environment.
- [ ] Feature flag `algo.oco` recorded: demo on, live off until R4.
- [ ] PR merged via merge queue.

## Dependencies
E33-T01 (framework, guards, persistence, idempotency). E29 (execution stream, cancel/amend routes, reconciler). E32 (native SL that remains the floor when OCO fails).

## Branch
`feat/e33-oco`.

## References
""" + REFS_COMMON,
)

# ---------------------------------------------------------------- S02 iceberg
add(
    key="E33-S02",
    kind="Story",
    title="Emulate iceberg: slice a large order into randomised visible tranches",
    labels=["type/feature", "area/oms-execution", "priority/p1", "security", "perf"],
    component="api",
    phase=PH,
    sprint="Sprint 17",
    priority="P1 High",
    perspective="Development",
    risk="R3 Real-time cost",
    estimate=5,
    parent="E33",
    blocked_by=["E33-T01"],
    milestone=MS,
    body="""## Context
**US-ALGO-005 — Emulated iceberg (Should):** *"As a trader, I want a large order sliced into visible tranches, so that I do not show my full size."* Bybit's `orderType` is Market/Limit only — there is no `displayQty` and no native iceberg (`docs/plan/24-internal-schemas.md` §10.3), so this is entirely app-managed and must be labelled "(app-managed)" everywhere it appears.

Randomisation is not a nicety: a perfectly regular refill is trivially detectable by the very iceberg detector CandleViewer itself ships (E25 / §7 `iceberg_present_at_level`), so jitter is on by default.

## Scope / Deliverables
- `packages/oms/algo/strategies/iceberg.py` against `IcebergParams` (`display_qty`, `total_qty`, `price_mode: fixed|peg_best|peg_offset`, `price`, `peg_offset_ticks`, `reprice_threshold_ticks`, `randomize_pct` default 0.2, `min_slice_qty` defaulting to the instrument's `min_order_qty`, `refill_delay_ms` 250, `refill_jitter_ms` 250, `post_only` True, `max_slices` 450) exactly as §10.3.
- Slicing loop: submit one visible child of `display_qty` jittered by ±`randomize_pct`, floored to `qty_step`, never below `min_slice_qty`; on **full** fill wait `refill_delay_ms + U(0, refill_jitter_ms)` and submit the next; on **partial** fill leave the child working and only refill after it terminates.
- Dust rule: the final slice is exactly the remainder; if that remainder is below `min_order_qty` it is **merged into the previous slice** so the algo never strands an unsendable quantity. If even the merged size is unfillable, the run completes with status detail `remainder unfillable`.
- Repricing: in `peg_best`/`peg_offset` the price is re-evaluated **per slice**, not continuously (continuous repricing is `chase`, E33-S04), and only when drift ≥ `reprice_threshold_ticks`; every reprice is logged.
- Rejection handling: a slice rejected for minimum-notional, lot-size or insufficient-margin **pauses** the run rather than retrying in a loop; the exact exchange reason and the filled-so-far quantity are surfaced, and the user chooses resume-with-smaller-slice, convert-remainder-to-a-single-order, or abandon (these three resolutions exposed as `POST /algos/{algoId}/control` extensions agreed in E33-T02).
- Post-only edge: a `post_only` slice rejected for crossing is retried **once** at the new best; two consecutive post-only rejections pause the run for 1 s.
- Crash edge: the resting slice is **adopted** by `order_link_id` rather than duplicated; filled-so-far is recomputed from `executions`; slicing resumes within 5 s.
- Kill-switch edge: slicing stops immediately, the resting slice is cancelled, the run ends `halted by risk control` with the reason recorded.
- Projected request-rate calculation exported for SCR-067's pre-submit estimate.

## Out of scope
The SCR-067 builder UI (E33-S05). Monitor row (E33-S06). Continuous repricing (S04). Scaled ladders (E32).

## Acceptance criteria
```gherkin
Scenario: Slicing
  Given a total of 5 BTC with a visible slice of 0.25
  Then only one slice rests at a time and a replacement is placed after each fill until the
  total is complete, with slice sizes jittered by the configured randomisation

Scenario: Price moves away
  Given the reprice policy is peg-to-best
  Then remaining slices reprice per the policy once drift exceeds the threshold, each reprice
  is logged, and repricing happens per slice rather than continuously

Scenario: Cancelled mid-way
  When I cancel the run
  Then the working slice is cancelled, no further slices are placed, and the filled portion is
  reported as a normal position with its protective stop intact

Scenario: Slice rejected by the exchange (error)
  Given a replacement slice is rejected for minimum-notional, lot-size or insufficient margin
  Then slicing pauses instead of retrying in a loop, the exact exchange reason and the filled
  quantity are surfaced, and resume-with-smaller-slice, convert-remainder or abandon are offered

Scenario: Final remainder below the minimum lot (edge)
  Given the untraded remainder is smaller than the instrument's minimum order quantity
  Then the last slice absorbs the remainder rather than leaving a dust order, and if even the
  combined size is below the minimum the run completes with "remainder unfillable"

Scenario: Crash with a slice resting (edge)
  Given the backend restarts while one slice rests
  Then that slice is adopted by client order id rather than duplicated, the filled total is
  recomputed from executions, and slicing resumes within 5 seconds

Scenario: Kill-switch during slicing (edge)
  Given the owner triggers a freeze or the daily-loss lockout fires
  Then slicing stops immediately, the resting slice is cancelled, and the run ends in
  "halted by risk control" with the reason recorded

Scenario: Post-only rejection (edge)
  Given a post-only slice is rejected for crossing
  Then it is retried once at the new best, and two consecutive such rejections pause the run
  for one second rather than hot-looping
```

## Technical notes / design
Every slice carries a client order id encoding the run (`order_link_id` group segment + `seq2` + `ac`), so orphan adoption is deterministic — US-ALGO-005 NFR.

Jitter uses the supervisor's seeded RNG so tests are reproducible; the seed is persisted with the run so a resume continues the same sequence.

Rate cost: one submission per slice plus one cancel per reprice; the projected requests/min figure is `slices_remaining / expected_fill_interval` and is what SCR-067 refuses configurations on.

## Test plan
- **Unit**: jittered slice sizing with `qty_step` flooring and `min_slice_qty` floor; dust merge including the unfillable case; partial-fill hold-off; reprice threshold; rejection classification (minimum-notional vs lot-size vs margin vs post-only crossing); pause-and-resolve transitions; seeded-RNG reproducibility.
- **Integration**: recorded fixtures for lot-size rejection, insufficient margin, post-only rejection, and a partial-fill-then-terminate sequence.
- **Chaos**: restart with a slice resting → adoption, not duplication; kill-switch mid-run.
- **Perf**: 450-slice run staying inside the account rate budget with the protective reserve untouched.
- Coverage ≥ 90 % on the strategy module.

## Security notes
Order-placing path → `security`-labelled. Threats: rate-budget exhaustion starving protective orders (mitigated by the reserve and the projected-rate refusal); tampering with `display_qty` to produce thousands of children (bounded by `max_slices` 450 and `min_slice_qty`); information disclosure — `params` reveal hidden size and are restricted to users with account access. Abuse case: an iceberg configured with a minimum slice as a request-flood vector (E33-X02).

## Accessibility notes
N/A — backend.

## Performance notes
Per-slice submission inside budget #4. A run must never exceed its account's order token-bucket allowance nor touch the protective reserve (`24-internal-schemas.md` §8).

## Observability
Audit `algo.iceberg_created {symbol, side, totalQty, visibleQty, refreshPolicy, accountIds}`, `algo.iceberg_paused|resumed|cancelled|completed|failed`, `algo.iceberg_slice_replaced` (sampled — it is rate-relevant). Metrics `oms_algo_child_orders_total{kind="iceberg"}`, `oms_iceberg_slice_rejections_total{reason}`.

## Definition of Done
- [ ] Every Gherkin scenario covered by a named test.
- [ ] Coverage ≥ 90 % strategy module, ≥ 85 % package.
- [ ] Chaos adoption test green.
- [ ] `24-internal-schemas.md` §10.3 updated on divergence.
- [ ] Security review comment; abuse case executed.
- [ ] Rate-budget benchmark recorded.
- [ ] QA sign-off (E33-Q01).
- [ ] Demoed on demo.
- [ ] Feature flag `algo.iceberg`: demo on, live off until R4.
- [ ] PR merged via merge queue.

## Dependencies
E33-T01 (framework, adoption, rate guards, seeded RNG). E29 (instrument filters, execution stream). E32 (native SL on the first fill).

## Branch
`feat/e33-iceberg`.

## References
""" + REFS_COMMON,
)

# ---------------------------------------------------------------- S03 TWAP
add(
    key="E33-S03",
    kind="Story",
    title="Emulate TWAP: schedule slices over a window with jitter and catch-up",
    labels=["type/feature", "area/oms-execution", "priority/p1", "security", "perf"],
    component="api",
    phase=PH,
    sprint="Sprint 18",
    priority="P1 High",
    perspective="Development",
    risk="R11 Alert reliability",
    estimate=5,
    parent="E33",
    blocked_by=["E33-S02"],
    milestone=MS,
    body="""## Context
**US-ALGO-006 — Emulated TWAP (Should):** *"As a trader, I want an order executed in equal slices over a time window, so that I reduce impact."* TWAP is not a native Bybit order type; the scheduler is server-side, survives client disconnects and browser closure, and is driven by **persisted wall-clock schedule rows rather than in-memory timers** (US-ALGO-006 NFR, `docs/plan/24-internal-schemas.md` §10.4).

The dangerous case is not the happy path — it is the resumed one. A process suspended across two scheduled slice times must never fire the missed slices back to back; that is how a "reduce impact" algo becomes an impact event.

## Scope / Deliverables
- `packages/oms/algo/strategies/twap.py` against `TwapParams` (`duration_ms`, `slices` ≥ 2, `order_type: market|limit` default limit, `limit_offset_ticks`, `randomize_time_pct` 0.25, `randomize_qty_pct` 0.20, `catch_up: none|next_slice|proportional` default `next_slice`, `max_participation_pct`, `price_limit`, `abort_on_price_limit` False) exactly as §10.4.
- Schedule generation: nominal slice `q = total_qty / slices`, nominal interval `T = duration_ms / slices`; slice *i* planned at `start + i*T ± U(0, randomize_time_pct*T)` with qty `q ± randomize_qty_pct` floored to `qty_step`. All planned rows written to `algo_slices` at start, so the schedule is inspectable (and previewable by SCR-066) and survives restart.
- Participation cap: `max_participation_pct` shrinks a slice so the run never exceeds that share of the volume actually traded since the previous slice — the defence against pushing an illiquid book.
- Shortfall handling per `catch_up`: `none` abandons, `next_slice` adds to the next, `proportional` redistributes across remaining slices. The final slice always carries the exact remainder.
- End-of-window policy executed **exactly once**, shown on the panel *before* the window ends: `final_market_sweep` (default true) converts an unfilled final limit slice to market, subject to `price_limit`; alternatives leave-as-limit or cancel-remainder.
- Price-limit breach: **pause** by default (a temporary spike should not abandon an execution); abort only when `abort_on_price_limit`.
- Spread guard: slices are skipped with a logged reason when the spread exceeds the configured maximum, and the schedule adapts — never silently overtrading later.
- Missed-window re-planning: on resume, remaining quantity is re-planned over the **remaining** window, any single catch-up slice is capped at the configured maximum participation, and the event is logged as e.g. "2 slices missed, re-planned". Next slice time is recomputed from wall clock, never from process start.
- Pause/resume via `POST /algos/{algoId}/control`, with remaining time recalculated and extend/compress offered.
- Slices whose qty rounds below `min_order_qty` are skipped and their quantity rolls forward; exceeding `max_duration_ms` cancels the run with the remainder unfilled and raises a `warning`.

## Out of scope
The SCR-066 builder UI (E33-S05). Monitor row (E33-S06). Volume-weighted (VWAP) execution — not in the roadmap for R3.

## Acceptance criteria
```gherkin
Scenario: TWAP running
  Given 2 BTC over 30 minutes in 10 slices
  Then a slice is submitted approximately every 3 minutes within the configured time jitter,
  and progress shows completed, remaining and average fill price

Scenario: Pause and resume
  When I pause the run
  Then no further slices are sent until I resume, and on resume the remaining time is
  recalculated with the option to extend or compress the window

Scenario: Market disruption
  Given the spread exceeds the configured maximum
  Then slices are skipped with a logged reason and the schedule adapts,
  never silently overtrading later

Scenario: Clock drift or missed schedule window (error)
  Given the process was suspended across two or more scheduled slice times
  When it resumes
  Then the missed slices are never fired back to back; the remaining quantity is re-planned over
  the remaining window, any single catch-up slice is capped at the configured maximum
  participation, and "2 slices missed, re-planned" is logged

Scenario: Window expires with quantity remaining (edge)
  Given the window ends before the total is filled because slices were skipped
  Then the configured end-of-window policy executes exactly once, and the policy in force was
  shown on the panel before the window ended, not only afterwards

Scenario: Backend restart mid-TWAP (edge)
  Given the scheduler process restarts
  Then the schedule, filled quantity and skip history are restored from Postgres, the next
  slice time is recomputed from wall clock, and no slice is duplicated because each carries a
  deterministic per-slice client order id

Scenario: Owner freeze during the window (edge)
  Given the kill-switch or daily-loss lockout fires mid-window
  Then the scheduler halts, pending slices are cancelled, and the run ends in
  "halted by risk control" — resumption requires an explicit re-arm, never automatic continuation

Scenario: Participation cap (edge)
  Given traded volume since the previous slice is small
  Then the next slice is shrunk so the run stays within max_participation_pct of that volume,
  and the shrink is recorded with the observed volume
```

## Technical notes / design
The schedule is data: `algo_slices` rows with `planned_at`, `planned_qty`, `state`. The scheduler (E33-T01) polls the `next_action_at` index; nothing depends on an in-memory timer surviving. Re-planning rewrites the *future* rows only — executed and skipped rows are immutable history, which is what makes the skip log trustworthy.

Traded-volume input for `max_participation_pct` comes from the ingestion trade stream aggregated per interval (module M4/M5), not from klines, so live and replay agree.

Config keys: `oms.algo.twap.final_market_sweep=true`, `oms.algo.twap.max_spread_ticks`, `oms.algo.twap.min_slice_interval_ms=1000`.

## Test plan
- **Unit**: schedule generation with jitter bounds and deterministic seed; catch-up arithmetic in all three modes; participation shrink; sub-minimum slice roll-forward; end-of-window policy executed exactly once (including the double-trigger guard); price-limit pause vs abort; spread-skip logging; re-planning after N missed windows with the participation cap applied.
- **Integration**: recorded fixtures for partial fills across slices, a rejection mid-schedule, and `10018` back-off.
- **Chaos**: `tests/chaos/test_twap_restart.py` — restart mid-window (the roadmap's named chaos scenario "backend restart mid-TWAP"); suspend the event loop for 2 intervals and assert no back-to-back firing.
- **Perf**: 500-slice schedule, drift < 250 ms per slice; 50 concurrent TWAPs within the account rate budget.
- Coverage ≥ 90 % on the strategy module.

## Security notes
Order-placing path → `security`-labelled. Threats: a long-running scheduled algo is the longest-lived authorisation in the product — the run records `created_by` and is re-checked against `user_account_access` at each slice, so revoking a manager's access stops their running TWAPs; denial of wallet via an absurd `slices`/`duration` combination (bounded by `slices ≤ 500`, `max_duration_ms`, `min_slice_interval_ms`); repudiation (full slice history audited). Abuse case in E33-X02: schedule survival across a permission revocation.

## Accessibility notes
N/A — backend. SCR-066's schedule preview table and textual progress are E33-S05/S06.

## Performance notes
Scheduler drift < 250 ms per slice at 500 slices; per-slice submission inside budget #4; 50 concurrent runs without breaching the per-account token bucket or the protective reserve.

## Observability
Audit `algo.twap_created {symbol, side, totalQty, duration, sliceCount, randomisation, accountIds}`, `algo.twap_paused|resumed|cancelled|completed`, `algo.twap_slice_failed`, plus `algo.twap_replanned {missed, remaining}`. Metrics `oms_algo_scheduler_drift_ms`, `oms_twap_slices_skipped_total{reason}`, `oms_twap_participation_shrink_total`.

## Definition of Done
- [ ] Every Gherkin scenario covered by a named test.
- [ ] Coverage ≥ 90 % strategy module, ≥ 85 % package.
- [ ] Chaos restart-mid-TWAP test in CI and green (R3 quality gate).
- [ ] `24-internal-schemas.md` §10.4 updated on divergence.
- [ ] Security review comment; the permission-revocation abuse case executed.
- [ ] Perf benchmark recorded (drift, concurrency).
- [ ] QA sign-off (E33-Q01).
- [ ] Demoed on demo.
- [ ] Feature flag `algo.twap`: demo on, live off until R4.
- [ ] PR merged via merge queue.

## Dependencies
E33-S02 — iceberg lands first and establishes the slice-lifecycle, adoption and rejection-classification code paths TWAP reuses (per US-ALGO-006's own `Deps: US-ALGO-005`). E33-T01 (scheduler, persistence, guards). E29 (executions, rate buckets). E39 (kill-switch, lockouts).

## Branch
`feat/e33-twap`.

## References
""" + REFS_COMMON,
)

# ---------------------------------------------------------------- S04 chase
add(
    key="E33-S04",
    kind="Story",
    title="Emulate chase: peg a limit to the best price with hard anti-runaway bounds",
    labels=["type/feature", "area/oms-execution", "priority/p1", "security", "perf"],
    component="api",
    phase=PH,
    sprint="Sprint 18",
    priority="P1 High",
    perspective="Development",
    risk="R3 Real-time cost",
    estimate=5,
    parent="E33",
    blocked_by=["E33-T01", "E33-S02"],
    milestone=MS,
    body="""## Context
**US-ALGO-007 — Chase / pegged limit (Should):** *"As a trader, I want an order that follows the best bid or ask, so that I get filled without crossing."* Bybit has no pegged order type (`docs/plan/24-internal-schemas.md` §10.5), so the backend amends a resting limit as the book moves.

Chase is the highest-risk strategy in the epic for two independent reasons: it is the **highest request-rate** path (every reprice costs an `order.amend` token), and an unbounded chase follows a trending market until it fills at a terrible price. Both are bounded by hard, non-optional caps. The single most common implementation bug is documented in §10.5 and has a dedicated regression test: in `maker` mode, when our own order is the sole best quote, the target must be computed **excluding our own size**, or the algo chases itself one tick at a time into a self-inflicted spread walk.

## Scope / Deliverables
- `packages/oms/algo/strategies/chase.py` against `ChaseParams` (`mode: maker|taker|offset`, `offset_ticks`, `max_chase_ticks`, `reprice_interval_ms` default 200, `reprice_threshold_ticks` default 1, `max_repricings` default 200, `timeout_ms` 60 000, `on_timeout: market|cancel|leave` default cancel, `post_only` True) exactly as §10.5.
- Target price computation per mode: `maker` = same-side best ± `offset_ticks` **excluding our own resting size**; `taker` = opposite-side best (crossing); `offset` = best ± fixed offset.
- Reprice loop driven by book updates: reprice only when drift ≥ `reprice_threshold_ticks` **and** ≥ `reprice_interval_ms` since the last reprice; **amend** rather than cancel/replace (one request instead of two, and no window with no order in the book).
- Debounce: a flapping best price is debounced to the interval and only the latest target is acted on.
- Hard bounds: never beyond `max_chase_ticks` from the arm price; stop after `max_repricings`; stop at `timeout_ms` and apply `on_timeout`. Each is independently tested.
- One-live-order invariant: asserted in code before every placement and enforced by the `ux_algo_one_live_child` partial unique index from E33-T01 (US-ALGO-007 NFR).
- Amend-races-fill: an amend rejection with `110001` while a fill is in flight is classified **benign**; the run ends `filled`, the fill is attributed once, and **no replacement order is created** — a replacement after a fill would double the position and is explicitly forbidden.
- Non-fill amend rejection (e.g. post-only would cross): cancel and re-place **at most once per reprice interval**, verifying the cancel acknowledgement before placing; if a cancel is ever unacknowledged the chase **aborts** so it can never hold two live orders.
- Rate-budget behaviour: when the amend token budget is exhausted, repricing **throttles** rather than failing, and the throttling is visible in the run detail (surfaced by E33-T02's projection for SCR-068/SCR-070).
- Crash edge: adopt the resting order by `order_link_id`, **read its current price back from the exchange** rather than assuming, and resume chasing only after the adopted state is confirmed.
- Fall-back-to-market is opt-in only (`on_timeout=market`), and its slippage risk is stated in SCR-068.

## Out of scope
The SCR-068 builder UI (E33-S05). Monitor row (E33-S06). Iceberg's per-slice repricing (S02). Trailing stops (E32).

## Acceptance criteria
```gherkin
Scenario: Chasing
  Given a chase buy pegged to best bid with a one-tick offset
  Then the order is amended to follow the best bid, respecting the minimum reprice interval

Scenario: Max chase distance
  Given the price has moved beyond the configured maximum distance from the arm price
  Then chasing stops, the order is cancelled or left resting per the configured policy,
  and I am notified

Scenario: Reprice rate limited
  Given the amend rate budget is exhausted
  Then repricing throttles rather than failing, and the throttling is visible in the run detail

Scenario: Amend races a fill (error)
  Given an amend is in flight when the order fills
  Then the amend rejection is classified as benign, the run ends in state "filled", the fill is
  attributed exactly once, and no replacement order is created

Scenario: Amend rejected as unmodifiable, replacement needed (edge)
  Given the venue rejects an amend for a reason that is not a fill
  Then the algorithm cancels and re-places at most once per reprice interval, verifies the
  cancel acknowledgement before placing, and aborts the chase if a cancel is ever unacknowledged

Scenario: Flapping best price (edge)
  Given the best bid oscillates faster than the minimum reprice interval
  Then repricing is debounced to the interval, only the latest target price is acted on,
  and the account's rate budget is not burned

Scenario: Chase orphan after crash (edge)
  Given the backend restarts while a chase order rests
  Then the order is adopted by client order id, its current price is read back from the
  exchange rather than assumed, and chasing resumes only after the adopted state is confirmed

Scenario: Self-chase guard (edge)
  Given our own order is the sole best quote
  Then the target is computed excluding our own size and no reprice occurs,
  so the algorithm cannot walk the spread against itself
```

## Technical notes / design
Book input is the engine's `BookEngine` top-of-book stream (module M5, `24-internal-schemas.md` §2), not a polled REST call.

`max_chase_ticks` is measured from the **arm price** (the best price at run start), not from the last reprice, so a slow drift cannot be laundered into an unbounded move.

Every reprice consumes an `order.amend` token from the account bucket; the protective reserve is never drawn on (§8), so a stop-loss or flatten can always get a token even while a chase saturates the budget.

Config keys: `oms.algo.chase.min_reprice_interval_ms=200` (floor, not overridable downward), `oms.algo.chase.max_repricings_cap=500`.

## Test plan
- **Unit**: target computation per mode including the self-chase exclusion (dedicated named regression test); debounce and interval gating; each of the three hard bounds independently; benign-vs-real amend-rejection classification; the cancel-unacknowledged abort path; throttle-on-empty-budget.
- **Property test**: over randomly generated book-update sequences, assert the invariant "at most one live order" and "never beyond max_chase_ticks" hold for every prefix.
- **Integration**: recorded fixtures with a fast-moving book, `110001` amend-after-fill, post-only crossing rejection, `10018` amend rate limit.
- **Chaos**: restart with a resting chase order → adoption with price read-back; DB-level rejection of a second live slice.
- **Perf/load**: k6-driven flapping-book soak for 1 h, asserting zero budget exhaustion of the protective reserve and reprice interval ≥ 200 ms at all times.
- Coverage ≥ 90 % on the strategy module.

## Security notes
Order-placing path → `security`-labelled. Threats: **denial of wallet** — a runaway chase is the epic's clearest self-inflicted-loss vector, bounded by three independent caps; **resource exhaustion** — reprice storms starving protective orders, bounded by the token bucket's reserve and the interval floor; **integrity** — a replacement after a fill doubling the position, forbidden and tested. Abuse case in E33-X02: a chase configured at the interval floor against a synthetic flapping book as a rate-limit DoS on the account's own budget.

## Accessibility notes
N/A — backend.

## Performance notes
Reprice interval ≥ 200 ms (hard floor). Amend request p95 inside budget #4. Sustained 1 h flapping-book soak with no lost acknowledgements and correct governor back-off (R3 load gate).

## Observability
Audit `algo.chase_created {symbol, side, qty, peg, offsetTicks, maxDistance, maxRepricings, fallback, accountIds}`, `algo.chase_repriced` (sampled/aggregated — it is high-rate), `algo.chase_limit_reached`, `algo.chase_fell_back_to_market`, `algo.chase_cancelled|completed|failed`. Metrics `oms_chase_repricings_total`, `oms_chase_throttled_seconds`, `oms_chase_distance_ticks` histogram.

## Definition of Done
- [ ] Every Gherkin scenario covered by a named test, including the self-chase regression test.
- [ ] Property test for the two invariants in CI.
- [ ] Coverage ≥ 90 % strategy module, ≥ 85 % package.
- [ ] Chaos adoption test green; DB unique-index test green.
- [ ] `24-internal-schemas.md` §10.5 updated on divergence.
- [ ] Security review comment; the rate-DoS abuse case executed.
- [ ] 1 h soak result recorded.
- [ ] QA sign-off (E33-Q01).
- [ ] Demoed on demo.
- [ ] Feature flag `algo.chase`: demo on, live off until R4.
- [ ] PR merged via merge queue.

## Dependencies
E33-T01 (framework, the one-live-order index, rate guards, adoption). E33-S02 (slice lifecycle and rejection classification reused; US-ALGO-007's own `Deps` chain runs through iceberg/TWAP). E29 (amend route, execution stream, token buckets). M5 BookEngine for top-of-book.

## Branch
`feat/e33-chase`.

## References
""" + REFS_COMMON,
)

# ---------------------------------------------------------------- S05 builders
add(
    key="E33-S05",
    kind="Story",
    title="Build the emulated-algo builder modals SCR-066, SCR-067, SCR-068 and SCR-069",
    labels=["type/feature", "area/oms-execution", "priority/p1", "a11y", "design-qa", "security"],
    component="web",
    phase=PH,
    sprint="Sprint 18",
    priority="P1 High",
    perspective="Development",
    risk="R11 Alert reliability",
    estimate=3,
    parent="E33",
    blocked_by=["E33-T02", "E33-D06"],
    milestone=MS,
    body="""## Context
Each emulated strategy needs a configuration surface, and `docs/plan/14-screens-catalogue.md` specifies four of them precisely: **SCR-066 TWAP builder**, **SCR-067 Iceberg (emulated) builder**, **SCR-068 Chase-limit builder** and **SCR-069 Emulated OCO / bracket builder** (this story ships the OCO half; E32 ships the bracket half of the same modal).

The through-line of all four is honesty: each states *in text, not in a tooltip* that the strategy is emulated by CandleViewer because Bybit's API has no such order type, each shows the projected request rate before submit, and each carries CMP-158 SafetyInvariantNotice stating that the native stop remains in force regardless.

## Scope / Deliverables
- **SCR-066 TWAP builder** (modal): total qty, duration, slice count/interval, price limit (max slippage), randomisation, participation cap, disconnect behaviour. Validation: duration 1 min–24 h; slices 2–500; each slice ≥ min lot with the exact message *"Slices of 0.0004 BTC are below the minimum — reduce slice count."* Schedule preview table (slice #, planned time, qty). States: configured · running · paused (auto-paused on disconnect with a banner) · completed · cancelled · failed.
- **SCR-067 Iceberg builder** (modal): total qty, visible qty, refresh behaviour, price offset/peg, max show-ratio. Validation: visible qty ≥ min lot and ≤ 50 % of total (configurable) — *"Visible size must be at least the minimum lot and no more than half the total."* Prominent "emulated client-side — Bybit's API has no native iceberg field" text. Projected requests/min shown before submit.
- **SCR-068 Chase-limit builder** (modal): peg to best bid/ask/mid with a signed offset in ticks, re-peg threshold, max chase distance from the arrival price, max repricings, fall-back-to-market toggle (opt-in, with its slippage risk stated), timeout. Validation: max chase distance > offset; max repricings 1–500; rate estimate shown (*"≈ 12 requests/min — within your per-account budget"*) and configurations projected to exceed the account budget are **refused with an explicit message**.
- **SCR-069 OCO builder** (modal, OCO half): entry + OCO exit pair or a standalone OCO on an existing position; "emulated — Bybit's API has no OCO" stated prominently; race-resolution behaviour explained as a paragraph; residual-risk state (app offline during a fill) drawn with what the user must do; the mandatory native SL floor shown as always present and non-removable. Validation: the two legs on opposite sides of the mark, quantities matching the position.
- Submission through `POST /api/v1/orders` with the appropriate `algo: AlgoSpec` payload; progress subsequently read from the WS `orders` topic; the confirm policy and arm/lock gating of E30 apply unchanged.
- Components: CMP-008 NumericStepperInput, CMP-043 Dialog, CMP-047 DatePicker / DateRangePicker, CMP-100 PriceInput, CMP-101 QtyInput, CMP-118 AlgoProgressCard, CMP-119 BracketEditor (SCR-069), CMP-130 SlippageEstimateChip, CMP-158 SafetyInvariantNotice, CMP-227 EstimatedBadge; entry point via CMP-115 OrderTypeSelector's "Emulated" group.
- Analytics `algo.twap_previewed`, `algo.iceberg_previewed`, `algo.scaled_previewed` (the last owned by E32 but wired from the same selector).

## Out of scope
SCR-065 scaled/ladder builder and the bracket half of SCR-069 (**E32**). The monitor panel SCR-070 (**E33-S06**). Strategy behaviour (S01–S04). The order ticket itself, sizing and arm/lock (**E30**).

## Acceptance criteria
```gherkin
Scenario: Configure and start a TWAP
  Given BTCUSDT and a valid account with chart trading armed
  When I open the TWAP builder, enter 2 BTC over 30 minutes in 10 slices and submit
  Then the schedule preview lists ten slices with planned times and quantities before submit,
  the run is created, and the modal transitions to the running state with live progress

Scenario: Slice below minimum lot (failure)
  Given a slice count that makes each slice smaller than the instrument's minimum quantity
  Then submit is blocked with "Slices of <qty> are below the minimum — reduce slice count."
  and nothing is sent

Scenario: Chase configuration exceeding the rate budget (failure)
  Given a chase configuration whose projected request rate exceeds the account's budget
  Then the builder refuses it with an explicit message naming the projected and allowed rates

Scenario: Emulation is stated, not hidden (edge)
  Given any of the four builders
  Then the emulation caveat is rendered as a text paragraph readable by a screen reader,
  never only as a tooltip or a colour, and the native stop-loss floor is shown as non-removable

Scenario: Backend disconnect while running (edge)
  Given a running algo and the backend connection drops
  Then the builder shows the degraded/paused state explaining that slicing is suspended and
  native stops still protect, with the residual risk stated

Scenario: Invalid OCO legs (failure)
  Given two OCO legs on the same side of the mark, or quantities not matching the position
  Then submit is blocked with the specific validation message and nothing is sent

Scenario: Keyboard only
  Given a keyboard-only user
  Then every builder is fully operable, focus is trapped in the modal and restored on close,
  the schedule preview is reachable as a table, and validation errors are announced
```

## Technical notes / design
Implement the E33-D06 handoff redlines; where the screens catalogue and the handoff disagree, the handoff wins and the divergence is recorded in E33-T03.

All four modals share one `AlgoBuilderShell` (title, emulation notice, safety-invariant notice, projected-rate chip, validation summary, submit/cancel) so the honesty affordances cannot be forgotten in one of them — a design-system contribution made in E33-D04.

Instrument filters (`priceFilter.tickSize`, `lotSizeFilter.minOrderQty`/`qtyStep`) come from the cached `GET /api/v1/instruments/{symbol}`; validation is client-side for feedback and **re-validated server-side** — the client is never the authority.

Projected request rate: iceberg `= total/visible slices ÷ expected fill interval`; chase `= 60 000 / reprice_interval_ms` capped by `max_repricings`; both compared against `GET /api/v1/me/limits`.

## Test plan
- **Unit/component**: validation rules and their exact messages per screen; schedule preview generation; projected-rate arithmetic and the refusal threshold; state rendering for configured/running/paused/degraded/completed/failed.
- **Storybook**: each builder in every enumerated state, light/dark, both densities; CMP-118 AlgoProgressCard variants per algo kind; visual regression.
- **Integration**: against a mocked `POST /orders` and a mocked `orders` WS topic — submit → running → completed.
- **E2E (Playwright, web + Electron)**: start a TWAP and an iceberg on demo, assert the run appears in the monitor panel; attempt a sub-minimum slice and assert no network request was made.
- **A11y**: axe-core on all four screens; keyboard-only pass; screen-reader pass on the emulation caveat and validation errors.
- Coverage ≥ 80 % frontend on touched files.

## Security notes
These modals create orders → `security`-labelled per `02-definition-of-ready-done.md` §8. Client-side validation is UX only; the server re-validates every `AlgoSpec` field (E33-T02). The arm/lock control and confirmation policy from E30 gate submission; a disarmed user cannot submit from a builder. A `viewer` must not see submit controls at all, and the server returns 403 regardless. Manual abuse-case check: submit while disarmed, while kill-switched, and as a `viewer`.

## Accessibility notes
Per E33-D05 and `05-accessibility-standard.md`: fields labelled **with units**; the emulation caveat is a paragraph, not a tooltip; the TWAP schedule is a real table; the chase peg source is a radio group (best bid / best ask / mid) plus a signed tick offset with the resulting price previewed in text; the OCO residual-risk warning is `role="note"` and always visible; running states announce refreshes politely at most once every 5 s; modal focus trap and restoration; ≥ 24 px targets; contrast AA. axe-core green on SCR-066..069.

## Performance notes
Modal open < 100 ms. Progress rendered from the `orders` topic at ≤ 2 Hz (SCR-066/SCR-070 performance notes). No polling.

## Observability
Analytics `algo.twap_previewed`, `algo.iceberg_previewed`; audit events are emitted server-side on creation (`algo.*_created`) — the client must not be the audit source. Metric `web_algo_builder_open_total{kind}`.

## Definition of Done
- [ ] Every Gherkin scenario covered by an automated test naming it.
- [ ] Coverage ≥ 80 % frontend; CI gate green.
- [ ] Storybook stories published for all builder states and CMP-118 variants.
- [ ] axe-core green on SCR-066..069; manual screen-reader pass recorded; keyboard-only verified.
- [ ] Design QA against the E33-D06 redlines (E33-D07) with discrepancies fixed or filed.
- [ ] Security review comment; abuse-case checks executed.
- [ ] QA sign-off (E33-Q01/Q02).
- [ ] `14-screens-catalogue.md` updated if design changed during implementation.
- [ ] Demoed on demo environment.
- [ ] Feature flags recorded per kind (demo on, live off until R4).
- [ ] PRs merged via merge queue, each ≤ 400 LOC (one builder per PR).

## Dependencies
E33-T02 (the `AlgoSpec` create payload, control verbs and WS projection — interface-first, merged before this starts). E33-D06 (design handoff Done ≥ 2 sprints prior). E30 (order ticket shell, arm/lock, confirm policy, CMP-115 selector). E32 (the bracket half of SCR-069 and the native-SL notice content).

## Branch
`feat/e33-algo-builders`.

## References
""" + REFS_COMMON,
)

# ---------------------------------------------------------------- S06 monitor
add(
    key="E33-S06",
    kind="Story",
    title="Build the algo monitor panel SCR-070 with orphan adoption and bulk controls",
    labels=["type/feature", "area/oms-execution", "priority/p0", "a11y", "design-qa", "perf", "security"],
    component="web",
    phase=PH,
    sprint="Sprint 18",
    priority="P0 Critical",
    perspective="Development",
    risk="R11 Alert reliability",
    estimate=3,
    parent="E33",
    blocked_by=["E33-T02", "E33-D06"],
    milestone=MS,
    body="""## Context
**US-ALGO-010 — Algorithm control panel (Must):** *"As a trader, I want one panel showing every running emulated algorithm, so that nothing runs invisibly."* This is the story that makes the whole epic safe to ship: four server-side strategies that survive browser closure are only acceptable if there is one authoritative place that shows them all and can stop them.

The NFR is explicit: the panel reflects **server** state, not client memory, and reconciliation runs at least every 30 s.

## Scope / Deliverables
- **SCR-070 Algo monitor panel**, rendered as a standalone panel and as the **Algos** tab of **SCR-063** (Positions & orders panel).
- Row content per `14-screens-catalogue.md` SCR-070: id, type, symbol, account, progress (type-specific: TWAP slices, chase repricings, iceberg slices, OCO leg state), filled/remaining, average price, next-action countdown, and controls (pause, resume, cancel, cancel-and-flatten).
- Type-specific progress metric per kind — a TWAP shows "6 of 10 slices, 60 %", a chase shows "repriced 7×, 3 ticks from arrival, 12 of 500 repricings used", an iceberg shows slices done/remaining, an OCO shows its leg states.
- States: running · paused · **degraded** (backend reconnecting — a `role="status"` banner explaining that algos are suspended and native stops still protect) · completed · failed with reason · empty state.
- Bulk actions: **pause all** and **cancel all** with a confirmation restating the count; results reported **per item** (US-ALGO-010 scenario 2), handling the "some already terminal" case.
- **Orphan detection**: an exchange order belonging to no known run is listed as orphaned with **adopt** or **cancel** actions, wired to `POST /algos/orphans/{orderId}/adopt|cancel` (E33-T02).
- Data: WS `orders` topic (`algo_run` records, coalesced 2 Hz) plus `GET /api/v1/algos` on mount and on reconnect; a visible "last reconciled" timestamp so staleness is never invisible.
- Components: CMP-023 Progress Bar, CMP-049 Table, CMP-055 FilterBar (account / symbol / kind / status), CMP-118 AlgoProgressCard, CMP-123 FlattenAllButton, CMP-227 EstimatedBadge.
- Countdown timers driven by **one shared ticker**, not one per row.

## Out of scope
The builder modals (E33-S05). Positions/orders/fills/groups tabs of SCR-063 (E29). Risk dashboard SCR-071 (E39). Strategy behaviour (S01–S04).

## Acceptance criteria
```gherkin
Scenario: Panel lists everything
  Given an active OCO, iceberg, TWAP and chase across two accounts
  Then every one is listed with its account, symbol, type-specific progress, next action time
  and a cancel control, and the list reflects server state with a visible last-reconciled time

Scenario: Cancel all algorithms
  When I choose cancel all and confirm the restated count
  Then every emulated algorithm stops, working orders are handled per each algorithm's
  cancellation policy, and results are reported per item including any that were already terminal

Scenario: Orphan detection
  Given an exchange order that belongs to no known algorithm
  Then it is listed as orphaned with an adopt or cancel action, and adopting it associates it
  with the correct run rather than creating a duplicate

Scenario: Degraded state (failure)
  Given the backend websocket disconnects
  Then a status banner explains that algos are suspended while the backend reconnects and that
  native stops still protect, the rows are marked stale, and controls that cannot be honoured
  are disabled rather than silently failing

Scenario: Halted by risk control (edge)
  Given the kill-switch fires while algos run
  Then every affected row shows "halted by risk control" with its reason, and resuming requires
  an explicit re-arm rather than a plain resume

Scenario: Density (edge)
  Given 100 running algorithms
  Then the grid virtualises, stays under 3 ms scripting per frame, and countdowns are driven by
  a single shared ticker

Scenario: Keyboard and screen reader
  Given a keyboard-only or screen-reader user
  Then the panel is a table navigable by keyboard, progress is available as text as well as a
  bar, the degraded banner is announced politely, and each control names its target algorithm
  and effect
```

## Technical notes / design
State is a normalised store keyed by `algo_id`, hydrated from `GET /api/v1/algos` and patched by `algo_run` WS records; a record older than the store's version is dropped. On reconnect the store is **re-hydrated from REST**, never merged optimistically — the server is authoritative (US-ALGO-010 NFR).

Reconciliation freshness is surfaced: if no record or poll has arrived within 30 s the rows are marked stale, matching the backend's `oms.algo.reconcile_interval_s=30`.

Bulk actions call `POST /api/v1/algos/cancel-all` once and render its per-run result list; they never loop per row from the client.

## Test plan
- **Unit/component**: store hydration and patch ordering; stale detection at the 30 s boundary; per-kind progress formatting; bulk-result rendering including mixed success/terminal; orphan row actions; disabled-control logic in the degraded state.
- **Storybook**: running / paused / degraded / completed / failed / halted / orphan / empty rows; 100-row density story; light/dark, both densities; visual regression.
- **Integration**: mocked WS + REST, including a disconnect/reconnect cycle asserting REST re-hydration.
- **E2E (Playwright, web + Electron)**: start a TWAP and a chase on demo, assert both appear with correct progress, cancel all and assert per-item results and that the exchange orders are gone.
- **Perf**: 100 running algos — scripting < 3 ms per frame, updates coalesced at 2 Hz, one ticker instance asserted.
- **A11y**: axe-core; keyboard-only pass; screen-reader pass on the degraded banner and control labels.
- Coverage ≥ 80 % frontend.

## Security notes
Mutating controls → `security`-labelled. RBAC: a `manager` sees and controls only runs on accounts they have access to; a `viewer` sees the panel read-only with controls absent — and the server enforces both regardless of the UI (E33-T02). Orphan **adopt** is the sensitive verb: adopting an order into a run changes what the supervisor will do with it, so it is audited with actor and order id and is owner/manager-only. Manual abuse-case check: attempt cancel-all as a viewer and as a manager scoped to a different account.

## Accessibility notes
Per SCR-070 and `05-accessibility-standard.md`: the monitor is a real `<table>`; progress is text as well as a bar ("60 %, 6 of 10 slices"); the degraded banner is `role="status"`; every control button names its target algo and effect ("Cancel TWAP a_12 on BTCUSDT, Main"); bulk confirmations restate the count; focus order follows visual order; ≥ 24 px targets; no colour-only status encoding (glyph + text). axe-core green.

## Performance notes
< 3 ms scripting per frame with 100 running algos; WS updates coalesced to 2 Hz; virtualised grid; one shared countdown ticker (SCR-070 performance note).

## Observability
Audit is server-side (`algo.created|paused|resumed|cancelled|completed|failed`, `algo.orphan_adopted`); the client emits analytics `algo.monitor_opened`, `algo.monitor_bulk_action{action,count}`. Metric `web_algo_monitor_frame_ms`.

## Definition of Done
- [ ] Every Gherkin scenario covered by an automated test naming it.
- [ ] Coverage ≥ 80 % frontend; CI gate green.
- [ ] Storybook stories incl. the 100-row density story; visual regression green.
- [ ] axe-core green; manual screen-reader pass recorded; keyboard-only verified.
- [ ] Perf benchmark recorded against the 3 ms budget.
- [ ] Design QA against E33-D06 redlines (E33-D07).
- [ ] Security review comment; RBAC abuse cases executed.
- [ ] QA sign-off (E33-Q02/Q06).
- [ ] `14-screens-catalogue.md` SCR-070 updated if design changed during implementation.
- [ ] Demoed on demo environment.
- [ ] PR(s) merged via merge queue, each ≤ 400 LOC.

## Dependencies
E33-T02 (`GET /algos`, control verbs, orphan verbs, WS projection). E33-D06 (design handoff Done ≥ 2 sprints prior). E29 (SCR-063 host panel and its tab shell). E39 (kill-switch state surfaced as `halt_reason`).

## Branch
`feat/e33-algo-monitor`.

## References
""" + REFS_COMMON,
)

# ---------------------------------------------------------------- T03 docs
add(
    key="E33-T03",
    kind="Chore",
    title="Write ADR-0016 and reconcile plan docs with the shipped emulated algos",
    labels=["type/chore", "area/oms-execution", "priority/p2", "type/docs"],
    component="docs",
    phase=PH,
    sprint="Sprint 18",
    priority="P2 Medium",
    perspective="Architecture",
    risk="None",
    estimate=1,
    parent="E33",
    blocked_by=["E33-S06", "E33-S04"],
    milestone=MS,
    body="""## Context
`02-definition-of-ready-done.md` §2.2 requires that the plan docs reflect **final shipped behaviour**, not the original proposal, and §5.2 requires a spike's decision to be recorded as an ADR. E33-K01 chose the persistence seam, scheduler shape and orphan-adoption strategy; S01–S06 will have diverged from `24-internal-schemas.md` §10 in small ways (parameter defaults, error classification, control-verb semantics). This chore closes both gaps in one pass so the next epic to touch M14 (E34 fan-out, E35 rules) reads the truth.

## Scope / Deliverables
- New **`docs/plan/27-adrs/ADR-0016-emulated-algo-supervisor.md`** following the existing ADR template: context (Bybit exposes no OCO/iceberg/TWAP/chase), decision (backend `AlgoSupervisor`, the chosen persistence seam, the persisted wall-clock scheduler, `order_link_id`-based orphan adoption, the one-live-order DB invariant for chase), alternatives considered (browser-resident algos, outbox relay, per-run asyncio tasks), consequences (what a backend outage means for a running algo, and why `on_disconnect="freeze"` plus the native SL is the accepted answer), and links to E33-K01's measurements.
- Update `docs/plan/24-internal-schemas.md` §10.1–§10.5 where implementation diverged (defaults, error codes, status names, control-verb semantics).
- Update `docs/plan/21-database-schema.md` with the shipped `algo_runs` / `algo_slices` DDL, the `ux_algo_one_live_child` partial unique index, retention/sizing rows, and the `algo.*` feature-flag defaults.
- Update `docs/plan/22-api-openapi.yaml` and `docs/plan/23-ws-protocol.md` if the algo control surface or the `algo_run` record changed after E33-T02's review.
- Update `docs/plan/14-screens-catalogue.md` SCR-066..070 and `docs/plan/15-component-catalogue.md` CMP-118 where the shipped UI differs from the handoff.
- Update `docs/plan/32-risk-register.md` with the residual risk "a backend outage suspends emulated algos; native stops remain the only live protection" and its accepted mitigation.
- Changelog fragment describing the four emulated algos and the monitor panel as user-facing additions (`07-release-and-prr.md` §3).

## Out of scope
New behaviour of any kind. Runbooks for the algo supervisor (E48 docs & runbooks, R5).

## Acceptance criteria
- ADR-0016 exists, is reviewed by the Architect, and is linked from `27-adrs/README.md` and from `24-internal-schemas.md` §10.
- A diff review confirms every divergence found during S01–S06 code review is reflected in the plan docs; a reviewer can read §10 and the schema doc and predict the shipped behaviour exactly.
- `21-database-schema.md` contains the shipped DDL verbatim (copy-checked against the migration).
- The risk register entry exists with an owner and an accepted-risk sign-off.
- Changelog fragment present and rendered by the release tooling.

## Technical notes / design
Do this as one PR at the end of the train so it captures late changes; use the code as the source of truth and the docs as the target, never the reverse.

## Test plan
Docs-only. The contract-assertion harness in `22-api-openapi.yaml` (enum parity, schema-block validity) must stay green, which is the automated check that the doc edits are not merely prose.

## Security notes
No code change. The ADR must state the security-relevant consequences explicitly: the supervisor is the only creator of `algo_child` orders, algo params are account-scoped data, and a running algo's authorisation is re-checked per child. Security engineer reviews the ADR's consequences section.

## Accessibility notes
N/A — documentation.

## Performance notes
N/A. The measured numbers from E33-K01, T01, S03 and S04 are quoted in the ADR so they are not re-derived later.

## Observability
The ADR lists the metric and audit-event names shipped, so `docs/plan/…` and Grafana dashboards cannot drift apart silently.

## Definition of Done
- [ ] ADR-0016 merged and indexed.
- [ ] `24-internal-schemas.md`, `21-database-schema.md`, `22-api-openapi.yaml`, `23-ws-protocol.md`, `14-screens-catalogue.md`, `15-component-catalogue.md` updated as needed.
- [ ] `32-risk-register.md` updated with sign-off.
- [ ] Changelog fragment added.
- [ ] Contract-assertion CI green.
- [ ] No demo required (documentation only — stated explicitly per §7.2 of the DoD).
- [ ] PR merged via merge queue.

## Dependencies
E33-S04 and E33-S06 must be complete so the docs describe shipped behaviour; E33-K01 supplies the ADR's evidence.

## Branch
`chore/e33-docs-adr`.

## References
""" + REFS_COMMON,
)
