# -*- coding: utf-8 -*-
"""E33 — Emulated algos (OCO, iceberg, TWAP, chase): epic ticket."""

MS = "R3 Trading on demo"
PH = "P3 Drawing & Alerts"

REFS_COMMON = """- `docs/plan/11-user-stories.md` §18 ALGO (US-ALGO-002, 005, 006, 007, 010)
- `docs/plan/14-screens-catalogue.md` SCR-066 TWAP builder, SCR-067 Iceberg (emulated) builder, SCR-068 Chase-limit builder, SCR-069 Emulated OCO / bracket builder, SCR-070 Algo monitor panel, SCR-063 Positions & orders panel (Algos tab)
- `docs/plan/15-component-catalogue.md` CMP-118 AlgoProgressCard, CMP-227 EstimatedBadge, CMP-158 SafetyInvariantNotice, CMP-130 SlippageEstimateChip, CMP-023 Progress Bar, CMP-049 Table, CMP-055 FilterBar, CMP-123 FlattenAllButton, CMP-008 NumericStepperInput, CMP-100 PriceInput, CMP-101 QtyInput, CMP-043 Dialog, CMP-047 DatePicker / DateRangePicker, CMP-115 OrderTypeSelector, CMP-119 BracketEditor
- `docs/plan/18-traceability-matrix.md` §2.18 ALGO rows
- `docs/plan/22-api-openapi.yaml` `POST /orders`, `PATCH /orders/{orderId}`, `DELETE /orders/{orderId}`, `POST /orders/cancel-all`, `GET /orders`, `GET /orders/{orderId}/diagnostics`; schemas `AlgoSpec`, `AlgoKind`, `OrderIntent`
- `docs/plan/23-ws-protocol.md` private topics `orders`, `executions`, `positions`; `algo_kind` enum in the order frames (§13)
- `docs/plan/21-database-schema.md` `orders` (`algo`, `algo_params`, `parent_order_id`, `oco_group_ref`), `order_events`, `executions`, `positions`, `audit_log`, `feature_flags` (`algo.twap` / `algo.chase` / `algo.iceberg` / `algo.scaled` / `algo.oco`)
- `docs/plan/24-internal-schemas.md` §10 Emulated order algorithms (§10.1 common model, §10.2 OCO, §10.3 iceberg, §10.4 TWAP, §10.5 chase, §10.8 capability-driven selection), §8 OMS state machine, §8.5 reconciliation, §8.8 native-SL attach, §8 rate-limit token buckets
- `docs/plan/20-architecture.md` M14 OMS / `AlgoSupervisor`
- `docs/plan/27-adrs/ADR-0006-oms-state-machine.md`, `ADR-0008-trade-group-fanout.md`, `ADR-0012-testing-pyramid.md`, `ADR-0014-observability.md`
- `docs/plan/30-release-roadmap.md` §7.2 E33, §7.3 exit criteria 2, §7.4 R3 quality gates
- `docs/plan/03-testing-strategy.md`, `docs/plan/04-security-program.md`, `docs/plan/05-accessibility-standard.md`, `docs/plan/06-performance-and-load-standard.md` §5.2 budget #4"""

