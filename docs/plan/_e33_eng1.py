# -*- coding: utf-8 -*-
"""E33 engineering tickets: spike, framework tasks, strategy stories, UI stories, docs chore."""

from _e33_epic import REFS_COMMON, MS, PH

BASE_LABELS = ["type/feature", "area/oms-execution"]

TICKETS = []


def add(**kw):
    TICKETS.append(kw)


# ---------------------------------------------------------------- K01
add(
    key="E33-K01",
    kind="Spike",
    title="Prove the emulated-algo scheduler, crash-resume seam and orphan adoption",
    labels=["type/spike", "area/oms-execution", "priority/p1", "perf"],
    component="api",
    phase=PH,
    sprint="Sprint 17",
    priority="P1 High",
    perspective="Architecture",
    risk="R11 Alert reliability",
    estimate=2,
    parent="E33",
    blocked_by=["E29"],
    milestone=MS,
    body="""## Context
`docs/plan/24-internal-schemas.md` §10.1 states the universal rule that "every algo persists its state transactionally with each child submission, so a restart resumes exactly where it stopped", and US-ALGO-005/006/007 each require resumption **within 5 seconds of process start**. That is an architectural claim nobody has measured yet, and three design choices hang on it:

1. **Where the seam is.** A child submission is a Postgres write plus a Bybit REST call. Whichever order they occur in, a crash between them leaves ambiguity. The candidate patterns are *intent-first* (persist a `pending_submit` slice row with its deterministic `order_link_id`, then submit, then mark `submitted`) versus *outbox* (write to the existing `outbox` table, `21-database-schema.md` §, and let a relay submit).
2. **How the schedule survives.** TWAP slice times must be wall-clock rows, not in-memory timers (US-ALGO-006 NFR). The question is whether one supervisor task polls a `next_action_at` index, or each run holds an asyncio task rehydrated at boot.
3. **Whether orphan adoption is deterministic.** `24-internal-schemas.md` §8.x gives `order_link_id` a structured layout (group segment + `seq2` + 2-char suffix, `ac` for algo child). Adoption must recover a resting child from `GET /v5/order/realtime` by that id alone, with no local state.

This spike answers all three with a throwaway prototype against the demo environment and the recorded-fixture harness, and records the decision in ADR-0016 (written up in E33-T03).

## Scope / Deliverables
- Throwaway prototype on `spike/e33-algo-resume` implementing a two-slice TWAP against **demo** using (a) the intent-first seam and (b) the `outbox` relay seam.
- A kill harness that `SIGKILL`s the process at each of four seams: before persist, after persist/before submit, after submit/before ack persist, after ack persist.
- Measurement of **resume latency** (process start → first correct action) for 1, 10 and 100 concurrent runs, and of scheduler drift for a 100-slice TWAP.
- An orphan-adoption probe: place a child, wipe local rows, restart, and recover it from `GET /v5/order/realtime` by `order_link_id` prefix.
- A comparison table + recommendation appended to the spike ticket and carried into ADR-0016.
- Follow-up tickets filed if the spike surfaces work not already covered by E33-T01.

## Out of scope
Production code (this is explicitly a throwaway spike per `02-definition-of-ready-done.md` §5.1). Strategy logic beyond a minimal TWAP. Any live-environment use.

## Acceptance criteria
```gherkin
Scenario: Seam decision made
  Given both candidate seams are prototyped and killed at all four points
  Then a comparison table records duplicate-child count, lost-child count and resume latency per seam,
  and one seam is recommended with the reason stated

Scenario: Resume budget measured
  Given 100 concurrent prototype runs and a hard process kill
  When the process restarts
  Then the time from process start to the first correct action per run is recorded at p50/p95/max
  and compared against the 5-second requirement of US-ALGO-005/006/007

Scenario: Orphan adoption proven or disproven (edge)
  Given a child order resting on demo and all local algo rows deleted
  When the prototype restarts and queries GET /v5/order/realtime
  Then it either re-associates that child by order_link_id alone, or the spike records precisely
  why it cannot and what additional persisted state E33-T01 must keep

Scenario: Scheduler drift bounded (edge)
  Given a 100-slice TWAP over 10 minutes and a deliberately suspended event loop
  Then the recorded per-slice drift and the catch-up behaviour are measured, and the finding
  states whether a polled next_action_at index or per-run tasks is required
```

## Technical notes / design
Timebox **3 working days**, agreed with the Architect. Decision criteria fixed in advance: if the intent-first seam produces zero duplicate children across all four kill points **and** p95 resume < 2 s at 100 runs, it is chosen outright and the outbox relay is not pursued; if it duplicates at any seam, the outbox relay is chosen even at a latency cost, because a duplicate child is an unintended position and a slow resume is only a delay.

`order_link_id` layout is already normative (`24-internal-schemas.md` §8.x): the prototype must use it as-is, not invent one.

## Test plan
Prototype-level only: the kill harness is the test. Fixtures — the recorded Bybit partial-fill and rejection fixtures from E29's harness plus a live demo account. No coverage gate applies to spike code.

## Security notes
The prototype runs against **demo keys only**; the spike branch must not contain credentials (secrets scanning applies to the branch like any other). No production data. The spike must note any finding that affects the naked-position guarantee.

## Accessibility notes
N/A — no UI.

## Performance notes
Targets to measure, not yet to meet: resume p95 < 2 s at 100 concurrent runs; scheduler drift < 250 ms per slice at 100 slices; submission path staying inside budget #4 (submit → ack p95 < 300 ms, `06-performance-and-load-standard.md` §5.2).

## Observability
The prototype emits `oms_algo_resume_seconds` and `oms_algo_child_orders_total{kind}` so the same metric names are proven before E33-T01 adopts them.

## Definition of Done
- [ ] All four questions answered with recorded numbers and a comparison table.
- [ ] **ADR-0016** drafted with the chosen seam, scheduler shape and adoption strategy (finalised in E33-T03).
- [ ] Follow-up tickets filed for anything E33-T01 does not already cover.
- [ ] Findings presented at Sprint Review / architecture review.
- [ ] `docs/plan/32-risk-register.md` updated if a new risk surfaced (expected candidates: rate-budget exhaustion on resume storms).
- [ ] Spike branch left unmerged and marked throwaway.

## Dependencies
E29 supplies the OMS state machine, the `order_link_id` scheme and the demo adapter the prototype submits through.

## Branch
`spike/e33-algo-resume`. No PR to `main`.

## References
""" + REFS_COMMON,
)

