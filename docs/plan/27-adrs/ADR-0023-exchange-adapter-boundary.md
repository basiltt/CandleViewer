# ADR-0023 — Exchange-adapter boundary and the market-data trust contract

- Status: **accepted** — written after `E08-K01` (spike, merged) and `E08-X01` (STRIDE threat model,
  merged) so it records decisions actually made and tested rather than intentions. Per this ticket's
  "Agent-delivery adaptations", owner `approved` comment on issue #173 or owner merge of the PR
  substitutes for Architect countersignature; this ADR does not block on it.
- Date: 2026-09-29
- Deciders: Owner (`@basiltt`) — owner approval pending per the adaptation above.
- Consulted: `docs/plan/24-internal-schemas.md` §14 (exchange adapter interface), `docs/plan/20-architecture.md`
  §3.2 and P3, `docs/plan/23-ws-protocol.md` §6.1 / C3, `docs/plan/27-adrs/ADR-0021-book-depth-tier-policy.md`,
  `docs/plan/spikes/E08-K01.md`, `docs/plan/32-risk-register.md` R3, R9.
- Related: E08-T03 (bus, merged — the transport E08-K01 measured through), E08-K01 (depth-tier spike,
  merged), E08-X01 (STRIDE threat model, merged), E08-S05 (order-book reconstruction, consumes the
  invalidate-and-resync rule below), E08-X03 (P3 vocabulary-leak lint gate, enforces §3 below), E12/E17/
  E22/E24/E29 (downstream consumers of the trust contract in `docs/plan/25-market-data-trust-contract.md`).

## Context and problem statement

Nine downstream epics (E12, E17, E21, E22, E24, E25, E27, E29 and others) consume events that cross the
exchange-adapter boundary defined in `24-internal-schemas.md` §14. That section is the *implementation*
specification (protocols, DTOs, Bybit specifics); it does not record *why* the boundary is shaped the way
it is, nor does any single document tell a downstream developer how much to trust a given field on an
event. Left unrecorded, each downstream epic re-derives these rules from the ticket bodies and reviewers'
memories, and epics will derive them differently — which is exactly how a chart ends up rendering an
unconfirmed bar as closed, or a heuristic detector's output as a measured fact (`R9 Advice boundary`,
`docs/plan/32-risk-register.md`).

This ADR is deliberately written *after* the two tickets whose outputs it must cite with evidence rather
than intent: `E08-K01` (which measured the depth-tier/cadence tradeoff) and `E08-X01` (which threat-modelled
the boundary and produced the mitigations §3 and §5 below encode). It records the port/adapter split,
principle P3 and its enforcement, the invalidate-and-resync rule for the order book, the depth-tier
decision, environment separation, and arithmetic/timestamp conventions — the decisions a second exchange
adapter, or a downstream epic, needs and currently cannot get from one place.

## Decision

### D1 — Port/adapter split: `MarketDataPort`, `TradingPort` (declared-only in v1), `ExchangeCapabilities`

The adapter package exposes two `Protocol`s (`services/api/candleviewer/exchange/base.py`,
`24-internal-schemas.md` §14.1) and one capability record:

- **`MarketDataPort`** — read-only market data: instruments, trades, book, ticker, klines, liquidations,
  open interest, funding, risk limits, server time. Fully specified and consumed starting with E08's own
  tickets (`E08-S05` and siblings).
- **`TradingPort`** — order placement, amend/cancel, positions, executions, wallet, private stream.
  **Declared in the interface now, implemented by E29 (OMS)**, not E08. E08 ships the shape so E29 does not
  invent a competing one; E08 does not implement trading behaviour.
- **`ExchangeCapabilities`** — a `BaseModel` of booleans, ints and dicts (`supports_native_oco`,
  `book_depths`, `order_link_id_max_len`, `book_cadence_ms`, …) constructed once per
  `(exchange, environment)` at startup.

**Decision: capability-record-driven behaviour, not per-call conditionals.** A consumer (OMS, rule engine,
book reconstruction) reads `capabilities.supports_native_oco` or `capabilities.book_depths` as data; it
never branches on `if exchange == "bybit"` or `if env == "demo"`. This is adapter rule 3
(`24-internal-schemas.md` §14.2) and is lint-enforced by `E08-X03`.

**Rejected alternative: per-call runtime checks (`if isinstance(port, BybitAdapter)` or string comparisons
scattered through consumer code).** Rejected because it reintroduces exchange-specific knowledge at every
call site a second exchange would need to touch, defeating the entire purpose of the port — the cost of
adding exchange #2 would be proportional to the number of call sites, not to the number of capability
differences. A capability record makes the cost proportional to the latter.