EPIC_BODY = """## Context
Bybit v5 exposes **no** OCO, iceberg (`displayQty`), TWAP or chase/peg order types through its public API (research digest 09 §2/§6, recorded in `docs/plan/24-internal-schemas.md` §10). Traders still need them, so CandleViewer emulates them in the backend `AlgoSupervisor` (module **M14**, `docs/plan/20-architecture.md` §OMS) — never in the browser: a browser-resident algo dies with the tab, and a dead algo holding a working order is a risk event.

This epic builds that supervisor and the four emulated strategies the roadmap names for R3 (`docs/plan/30-release-roadmap.md` §7.2 E33): **OCO**, **iceberg** (display-size slicing with randomisation), **TWAP** (duration, slice count, jitter) and **chase** (follow best bid/ask with a max-chase cap and a give-up condition) — plus the **algo monitor panel** so nothing ever runs invisibly. Every algo is crash-safe (state in Postgres, resumed on restart), disconnect-aware (`on_disconnect="freeze"` by default), subject to the kill-switch and risk lockouts (E39), and carries a visible **"emulated — not exchange-native"** badge (CMP-227 EstimatedBadge + CMP-158 SafetyInvariantNotice) everywhere it appears.

The scaled/ladder algo (`AlgoKind.scaled`), brackets (`bracket`) and trailing stops ship in **E32**; this epic does not re-implement them, but the supervisor framework it builds (E33-T01) is the one E32's strategies register into.

## Scope / Deliverables
**User stories (domain ALGO, `docs/plan/11-user-stories.md` §18):**
- **US-ALGO-002** Emulated OCO — *Must*
- **US-ALGO-005** Emulated iceberg — *Should*
- **US-ALGO-006** Emulated TWAP — *Should*
- **US-ALGO-007** Chase / pegged limit — *Should*
- **US-ALGO-010** Algorithm control panel — *Must*

(US-ALGO-001 brackets, -003 TP ladders, -004 scaled entries, -008 trailing stops and -009 DCA ladders belong to **E32**; they appear here only as the sibling strategies that share E33-T01's framework.)

**Screens:** SCR-066 TWAP builder · SCR-067 Iceberg (emulated) builder · SCR-068 Chase-limit builder · SCR-069 Emulated OCO / bracket builder (the OCO half; the bracket half is E32) · SCR-070 Algo monitor panel · SCR-063 Positions & orders panel (its **Algos** tab hosts SCR-070).

**Components:** CMP-118 AlgoProgressCard, CMP-227 EstimatedBadge, CMP-158 SafetyInvariantNotice, CMP-130 SlippageEstimateChip, CMP-023 Progress Bar, CMP-049 Table, CMP-055 FilterBar, CMP-123 FlattenAllButton, CMP-008 / CMP-100 / CMP-101 inputs, CMP-043 Dialog, CMP-047 DatePicker, CMP-115 OrderTypeSelector (its "Emulated" group).

**Backend:** `AlgoSupervisor` in M14 — `packages/oms/algo/` with `supervisor.py`, `strategies/{oco,iceberg,twap,chase}.py`, `store.py`, `scheduler.py`; a Postgres migration adding `algo_runs` and `algo_slices` next to the existing `orders.algo` / `orders.algo_params` / `orders.parent_order_id` / `orders.oco_group_ref` columns (`docs/plan/21-database-schema.md` §3.3); a wall-clock persisted scheduler; orphan adoption by `order_link_id`; feature flags `algo.oco`, `algo.iceberg`, `algo.twap`, `algo.chase`.

**API/WS:** `POST /api/v1/orders` with `algo: AlgoSpec` (already specified in `22-api-openapi.yaml`), `PATCH|DELETE /api/v1/orders/{orderId}`, `POST /api/v1/orders/cancel-all`, `GET /api/v1/orders`, `GET /api/v1/orders/{orderId}/diagnostics`; algo control verbs (pause / resume / cancel / cancel-and-flatten / adopt) added as an OpenAPI delta in E33-T02; WS `orders`, `executions`, `positions`.

## Out of scope
- Brackets, TP ladders, scaled/DCA ladders, trailing stops — **E32**.
- OMS core state machine, reconciliation loop, blotters — **E29**.
- Order ticket form, sizing, arm/lock, hotkeys — **E30**; chart/DOM direct manipulation — **E31**.
- Trade-group fan-out and the rate-limit governor — **E34**. This epic *consumes* the per-account token buckets of `24-internal-schemas.md` §8; in R3 an algo run targets exactly one account, and group-level algos are explicitly deferred.
- Rule-engine-authored algos — **E35** (`origin="algo_child"` is excluded from rule scopes by design, §10.1 rule 5).
- Android; a separate admin app; non-Bybit venues; non-USDT-perp instruments.

## Acceptance criteria
```gherkin
Scenario: Every emulated strategy is available and labelled
  Given the algo feature flags are enabled on demo
  When I open the order ticket's emulated order-type group
  Then OCO, iceberg, TWAP and chase are offered, each opening its builder (SCR-066..069),
  and each builder states in text that the strategy is emulated by CandleViewer, not by Bybit

Scenario: Nothing runs invisibly
  Given one OCO, one iceberg, one TWAP and one chase are running across two accounts
  When I open the algo monitor panel
  Then all four are listed with type-specific progress, next action time and controls,
  reflecting server state reconciled at least every 30 seconds

Scenario: Crash safety across every strategy (failure)
  Given each strategy is running and the backend process is killed at a persistence seam
  When the process restarts
  Then every run resumes from Postgres within 5 seconds, adopts its resting children by
  order_link_id instead of duplicating them, and reaches a correct terminal state

Scenario: Risk control halts everything (edge)
  Given the kill-switch is engaged or a daily-loss lockout fires
  Then every running algo halts, working children are handled per each strategy's policy,
  each run ends in "halted by risk control" with the reason recorded and audited,
  and no run ever auto-resumes without an explicit re-arm
```

## Technical notes / design
`AlgoSupervisor` is the only component allowed to create `orders` rows with `intent='algo_child'` and `origin='algo_child'`. Universal rules from `24-internal-schemas.md` §10.1 are implemented once in the framework, not per strategy: (1) state persisted transactionally with each child submission; (2) `on_disconnect="freeze"` by default; (3) an entry algo's first fill triggers the native-SL attach (§8.8) — algos never place unprotected exposure; (4) children inherit the parent's `order_link_id` group segment with an incremented `seq2` and the `ac` suffix; (5) algo children are never themselves rule-managed.

Strategy selection is capability-driven (`ExchangeCapabilities`, §10.8) — `supports_native_oco/iceberg/twap/chase` are all `False` for Bybit, and there is no `if exchange == "bybit"` outside the adapter package.

## Test plan
Per-strategy unit suites (≥90 % on `packages/oms/algo` by local policy), contract tests on the `AlgoSpec` schema and the algo control endpoints, integration tests against recorded Bybit fixtures (partial fill, rejection, `10018`, `110017`, `110020`, WS disconnect), chaos tests killing the process at each seam, a k6 rate-budget soak for chase/iceberg, Playwright E2E for each builder and the monitor panel, and an a11y audit of SCR-066..070. Details in E33-Q01..Q06.

## Security notes
`area/oms-execution` order-placing paths are always `security`-labelled (`02-definition-of-ready-done.md` §8). The epic's STRIDE model is E33-X01; the headline threats are (a) a runaway algo as a denial-of-wallet / self-inflicted-loss vector, (b) rate-budget exhaustion starving protective orders, (c) privilege escalation — a `viewer` or a manager without access to the account starting or cancelling an algo, (d) repudiation — every create/pause/resume/cancel must be audited with actor and parameters. Data classification: financial.

## Accessibility notes
SCR-066..070 are net-new UI and must meet WCAG 2.2 AA: progress exposed as text as well as bars, schedule previews as tables, emulation caveats as paragraphs (never tooltips), the degraded banner as `role="status"`, and every control naming its target algo and effect. Audited in E33-Q05.

## Performance notes
Order submit → ack p95 < 300 ms on demo (budget #4). OCO fill → opposing-leg cancel request ≤ 300 ms p95 (SCR-069). Chase reprice interval ≥ 200 ms with debounced targets. Monitor panel < 3 ms scripting per frame with 100 running algos, updates coalesced to 2 Hz (SCR-070).

## Observability
Audit events `algo.oco_created|leg_filled|leg_cancelled|race_resolved|residual_detected|cancelled|completed|failed`, `algo.iceberg_created|paused|resumed|cancelled|completed|failed|slice_replaced`, `algo.twap_created|paused|resumed|cancelled|completed|slice_failed`, `algo.chase_created|repriced|limit_reached|fell_back_to_market|cancelled|completed|failed`. Metrics `oms_emulated_algo_total{kind}`, `oms_algo_active{kind}`, `oms_algo_child_orders_total{kind}`, `oms_algo_resume_seconds`, `oms_oco_race_resolution_ms`, `oms_chase_repricings_total`. Traces span algo run → child submission → execution.

## Definition of Done (epic exit criteria)
1. All Gherkin scenarios of US-ALGO-002/005/006/007/010 pass in CI, including every failure and edge scenario written there (cancel-rejected-because-already-filled, crash between fill and cancel, duplicate fill delivery, manual flatten, slice rejected, dust remainder, kill-switch mid-algo, clock drift / missed windows, amend races a fill, flapping best price, orphan adoption after crash).
2. **Crash safety proven**: the chaos suite kills the backend at each persistence seam of each strategy; every algo resumes from Postgres and reaches a correct terminal state within 5 s of process start, with zero duplicated children.
3. **Safety invariant**: no algo path can open a position without a native exchange-side SL (R3 exit criterion 2); the algo path is one of the enumerated paths in that suite and has zero escapes.
4. **Kill-switch / lockout**: engaging either halts every running algo and lands each run in "halted by risk control" — audited, alerted, never auto-resumed.
5. **Chase invariant**: at most one live order per chase run, asserted before every placement and enforced by a DB unique partial index.
6. **OCO race**: fill → opposing-leg cancel/amend issued ≤ 300 ms p95; residual double fill detected from executions and corrected reduce-only with a high-severity incident.
7. **Monitor panel**: every running algo visible with type-specific progress, reconciled at least every 30 s, orphans listed with adopt/cancel, < 3 ms scripting per frame with 100 rows.
8. Design QA (E33-D07), a11y audit (E33-Q05), QA sign-off (E33-Q06) and Security sign-off (E33-X03) recorded; coverage ≥ 85 % on `packages/oms` (≥ 90 % on `packages/oms/algo`), ≥ 80 % frontend; zero open P0/P1; demoed on demo environment and accepted by the Owner.

## Story list
| Key | Kind | Title | Pts | Sprint |
|---|---|---|---|---|
| E33-K01 | Spike | Emulated-algo scheduler & crash-resume seam spike | 2 | 17 |
| E33-T01 | Task | `AlgoSupervisor` framework: state store, scheduler, resume, orphan adoption | 5 | 17 |
| E33-T02 | Task | Algo control API, WS projection, feature flags and audit events | 3 | 17 |
| E33-S01 | Story | Emulated OCO (US-ALGO-002) | 5 | 17 |
| E33-S02 | Story | Emulated iceberg (US-ALGO-005) | 5 | 17 |
| E33-S03 | Story | Emulated TWAP (US-ALGO-006) | 5 | 18 |
| E33-S04 | Story | Chase / pegged limit (US-ALGO-007) | 5 | 18 |
| E33-S05 | Story | Algo builder modals SCR-066..069 | 3 | 18 |
| E33-S06 | Story | Algo monitor panel SCR-070 (US-ALGO-010) | 3 | 18 |
| E33-T03 | Chore | Reconcile plan docs and write ADR-0016 emulated-algo supervisor | 1 | 18 |

Engineering total **37 pts** (budget 34 ± 15 %). Design (E33-D01..D07, 22 pts), QA (E33-Q01..Q06, 22 pts) and Security (E33-X01..X03, 8 pts) carry their own points and are tracked against the design/QA/security capacity lines, not the engineering budget.

## Risks
- **R11 Alert reliability** — an emulated algo is a promise the exchange never made; if the backend is down, slices stop. Mitigated by `on_disconnect="freeze"`, the always-present native SL, the degraded banner on SCR-070 and a residual-risk note in every builder.
- **R3 Real-time cost / rate limits** — chase repricing and iceberg refills are the highest request-rate paths in the product. Mitigated by `reprice_interval_ms ≥ 200`, debounced targets, per-account token buckets with a protective reserve (`24-internal-schemas.md` §8), and a projected-requests/min figure shown *before* submit.
- **R7 Data accuracy** — computing fills from intent rather than executions causes double positions. Mitigated by "executions are authoritative" in every strategy.
- **R5 Scope** — group-level algos and rule-driven algos are explicitly deferred to E34/E35.

## Dependencies
`blocked_by`: **E32** (bracket/native-SL machinery and the `AlgoKind` sibling strategies this framework must host), **E29** (OMS state machine, `order_link_id` scheme, reconciliation loop, WS order/execution stream), **E39** (kill-switch and risk lockouts that every algo must obey). Consumes E27 accounts/keys and E28 profiles transitively.

## Branch
`feat/e33-emulated-algos-<short>` per child ticket; PRs ≤ 400 LOC diff, one strategy per PR.

## References
""" + REFS_COMMON

EPIC = {
    "key": "E33",
    "kind": "Epic",
    "title": "Emulated algos (OCO, iceberg, TWAP, chase)",
    "labels": ["type/feature", "area/oms-execution", "priority/p1", "security", "qa", "design", "perf", "a11y"],
    "component": "api",
    "phase": PH,
    "sprint": "Sprint 17",
    "priority": "P1 High",
    "perspective": "Product",
    "risk": "R11 Alert reliability",
    "estimate": 37,
    "parent": None,
    "blocked_by": ["E32", "E29", "E39"],
    "milestone": MS,
    "body": EPIC_BODY,
}