# ---------------------------------------------------------------- T01
add(
    key="E33-T01",
    kind="Task",
    title="Build the AlgoSupervisor framework: state store, scheduler, resume, adoption",
    labels=["type/feature", "area/oms-execution", "priority/p0", "security", "perf"],
    component="api",
    phase=PH,
    sprint="Sprint 17",
    priority="P0 Critical",
    perspective="Development",
    risk="R11 Alert reliability",
    estimate=5,
    parent="E33",
    blocked_by=["E33-K01", "E33-X01", "E32", "E39"],
    milestone=MS,
    body="""## Context
Every emulated strategy in this epic and the scaled/bracket strategies in E32 are small state machines with the *same* hard parts: transactional persistence, wall-clock scheduling, crash resume, orphan adoption, rate-budget accounting, kill-switch obedience and audit. `docs/plan/24-internal-schemas.md` §10.1 specifies that common model once (`AlgoSpec`, `AlgoState`, the `pending → running → paused → completing → completed | cancelled | failed` state diagram and five universal rules). This task implements it once, so that S01–S04 are each a small strategy plug-in rather than four copies of the same risky machinery.

The seam, scheduler shape and adoption strategy are fixed by **E33-K01 / ADR-0016** — implement that decision, do not re-litigate it.

## Scope / Deliverables
- New package `packages/oms/algo/` inside module **M14**:
  - `models.py` — `AlgoSpec`, `AlgoState` and the per-strategy params models exactly as in `24-internal-schemas.md` §10.1–§10.5 (`OcoParams`, `IcebergParams`, `TwapParams`, `ChaseParams`), re-exported for the API layer.
  - `supervisor.py` — `AlgoSupervisor` with `start(algo_spec) -> algo_id`, `pause(algo_id)`, `resume(algo_id)`, `cancel(algo_id, flatten: bool)`, `adopt(order_id, algo_id)`, plus the strategy registry that E32 also registers `scaled`/`bracket` into.
  - `strategy.py` — the `AlgoStrategy` Protocol: `plan_next(state, snapshot) -> Action | None`, `on_execution(state, execution)`, `on_child_terminal(state, order)`, `on_halt(state, reason)`.
  - `store.py` — transactional state persistence and the resume query.
  - `scheduler.py` — the persisted wall-clock scheduler driven by `next_action_at`.
  - `guards.py` — pre-flight and per-child guards (see below).
- Postgres migration adding:
  - `algo_runs` (`id uuid pk`, `kind algo_kind`, `account_id`, `symbol`, `side`, `total_qty`, `params jsonb`, `status`, `filled_qty`, `remaining_qty`, `slices_done`, `slices_total`, `avg_fill_price`, `started_at`, `next_action_at`, `last_error`, `failure_count`, `on_disconnect`, `created_by`, `rule_id`, `halt_reason`, timestamps) with `CREATE INDEX ix_algo_runs_due ON algo_runs (next_action_at) WHERE status IN ('running','pending')`.
  - `algo_slices` (`id`, `algo_run_id fk`, `seq int`, `order_link_id text unique`, `order_id uuid null fk orders(id)`, `planned_at`, `planned_qty`, `planned_price`, `state`, `error_code`, `error_msg`) with `UNIQUE (algo_run_id, seq)`.
  - The **chase invariant** as a DB constraint: `CREATE UNIQUE INDEX ux_algo_one_live_child ON algo_slices (algo_run_id) WHERE state = 'live'` (US-ALGO-007 NFR: "enforced by a database-level unique constraint on (algorithm id, live order)").
  - Existing `orders` columns are reused, not duplicated: `algo`, `algo_params`, `parent_order_id`, `oco_group_ref` (`21-database-schema.md` §3.3.4).
- The five universal rules of §10.1 implemented in the framework: transactional persist-per-child; `on_disconnect="freeze"` default; first-fill native-SL attach delegated to E32/M17 (**never bypassed**); child `order_link_id` derived from the parent group segment with incremented `seq2` and the `ac` suffix; `origin="algo_child"` set so rules cannot manage children.
- Resume-on-boot: rehydrate every non-terminal run, adopt resting children by `order_link_id`, recompute `filled_qty` from `executions` (never from the local accumulator), and reach the first correct action within 5 s.
- Guards: kill-switch and risk-lockout checks (E39) before every child submission; rate-budget token acquisition from the per-account bucket with the protective reserve untouched (`24-internal-schemas.md` §8); `max_children` (450) and `max_duration_ms` caps; `cancel_on_position_flat`.
- Metrics/audit plumbing consumed by all strategies (see Observability).

## Out of scope
The four strategy implementations themselves (S01–S04). API endpoints and WS projection (T02). UI (S05, S06). Scaled/bracket strategies (E32). Group-level algos (E34).

## Acceptance criteria
```gherkin
Scenario: A strategy plug-in runs end to end
  Given a two-action test strategy registered in the supervisor
  When it is started against the demo adapter
  Then each action persists its slice row and its deterministic order_link_id in the same
  transaction as the submission intent, and the run reaches "completed"

Scenario: Resume after a hard kill
  Given 100 runs of the test strategy across all four kill seams
  When the process is SIGKILLed and restarted
  Then every run resumes from Postgres, no child order is duplicated, filled quantities are
  recomputed from the executions table, and the first correct action occurs within 5 seconds
  of process start (p95)

Scenario: Orphan adoption
  Given a resting child whose algo_slices row is missing
  When the supervisor boots and reconciles against the exchange
  Then the child is adopted by order_link_id into the correct run rather than duplicated,
  or, if no run matches, it is reported as an orphan for the monitor panel

Scenario: Kill-switch blocks new children (failure)
  Given the kill-switch is engaged
  When any strategy requests a child submission
  Then the guard refuses it, the run transitions to "halted by risk control" with the reason,
  an audit event is written, and no request reaches the exchange

Scenario: Rate budget exhausted (edge)
  Given the account's order token bucket is empty
  Then the supervisor pauses the run rather than queueing stale actions, the protective reserve
  is left untouched so a stop-loss or flatten can still get a token, and resumption is automatic
  when tokens return

Scenario: Child cap (edge)
  Given a run that would exceed max_children (450)
  Then the run stops issuing children, ends in "completed" with remaining quantity reported,
  and never approaches Bybit's 500 active-orders-per-symbol limit (error 110020)
```

## Technical notes / design
State machine exactly as the `stateDiagram-v2` in `24-internal-schemas.md` §10.1. `failure_count > 3` → `failed`. Persist-then-submit ordering follows ADR-0016.

`AlgoStrategy` is a `Protocol`, so a strategy is pure planning logic: it reads `AlgoState` plus a `MetricSnapshot`/book snapshot and returns an `Action` (`Submit`, `Amend`, `Cancel`, `Sleep(until)`, `Finish(status)`); the supervisor owns every side effect. This is what makes strategies unit-testable without an exchange.

Error-code mapping reuses `24-internal-schemas.md` §8 table: `110001` order-not-found during an amend race is *benign*; `110017` reduce-only rejection is the self-limiting double-fill guard; `110020` is the order cap; `10018` is rate limiting and must back off with jitter.

Config keys: `oms.algo.max_children=450`, `oms.algo.max_failures=3`, `oms.algo.resume_deadline_ms=5000`, `oms.algo.reconcile_interval_s=30`, `oms.algo.default_on_disconnect=freeze`.

## Test plan
- **Unit** (≥ 90 % on `packages/oms/algo`): state transitions for every edge of the §10.1 diagram; `order_link_id` derivation (group segment, `seq2` increment, `ac` suffix, uniqueness); slice-row transactional semantics; guard refusal for kill-switch, lockout, empty bucket, child cap, duration cap; `filled_qty` recomputation from executions including duplicate execution delivery; adoption matching and non-matching.
- **Contract**: `AlgoSpec` params models round-trip against the `22-api-openapi.yaml` `AlgoSpec` schema (enum parity for `AlgoKind`, including `scaled` and `bracket` owned by E32).
- **Integration**: recorded Bybit fixtures — partial fill, rejection, `10018`, `110017`, `110020`, WS disconnect mid-run.
- **Migration**: forward/backward migration test; the `ux_algo_one_live_child` index rejects a second live slice.
- **Chaos**: the E33-K01 kill harness promoted into CI as `tests/chaos/test_algo_resume.py`, four seams × four strategies (test strategy + the three shipping by the time it runs).
- **Perf**: resume of 100 runs, scheduler drift at 100 slices.

## Security notes
Threats (from E33-X01 / `04-security-program.md`): **Tampering** — a client-supplied `AlgoSpec` must be validated server-side against instrument filters and the account profile's caps, never trusted; **Elevation of privilege** — `start`/`cancel` require the caller to hold the account's trade permission, re-checked at the supervisor, not only at the route; **Denial of service / denial of wallet** — an unbounded algo is the epic's worst-case abuse, bounded by `max_children`, `max_duration_ms`, the token bucket and the protective reserve; **Repudiation** — every transition writes an `audit_log` row with actor, account, params and reason. Data classification: financial. Security review label required.

## Accessibility notes
N/A — backend only.

## Performance notes
Resume p95 < 2 s at 100 concurrent runs (5 s hard requirement). Scheduler drift < 250 ms per slice. Supervisor overhead on the submission path ≤ 10 ms so budget #4 (submit → ack p95 < 300 ms, `06-performance-and-load-standard.md` §5.2) is unaffected.

## Observability
Metrics `oms_algo_active{kind,status}`, `oms_emulated_algo_total{kind}`, `oms_algo_child_orders_total{kind}`, `oms_algo_resume_seconds`, `oms_algo_guard_refusals_total{reason}`, `oms_algo_scheduler_drift_ms`. Structured logs per transition with `algo_id`, `kind`, `account_id`, `seq`. Audit `algo.created|paused|resumed|cancelled|completed|failed` plus `algo.halted_by_risk_control{reason}`. Traces: run → child submission → execution.

## Definition of Done
- [ ] Acceptance criteria verified by the tests named above; chaos suite green in CI.
- [ ] Coverage ≥ 90 % on `packages/oms/algo`, package total ≥ 85 %.
- [ ] Migration reviewed by a code owner; `docs/plan/21-database-schema.md` updated with `algo_runs` / `algo_slices` and the unique partial index.
- [ ] `docs/plan/24-internal-schemas.md` §10.1 updated if the implementation diverged from the spec.
- [ ] ADR-0016 referenced; deviations from it recorded.
- [ ] Security engineer review comment; SAST/SCA clean or triaged.
- [ ] Perf benchmark recorded (resume, drift, submission overhead).
- [ ] PR(s) merged via merge queue, each ≤ 400 LOC.

## Dependencies
E33-K01 fixes the seam and scheduler shape. E33-X01 supplies the threat model whose controls the guards implement. E32 owns the native-SL attach this framework calls and the sibling strategies it hosts. E39 supplies the kill-switch and lockout checks. E29 supplies the OMS state machine, `order_link_id` scheme, execution stream and rate-limit buckets.

## Branch
`feat/e33-algo-supervisor`. Split: migration + models PR, then supervisor + scheduler PR, then guards + resume PR.

## References
""" + REFS_COMMON,
)