### D2 — Principle P3: no Bybit vocabulary outside the adapter package

`20-architecture.md` P3: **"All Bybit specifics live in `services/api/candleviewer/exchange/bybit/`."**
Concretely: no `retCode` integer, no raw Bybit field name (`execType`, `positionIdx`, `orderLinkId`'s wire
casing, `confirm`), and no Bybit topic string escapes the adapter package. The `Normalizer`
(`20-architecture.md` §3, table row) is the only place Bybit field names appear; everything past it is a
normalized domain event (`TradeEvent`, `BookDeltaEvent`, …) with fields the rest of the codebase owns.

**Enforcement, not just convention.** `E08-X03` ships a lint rule (adapter rule 3 above) that fails CI if a
Bybit-specific identifier appears outside `exchange/bybit/`. This ADR asserts the rule exists; it does not
duplicate the rule's implementation (owned by `E08-X03`).

**Rejected alternative: convention only, enforced by code review.** Rejected because review-only
enforcement degrades under time pressure and multi-agent parallelism (`CLAUDE.md` §10) — a lint gate is
cheap and catches the leak before a human ever has to notice it.

### D3 — Order-book gap handling: deterministic invalidate-and-resync, no silent patching

Bybit's public book stream has **no checksum** (`24-internal-schemas.md` §14.3, "Book" row); the only
signal of loss is a gap in the sequence number (`u`). The adapter therefore treats **any** `u` gap, and any
resulting **crossed book** (best bid ≥ best ask) after applying a delta, as desync — never as something to
clamp, interpolate or silently repair. On desync the adapter: discards the local book, emits
`BookDesyncEvent` (recorded, alerted, surfaced to the UI as a "book resyncing" badge,
`24-internal-schemas.md` §2.2), unsubscribes, resubscribes, and applies a fresh snapshot before returning to
`Live` (state machine at `24-internal-schemas.md` §2.2; statechart contract `28-statechart-catalogue.md`
§B14, book **health**, data path excluded per MUSTNOT-01 — the per-delta apply loop is never a statechart).

**Rejected alternative: attempt to patch a suspected small gap by re-fetching only the missing levels, or by
clamping a crossed book to keep serving heatmap/DOM data during the gap.** Rejected because Bybit gives no
checksum to confirm a patch is complete, and a "mostly right" book silently feeding rule-engine liquidity
metrics or the heatmap is worse than a visibly resyncing one — this is exactly the R9 honesty requirement:
degraded data must announce itself, not blend in. Columns produced during `Resyncing` are marked
`estimated=True` at 40% opacity with a hatch and excluded from any rule-engine liquidity metric
(`24-internal-schemas.md` §6, heatmap grid model) rather than shown at full confidence.

### D4 — Depth-tier and cadence: default 200, deferred, per `E08-K01`

`E08-K01` (spike, merged) measured Bybit's depth tiers 1/50/200/500 at cadences 10/20/100/200 ms by
replaying a seeded, recorded-shaped two-hour delta stream through a minimal `BookState` prototype and the
real merged bus (`services/api/bench/book_depth_compare.py`, committed run
`docs/plan/spikes/E08-K01-report.json`, seed=1, BTCUSDT/ETHUSDT/SOLUSDT). The measured, unambiguous finding:
**tier 500 @ 200 ms writes ~24–29% more bytes/day than tier 200 @ 100 ms per symbol despite halved cadence**
(each delta carries up to 2.5× more populated levels) — confirming depth is "a materially different
product, not a tuning knob" rather than a free upgrade.

**Decision, following ADR-0021 exactly: default depth 200, deferred, revisit at E21 with heatmap
evidence.** The pre-agreed mechanical rule (depth 500 > 0.5 vCPU/symbol or > 300 MB/symbol ⇒ choose 200
outright) was inconclusive-on-cost on this harness — its CPU leg is a single-tenant measurement artifact
(every row reported ~0.99 vCPU on both tiers) and memory did not trigger on either tier — so the decision
is **not** the mechanical rule's output; it is the ticket's own permitted "defer, revisit with evidence"
branch, with the revisit trigger named: E21's heatmap prototype reporting that tier-200 coverage visibly
truncates the rendered depth for the pinned symbol set. This ADR does not restate ADR-0021's comparison
table (`CONSTITUTION.md` C-16.5); ADR-0021 remains its owner.

**Rejected alternative: adopt depth 500 as the default up front, on the grounds that more book depth is
strictly better for the heatmap.** Rejected because the measured bytes/day cost compounds across the
recorder's retention budget (`E16`) before any UI benefit is proven necessary, and the mechanical
cost/benefit rule this project pre-committed to could not be satisfied for tier 500 either way — deferring
with a named, falsifiable trigger is honest where guessing a default would not be.