# ---------------------------------------------------------------- T02
add(
    key="E33-T02",
    kind="Task",
    title="Expose algo control API, WS projection, feature flags and audit events",
    labels=["type/feature", "area/oms-execution", "priority/p1", "security"],
    component="api",
    phase=PH,
    sprint="Sprint 17",
    priority="P1 High",
    perspective="Development",
    risk="R11 Alert reliability",
    estimate=3,
    parent="E33",
    blocked_by=["E33-T01"],
    milestone=MS,
    body="""## Context
`docs/plan/22-api-openapi.yaml` already carries `AlgoSpec` / `AlgoKind` on `POST /orders` (§`/orders`, schema `AlgoSpec` with `oco`, `iceberg`, `twap`, `chase`, `scaled`, `bracket` sub-objects), so *creating* an emulated algo needs no new endpoint. What does not exist yet is the control surface the UI needs: listing runs, pausing, resuming, cancelling (optionally with flatten) and adopting an orphan — plus the WS projection that makes SCR-070 reflect **server** state rather than client memory (US-ALGO-010 NFR).

Interface-first rule (`01-sdlc-and-branching.md` §10): this schema delta is drafted and reviewed **before** S05/S06 start, and it is what those stories are `blocked_by`.

## Scope / Deliverables
- OpenAPI delta in `docs/plan/22-api-openapi.yaml`:
  - `GET /algos` — list runs, filters `account_id`, `symbol`, `kind`, `status`, `include_orphans`; returns `AlgoRun` (mirrors `AlgoState` of `24-internal-schemas.md` §10.1 plus `kind`, `symbol`, `side`, `account_id`, `params`, `halt_reason`, `next_action_at`).
  - `GET /algos/{algoId}` — one run with its slice history.
  - `POST /algos/{algoId}/control` — body `{action: pause|resume|cancel|cancel_and_flatten, reason?}`; idempotent by `Idempotency-Key`.
  - `POST /algos/cancel-all` — body `{account_id?, kind?}`; returns a per-run result list so the UI can report "results per item" (US-ALGO-010 scenario 2).
  - `POST /algos/orphans/{orderId}/adopt` and `POST /algos/orphans/{orderId}/cancel`.
  - New error slugs registered in the shared catalogue: `algo_not_found`, `algo_terminal`, `algo_control_conflict`, `algo_flag_disabled`, `algo_orphan_unmatched`.
- WS projection: algo state is published on the existing private **`orders`** topic (SCR-070 "Data: WS `orders`"), coalesced to **2 Hz**, as an `algo_run` record carrying the same fields as `AlgoRun`; `23-ws-protocol.md` §13 updated with the record schema and its `algo_kind` enum parity assertion.
- Feature flags `algo.oco`, `algo.iceberg`, `algo.twap`, `algo.chase` seeded `false` in `feature_flags` (`21-database-schema.md` §, defaults per `docs/plan/21-database-schema.md` flag table) and enforced at the route: a disabled kind is refused with `algo_flag_disabled` **before** any exchange call.
- RBAC: `owner` full; `manager` limited to accounts granted via `user_account_access`; `viewer` read-only (`GET` only). Every mutating verb writes an `audit_log` row.
- Audit event emission for the full catalogue named in `14-screens-catalogue.md` SCR-066..070 (`algo.twap_created`, `algo.iceberg_slice_replaced`, `algo.oco_race_resolved`, `algo.chase_limit_reached`, …) wired from the supervisor's transition hooks.

## Out of scope
Strategy behaviour (S01–S04). UI (S05, S06). Creating algos (already `POST /orders`). Group-level algo control (E34).

## Acceptance criteria
```gherkin
Scenario: Control verbs work and are idempotent
  Given a running TWAP
  When pause is sent twice with the same Idempotency-Key
  Then the run is paused, the second call returns the same result, and exactly one audit row exists

Scenario: Terminal run refuses control (failure)
  Given a completed chase run
  When cancel is sent
  Then 409 with error slug algo_terminal is returned, no exchange request is made, and the
  attempt is logged

Scenario: Disabled feature flag (failure)
  Given the algo.iceberg flag is false
  When an iceberg AlgoSpec is posted to /orders
  Then it is refused with algo_flag_disabled before any exchange call and the refusal is audited

Scenario: RBAC (edge)
  Given a viewer and a manager without access to account A
  When either calls any mutating algo verb on a run belonging to account A
  Then 403 is returned, no state changes, and an audit row records the denied attempt

Scenario: WS projection reflects server state
  Given a TWAP progressing through slices
  Then algo_run records arrive on the orders topic at no more than 2 Hz with the current
  status, filled and remaining quantities, slices done/total and next action time

Scenario: Cancel-all reports per item (edge)
  Given five running algos of which one is already terminal
  When cancel-all is called
  Then the response lists a per-run outcome, four are cancelled, the terminal one reports
  algo_terminal, and the call itself succeeds
```

## Technical notes / design
`AlgoRun` is a projection of `algo_runs` + aggregated `algo_slices`; it must never be built from in-memory supervisor state, so that a second API replica answers identically. Cancellation semantics per strategy: `cancel` cancels working children per that strategy's policy; `cancel_and_flatten` additionally submits a reduce-only close through the normal OMS path (never a raw exchange call).

Contract tests assert enum parity for `AlgoKind` across OpenAPI, the Postgres `algo_kind` type and the WS `algo_kind` enum, using the existing `enum_parity_*` harness described in `22-api-openapi.yaml`'s contract-assertion block.

## Test plan
- **Unit**: projection building, control-verb state guards, flag enforcement, RBAC scoping, idempotency-key replay.
- **Contract**: OpenAPI schema validation of every new path; `enum_parity_algo_kind`; WS `algo_run` record validated against the §13 JSON Schema.
- **Integration**: control verbs against a live supervisor with the demo adapter; cancel-and-flatten produces exactly one reduce-only close.
- **E2E**: covered indirectly by S05/S06 suites.
- Coverage ≥ 85 % backend.

## Security notes
Every route is an order-affecting path → `security`-labelled by `02-definition-of-ready-done.md` §8. Threats: privilege escalation across accounts (mitigated by `user_account_access` scoping re-checked in the service layer), replay (idempotency keys), information disclosure (`params` may reveal strategy intent — restricted to users with access to the account), repudiation (audit rows on every verb). Abuse case for E33-X02: cancel-all used as a griefing tool by a manager against another manager's accounts.

## Accessibility notes
N/A — API only; the a11y obligations land on S05/S06.

## Performance notes
`GET /algos` p95 < 150 ms with 500 runs. WS projection coalesced to 2 Hz to keep SCR-070 inside its 3 ms-per-frame budget with 100 rows.

## Observability
Metrics `api_algo_control_total{action,result}`, `api_algo_list_seconds`. Audit events as listed in Scope. Logs carry `algo_id` and `account_id` on every verb.

## Definition of Done
- [ ] Acceptance criteria verified; contract tests green.
- [ ] `22-api-openapi.yaml` and `23-ws-protocol.md` updated and reviewed **before** S05/S06 begin (interface-first gate).
- [ ] Coverage ≥ 85 % backend on touched packages.
- [ ] Feature flags documented in `21-database-schema.md`'s flag table.
- [ ] Security engineer review comment; RBAC matrix test extended to the new routes.
- [ ] PR merged via merge queue.

## Dependencies
E33-T01 provides the supervisor and the tables this projects from. E29 supplies the RBAC-scoped order routes and the WS private-topic machinery. E39 supplies the kill-switch flag surfaced in `halt_reason`.

## Branch
`feat/e33-algo-control-api`.

## References
""" + REFS_COMMON,
)