**Caveat carried forward (not resolved by this ADR):** `E08-K01`'s numbers are from a synthetic, seeded
generator, not a live capture, because no recorded 2-hour order-book fixture existed yet
(`packages/fixtures/raw/` corpus is `E08-T05`). `E08-S05` must re-run the harness against a real fixture
before treating these numbers as a production SLO.

### D5 — Environment separation: one client instance per environment, capability-enforced

Live, demo and testnet are separate credential sets, base URLs, storage namespaces and code paths
(`20-architecture.md` P9, `24-internal-schemas.md` §14.3 "Environment differences" table). **One adapter
client instance exists per `(exchange, environment)` pair**; a request built for one environment is never
signed with another environment's keys (`.claude/rules/22-exchange-adapter.md`). The differences
themselves — no WS order entry on demo, 7-day order retention on demo, `best_effort` private-WS stability
and REST-primary reconciliation on testnet — are `ExchangeCapabilities`/`ReconCapabilities` fields the OMS
and reconciler read as data (`24-internal-schemas.md` §14.3, SR-040a), never `if env == "demo"` branches.
Testnet in particular carries **no user positions, no rules, and is never selectable as a trading
environment in the UI** — it exists solely for the closed-list connectivity smoke test named in §14.3.

**Rejected alternative: a single shared client with an `environment` parameter threaded through every
call.** Rejected because it makes "which credentials just got used" a runtime question answerable only by
tracing call arguments, rather than a startup-time invariant answerable by "which object is this" — the
STRIDE model (`E08-X01`) treats cross-environment credential leakage as a spoofing/tampering risk this
separation is a primary mitigation for.

### D6 — Arithmetic and timestamps: `Decimal` price/quantity, µs-normalised exchange time

All price and quantity fields are `Decimal` end-to-end (`24-internal-schemas.md` C5); the integer
`price_ticks` form used by chart grids is explicitly **derived, never authoritative**
(`price_ticks = round((price - price_origin) / tick_size)`). All event timestamps are normalised to
microseconds and anchored to **exchange** time, never wall-clock receipt time; `ts_event` is never
synthesized — where a record lacks its own timestamp the adapter uses the containing push envelope's `ts`
and sets `ts_estimated=True` on the subtype that declares that field (`24-internal-schemas.md` §2, "Bybit →
domain events").

**Rejected alternative: `float` prices with tick-rounding applied only at the render boundary.** Rejected
outright per C-2 money/price handling and CONSTITUTION §2 — floats produce phantom price levels in
footprint/heatmap grids that key on an exact integer, and any monetary comparison on floats is a defect
class this project does not accept anywhere near order values.

## Consequences

- **A second exchange adapter is additive.** It implements `MarketDataPort`/`TradingPort`, builds its own
  `ExchangeCapabilities` record, and normalizes into the same domain events — no change to book
  reconstruction, OMS, rule engine or chart engine, provided it honours D3's invalidate-and-resync
  contract and D6's arithmetic conventions. The contract-test suite each adapter ships (adapter rule 5,
  `24-internal-schemas.md` §14.2) is reused verbatim against the new adapter's recorded fixtures.
- **The depth-tier decision is not implemented by this ADR** — `E08-S05` wires the chosen default 200 as an
  `ExchangeCapabilities`-driven config value and owns re-measuring against a real fixture.
- **Downstream epics get one trust contract to review against**, not nine independent re-derivations:
  `docs/plan/25-market-data-trust-contract.md` (companion to this ADR).
- **Anything asserted in the trust contract that has no enforcement (test, lint rule or schema) is marked
  a convention, honestly labelled** — see that document's final section.

## Validation gate

- `E08-X03`'s P3 lint rule passing is the enforcement evidence for D2.
- `tests/xstate_contract/` and `28-statechart-catalogue.md` §B14 golden traces are the evidence for the
  book-health FSM boundary referenced in D3 (data path excluded, MUSTNOT-01).
- `docs/plan/spikes/E08-K01-report.json` and its smoke test (`test_book_depth_compare_bench.py`, 5 passed)
  are the measured evidence for D4; no new measurement is introduced by this ADR.
- `E08-T06`'s doc-reconciliation check is the ongoing gate that keeps this ADR and
  `docs/plan/25-market-data-trust-contract.md` truthful against shipped behaviour; a mismatch blocks the
  R0 exit review and is corrected in the doc, never annotated as an exception.

## Alternatives considered (summary)

Per-decision rejected alternatives are recorded inline under D1–D6 above, each with its rejection reason,
per this ticket's acceptance criterion that every decision states at least one rejected alternative and
why.
