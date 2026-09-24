# -*- coding: utf-8 -*-
"""E46 part 3: backend, storage, CI enforcement, ADR."""
from _e46_lib import T

tickets = []

tickets.append(T("E46-T04", "Task",
    "Profile the backend hot paths and add the WS tick-to-screen span breakdown",
    ["type/tech", "area/backend-platform", "priority/p1", "perf"],
    "api", "Sprint 23", "P1 High", "Development", "R3 Real-time cost", 5, "E46",
    ["E46-K01", "E04"],
    """## Context
`docs/plan/06-performance-and-load-standard.md` §5.1 breaks the WS tick→screen budget into seven stages and allocates the four CandleViewer-controlled backend stages a combined **≤20 ms p95** (budget #6): ingestion parse ≤3 ms, book/bar-builder update ≤5 ms, pre-aggregation ≤5 ms, fan-out emit ≤7 ms. US-OBS-002 requires that "exchange timestamp to on-screen paint is measured per stage (ingest, internal fan-out, client render) and reported as percentiles", and that when p95 exceeds 250 ms for 60 s "an alert fires **naming the stage** that consumed the budget". `docs/plan/20-architecture.md` §12.1 has `ws_fanout_latency_seconds` (p99 ≤20 ms) and `engine_process_seconds{engine}` as the metric surface.

What exists today is the aggregate fan-out histogram; the four-stage split that US-OBS-002 demands, and the profiling data needed to optimise any of them, do not. This ticket is the backend twin of E46-T01: make the §5.1 stages measurable, then profile the hot paths with `py-spy`/`memray` under the full 10-symbol capacity load so E46-T05 and E46-T07 have targets instead of guesses.

## Scope / Deliverables
- OpenTelemetry spans (`docs/plan/20-architecture.md` §12.3) at each §5.1 backend stage boundary, with a stage name enum matching the doc exactly: `ingest_parse`, `book_update`, `pre_aggregate`, `fanout_emit`.
- Extend `ws_fanout_latency_seconds` into a per-stage histogram (or add a sibling `ws_stage_latency_seconds{stage}`) so the four sub-budgets are independently visible, with bounded label cardinality per US-OBS-001's NFR.
- Propagate the ingestion-receipt timestamp and the trace/span id into the outbound WS envelope (`docs/plan/23-ws-protocol.md` §3.1) so the frontend can close the end-to-end loop and attribute the network + frontend stages — `06-…` §7.2 names this as an architecture requirement; E46-K01 reports whether it already exists.
- Extend `engine_process_seconds{engine}` to cover every order-flow engine (footprint, profile, CVD, Deep-Stats, big-trade, imbalance, detectors) so per-engine CPU is attributable rather than aggregate.
- Profile with `py-spy` (sampling, `--nonblocking`, per `06-…` §8 step 4) and `memray` against the §9 "Full capacity scenario" load (10 symbols / 5 accounts / 5 users) driven from recorded Bybit fixtures, producing flamegraphs for: WS frame parse, book delta application, bar builders, order-flow aggregation, fan-out serialisation, Postgres/QuestDB write paths.
- A written hot-path report listing the top CPU consumers and top allocation sites with their share, handed to E46-T05 (serialisation) and E46-T07 (CPU/memory) as their work lists.
- Verify the `event_loop_lag_seconds` p99 ≤50 ms target from §12.1 holds under the capacity load, and identify any blocking call on the event loop (a synchronous `json` call, a blocking DB driver call, a CPU-bound loop without a yield) — these are the classic asyncio killers and finding them is a primary deliverable.

## Out of scope
- Fixing what is found — T05 and T07 own the fixes; this ticket's job is to measure, attribute and hand over. Trivially-safe fixes found during profiling may be included if each is ≤20 LOC and separately tested.
- Frontend stages (E46-T01).
- QuestDB query tuning (E46-T08).

## Acceptance criteria
```gherkin
Scenario: The four backend stages are independently measured
  Given the backend is processing the 10-symbol capacity load
  Then ingest_parse, book_update, pre_aggregate and fanout_emit each have a p50, p95 and p99 exported
  And each is compared against its allocation from docs/plan/06-performance-and-load-standard.md §5.1

Scenario: The backend-internal budget is proven, not assumed
  Given a 30-minute run at realistic-peak load
  Then the sum of the four backend stages at p95 is at or below 20ms, satisfying budget #6

Scenario: A budget breach names the stage
  Given the end-to-end p95 exceeds 250ms for 60 seconds
  When the alert fires
  Then the alert payload names which stage consumed the budget, as required by US-OBS-002

Scenario: Profiling overhead is within the NFR
  Given py-spy is attached in non-blocking mode to the ingestion supervisor under capacity load
  Then the measured CPU overhead is at or below 1% and the ingestion message-loss counter remains zero

Scenario: The event loop is not blocked
  Given the capacity load runs for 30 minutes
  Then event_loop_lag_seconds p99 stays at or below 50ms
  And any call blocking the loop for more than 10ms is identified in the hot-path report with its stack

Scenario: The hot-path report is actionable
  When the report is delivered
  Then it lists the top ten CPU consumers and top ten allocation sites with their percentage share and the owning module from docs/plan/20-architecture.md §4
```

## Technical notes / design
Timestamp discipline: the ingestion-receipt timestamp is taken once, at the moment the raw Bybit frame is read off the socket, and carried through — not re-taken at each stage, which would hide queueing time. Queueing between stages is exactly what `ingest_queue_depth{stage}` (§12.1) exists to expose, and it must be sampled alongside the stage timings or a "fast stage, long queue" pathology will look healthy.

Clock handling: end-to-end measurement crosses the exchange clock, the backend clock and the browser clock. US-OBS-002's NFR requires clock offset to be accounted for per US-MKT-009 (`bybit_clock_drift_ms` in §12.1); the backend→frontend leg uses the span-id correlation plus the frontend's own `performance.timeOrigin`, never a naive subtraction of two wall clocks.

`py-spy` must be run with `--nonblocking` against the asyncio supervisor described in `20-architecture.md` §4.1; blocking-mode profiling on a live ingestion process risks stalling it and creating the very message loss the budget forbids. E46-K01 pre-verifies this; if K01 found it unsafe, use its recommended alternative.

`memray` output grows quickly; for the capacity-load runs use time-boxed captures with native-stack symbolisation off unless needed, and record the capture size so E46-Q02 can plan its 72 h soak accordingly.

## Test plan
- **Unit** (≥85 % backend coverage on new lines): stage-timer context manager including the exception path (a stage that raises still records its duration and marks the span errored); label-cardinality guard test asserting the stage set is closed.
- **Contract**: WS envelope with the propagated trace/span id validated against the `23-ws-protocol.md` §3.1 schema; a JSON and a msgpack client both tolerate the added field (additive evolution, §2's stated requirement).
- **Integration**: recorded-fixture replay asserting the four stages are emitted per message and sum sensibly.
- **Load**: k6/Locust capacity scenario from §9; `event_loop_lag_seconds` and per-stage p95 asserted.
- **Chaos-adjacent**: profiling attached during a WS-disconnect/resync event (reused from E45's harness) to confirm the instrumentation survives a resubscribe.

## Security notes
Spans and metrics must carry no secret and no personal data — US-OBS-001's NFR says metrics are labelled "by symbol, account and environment without embedding any secret or personal data"; account labels must be the internal account id, never an API key, UID-derived secret or human name. `py-spy`/`memray` captures include in-memory state and can contain order data and, in the worst case, credential material held in memory: captures are written to a gitignored operational path, access-controlled, never attached to a public issue, and deleted after analysis. The trace/span id added to the WS envelope must be a random opaque id, not something that encodes internal structure. Feeds E46-X01's STRIDE and is verified by E46-X02.

## Accessibility notes
N/A — backend only.

## Performance notes
Binding: budget #6 ≤20 ms p95 backend-internal, split 3/5/5/7 ms per §5.1; `ws_fanout_latency_seconds` p99 ≤20 ms (§12.1); `event_loop_lag_seconds` p99 ≤50 ms; instrumentation overhead ≤1 % CPU (US-OBS-002 NFR); zero ingestion message loss throughout (budget #5).

## Observability
Adds `ws_stage_latency_seconds{stage}`; extends `engine_process_seconds{engine}` to all order-flow engines; ensures `ingest_queue_depth{stage}` is sampled with the stage timings; adds the stage name to the budget-breach alert payload so US-OBS-002's "naming the stage" requirement is met by the alert rule, not by a human reading a dashboard.

## Definition of Done
- [ ] All six Gherkin scenarios verified.
- [ ] Hot-path report delivered and linked from E46-T05 and E46-T07.
- [ ] Spans and metrics merged; cardinality documented per US-OBS-001.
- [ ] WS envelope change reflected in `docs/plan/23-ws-protocol.md` §3.1 and contract tests updated.
- [ ] `docs/plan/20-architecture.md` §12.1 updated with the new/extended metrics.
- [ ] Alert rule updated to name the stage; rule is version-controlled config per US-OBS-004's NFR.
- [ ] Coverage ≥85 % on changed backend lines.
- [ ] Reviewed by a backend code owner + the Architect.

## Dependencies
- **E46-K01** verifies `py-spy`/`memray` safety and reports whether span-id propagation already exists.
- **E04** supplies the metrics/tracing pipeline being extended.

## Branch
`feat/e46-perf-backend-spans`. PR size: spans+metrics one PR, envelope propagation a second (it is a protocol change and deserves its own review).

## References
`docs/plan/06-performance-and-load-standard.md` §5.1, §7.2, §8, §9, §2 budgets #5 and #6 · `docs/plan/20-architecture.md` §4.1, §12.1, §12.3 · `docs/plan/23-ws-protocol.md` §3.1 · `docs/plan/11-user-stories.md` US-OBS-001, US-OBS-002, US-OBS-004
"""))

tickets.append(T("E46-T05", "Task",
    "Optimise WS fan-out serialisation and binary framing against the 7ms emit budget",
    ["type/tech", "area/backend-platform", "priority/p1", "perf"],
    "api", "Sprint 24", "P1 High", "Development", "R3 Real-time cost", 5, "E46",
    ["E46-T04"],
    """## Context
The `fanout_emit` stage owns **≤7 ms p95** of the ≤20 ms backend-internal budget (`docs/plan/06-performance-and-load-standard.md` §5.1), and it is the stage whose cost scales with the number of subscribers — at the capacity target (5 users × up to 20 pane subscriptions, §10.1) one book update can fan out to dozens of sockets. `docs/plan/23-ws-protocol.md` §3.4 already made the right architectural call: hot payloads (book deltas, bars, footprint cells, heatmap columns) use a hand-rolled fixed-layout binary format inside a MessagePack envelope, with `permessage-deflate` deliberately **disabled** for `cv.v1.msgpack` because deflating dense binary "burns CPU on both ends for <5 % gain and adds latency jitter at the 10–20 ms book cadence".

What has not been done is making the implementation live up to that design under load: serialise-once-fan-out-many, zero-copy where the protocol allows, and no per-subscriber re-encoding. E46-T04's hot-path report tells us exactly where the time and the allocations go; this ticket acts on the serialisation portion of it.

## Scope / Deliverables
- Implement/verify **encode-once, send-many**: a payload is encoded once per (topic, effective options) tuple per tick and the resulting buffer is shared across all subscribers with identical options, rather than re-encoded per socket. Where subscribers differ only in `throttle_ms`, the encoding is still shared and only the send schedule differs.
- Eliminate per-frame allocation in the encode path: preallocated/pooled buffers, `memoryview`/`bytearray` reuse, no intermediate Python list-of-dicts for binary kinds.
- Verify the binary payload writers for each kind in `23-ws-protocol.md` §3.4 (book, bars, footprint, heatmap columns, trades) are single-pass and fixed-layout, with no per-row Python-level loop where a `struct`/buffer-protocol bulk write is possible.
- Confirm the compression decision empirically: measure CPU and latency with `permessage-deflate` on and off for `cv.v1.msgpack` under capacity load and record the numbers, so §3.5's claim is evidence-backed at GA rather than an inherited assumption.
- Slow-consumer handling under load: verify `ws_conflated_total`, `ws_slow_conn_total` and `ws_resync_total` (`docs/plan/20-architecture.md` §12.1) behave correctly when one subscriber is slow — a slow socket must not add latency to fast ones (per-connection send queues with bounded depth and conflation, not a shared blocking write).
- Measure bandwidth per the §6 bandwidth consequence figures in `23-ws-protocol.md` and confirm the heatmap column encoding matches the documented byte budget.
- Before/after numbers for the `fanout_emit` stage and for CPU-per-symbol under the §9 capacity scenario.

## Out of scope
- Changing the wire format or adding a new binary kind — any format change is a protocol-version decision requiring an ADR and E46 is not the place for it. Fixing an implementation that does not match the documented format *is* in scope and is a bug.
- Frontend decode (`fe_ws_decode_ms` is measured by E46-T01; if decode proves to be the bottleneck, file a follow-up against the chart-engine rather than widening this ticket).
- Backend memory and per-symbol CPU generally (E46-T07).

## Acceptance criteria
```gherkin
Scenario: The emit stage fits its budget at capacity
  Given 5 users with 20 pane subscriptions each against 10 symbols at realistic-peak cadence
  Then the fanout_emit stage p95 is at or below 7ms
  And the four backend stages together remain at or below 20ms p95, satisfying budget #6

Scenario: Encoding is shared, not repeated
  Given twenty subscribers to the same topic with identical effective options
  When one book update is fanned out
  Then the payload is encoded exactly once
  And the count of encode operations is asserted by an instrumented counter, not inferred from timing

Scenario: A slow consumer is isolated
  Given one subscriber's socket stops draining
  Then that subscriber's frames are conflated and ws_slow_conn_total increments
  And the p95 fan-out latency for all other subscribers is unchanged within measurement noise
  And the slow subscriber is eventually resynced or disconnected per the protocol rather than growing an unbounded queue

Scenario: The compression decision is evidence-backed
  Given the capacity load is run with permessage-deflate enabled and disabled for cv.v1.msgpack
  Then CPU cost and latency jitter for both configurations are recorded in the ticket
  And docs/plan/23-ws-protocol.md §3.5 is confirmed or corrected against the measurement

Scenario: The wire format is unchanged
  Given the contract test suite for docs/plan/23-ws-protocol.md §3.4
  Then every binary kind encodes byte-identically to the pre-change golden fixtures
```

## Technical notes / design
The encode-once win is the structural one and should be built as a per-tick encode cache keyed by `(topic, encoding, depth, price_grouping, …)` — i.e. the `effective` options block echoed in the `sub` ack (`23-ws-protocol.md` §5). The cache lives for exactly one tick and is cleared, so there is no staleness risk and no memory growth.

Zero-copy claim check: `23-ws-protocol.md` §2 states MessagePack "lets us carry raw `bin` fields with zero-copy access to their `ArrayBuffer`". Verify the backend side is genuinely not copying the binary blob into the envelope buffer an extra time — one avoidable `bytes` copy per subscriber per tick at capacity is a meaningful share of a 7 ms budget.

Bounded queues: per-connection send queues must be bounded with a documented depth; on overflow the behaviour is conflate-then-resync, never unbounded buffering (which turns a slow consumer into a backend OOM — a §6.4 pass-criterion violation).

Do not micro-optimise without the report: E46-T04's flamegraph decides the order of work. If the report shows encode is already comfortably inside budget and the time is in the socket write path or the event loop, say so, record it, and redirect the effort — a ticket that closes with "measured, already within budget, here are the numbers" is a successful ticket.

## Test plan
- **Unit** (≥85 %): encode cache key equality/inequality across every option in the `effective` block; buffer pool reuse without cross-contamination between concurrent encodes; bounded-queue overflow behaviour.
- **Contract**: golden byte-fixtures per binary kind from `23-ws-protocol.md` §3.4 — byte-identical output is a hard gate; JSON/`b64` fallback path also asserted.
- **Integration**: multi-subscriber fan-out with an instrumented encode counter; slow-consumer isolation test with a deliberately stalled socket.
- **Load**: §9 WS tick→screen scenario and the full-capacity composite; bandwidth compared against the documented per-topic figures.
- **Chaos**: run the fan-out under a WS-disconnect/resubscribe storm reused from E45 to confirm the encode cache and queues behave across resync.

## Security notes
A shared encode buffer across subscribers is a **data-leak surface**: if the cache key omits an option that affects payload content, one user could receive another user's payload shape — or, worse, a topic they are not entitled to. The cache key must include every content-affecting option, and an authorisation check must remain per-subscriber and *outside* the cache (the cache may only be consulted after the subscriber's entitlement to the topic has been established). This is a named abuse case for E46-X02. Buffer pooling carries the classic risk of stale bytes leaking into a shorter subsequent message — always write the exact length and never send the pool's residual tail; add a test that fills pooled buffers with a poison pattern in debug builds.

## Accessibility notes
N/A — backend only.

## Performance notes
Binding: `fanout_emit` ≤7 ms p95; budget #6 ≤20 ms p95 total backend-internal; budget #3 p95 <100 ms / p99 <250 ms end-to-end; budget #11 ≤0.5 vCPU per symbol (fan-out is a contributor); documented per-topic bandwidth in `23-ws-protocol.md` §6.

## Observability
`ws_stage_latency_seconds{stage="fanout_emit"}` from T04; new `ws_encode_operations_total` counter (proves encode-once); existing `ws_conflated_total`/`ws_slow_conn_total`/`ws_clients`/`ws_topics_per_client` asserted under load rather than merely present.

## Definition of Done
- [ ] All five Gherkin scenarios verified by automated tests.
- [ ] Before/after `fanout_emit` and CPU-per-symbol numbers in the PR body.
- [ ] Golden byte-fixture contract tests green (format unchanged).
- [ ] Compression measurement recorded; `docs/plan/23-ws-protocol.md` §3.5 confirmed or corrected.
- [ ] Encode-cache key completeness reviewed by Security (entitlement-outside-cache invariant).
- [ ] Coverage ≥85 % on changed lines.
- [ ] Reviewed by a backend code owner.

## Dependencies
- **E46-T04** supplies the stage timings and the hot-path report that scope this ticket's work.

## Branch
`feat/e46-perf-fanout-serialisation`. PR size ≤400 LOC per change; encode-cache, buffer pooling and slow-consumer work are separate PRs.

## References
`docs/plan/06-performance-and-load-standard.md` §5.1, §6.4, §9, §2 budgets #3, #6, #11 · `docs/plan/23-ws-protocol.md` §2, §3.4, §3.5, §5, §6 · `docs/plan/20-architecture.md` §12.1 · `docs/plan/11-user-stories.md` US-OBS-002
"""))

tickets.append(T("E46-T07", "Task",
    "Bring backend per-symbol CPU and memory inside the 0.5 vCPU and 300MB ceilings",
    ["type/tech", "area/backend-platform", "priority/p1", "perf"],
    "api", "Sprint 24", "P1 High", "Development", "R3 Real-time cost", 5, "E46",
    ["E46-T04"],
    """## Context
Two budgets govern backend footprint per actively-recorded symbol: **#8**, ≤300 MB resident (hard), and **#11**, ≤0.5 vCPU sustained (soft, but it is the basis of the entire §10.2 capacity plan — 10 symbols × 0.5 vCPU = 5 cores of the 4–6 core VPS target). `docs/plan/06-performance-and-load-standard.md` §6.2 names the mechanism the memory ceiling depends on: "bounded rolling buffers per bar-builder/aggregation engine… time-boxed and rolled to storage rather than retained unbounded in process memory". §6.4 adds a hard stress criterion: "no backend process OOM-kills or restarts".

These have been designed for but never *enforced* against a running system at capacity. E46-T04's profile is the input; this ticket is the fix-and-prove pass covering the hot paths that are not serialisation (which is E46-T05): book delta application, bar builders, and the order-flow aggregation engines.

## Scope / Deliverables
- Act on the CPU portion of E46-T04's hot-path report for: book delta application (M-book), the time/tick/volume/range bar builders, and the order-flow aggregation engines (footprint, profile, CVD, Deep-Stats, big-trade, imbalance, detectors) as measured by `engine_process_seconds{engine}`.
- Act on the allocation portion: replace per-message allocation in the hot loops with reused structures; ensure `msgspec`/`orjson` fast paths are actually taken (a silent fallback to stdlib `json` for one message type would be invisible and expensive); avoid per-tick `Decimal` construction where a scaled integer is correct (price/size arithmetic must stay exact — this is market and order data, so any change from `Decimal` to integer scaling must be provably lossless for the instrument's tick/step size and covered by tests).
- Audit every rolling buffer and aggregation window for a **hard bound**: a documented maximum element count or time window, with the eviction/roll-to-storage path tested. Any unbounded structure found is a memory-leak bug and gets its own regression test.
- Per-symbol accounting: make per-symbol RSS and CPU measurable in the way budgets #8 and #11 specify ("`psutil`/cgroup memory sampled per symbol-worker process/task"), which requires the per-symbol task isolation from §6.1 to be attributable — if per-task attribution is not achievable in-process, implement a documented estimation method and state its accuracy.
- Verify per-symbol isolation under burst: §9's "Ingestion burst, synthetic 5× / 60 s" scenario requires that "other 9 symbols' Budget #3/#6 latency unaffected during the burst". Prove it with numbers.
- `memray` run over a multi-hour window to catch slow growth before E46-Q02's 72 h soak, mirroring E46-T06 on the frontend side.
- Before/after numbers for per-symbol CPU and RSS at the §9 capacity scenario.

## Out of scope
- WS fan-out serialisation (E46-T05).
- QuestDB/Postgres query tuning (E46-T08).
- Changing recording policy, retention or what is aggregated — E16's domain; if a budget can only be met by recording less, that is a finding to escalate, not a change to make here.
- Horizontal scale-out (explicitly excluded by §10.3).

## Acceptance criteria
```gherkin
Scenario: Per-symbol memory holds at capacity
  Given 10 symbols are actively recorded at full stream cadence for a 24-hour ingestion soak
  Then resident memory attributable per symbol stays at or below 300MB p95 throughout
  And no rolling buffer or aggregation window grows without bound

Scenario: Per-symbol CPU holds at capacity
  Given a one-hour steady-state window at full cadence with 10 symbols
  Then CPU per symbol is at or below 0.5 vCPU-equivalent p95
  And the aggregate stays within the 4-6 core provisioning target of §10.2

Scenario: A burst on one symbol does not harm the others
  Given a synthetic 5x message burst on one symbol for 60 seconds
  Then that symbol records zero undetected message loss
  And the other nine symbols' WS tick-to-screen p95 and backend fan-out p95 are unchanged within measurement noise

Scenario: No process dies under stress
  Given the worst-case stress scenario from docs/plan/06-performance-and-load-standard.md §6.4
  Then no backend process is OOM-killed and no process restarts

Scenario: Price arithmetic stays exact
  Given any hot-path change from Decimal arithmetic to scaled-integer arithmetic
  Then a property test over the instrument tick and step sizes shows the results are identical to the Decimal computation for every tested value
```

## Technical notes / design
Order of work is decided by E46-T04's report, not by intuition. The usual top offenders in an asyncio ingestion pipeline are: JSON parsing (already mitigated by `orjson`/`msgspec` — verify the fast path is taken for *every* message type, including the rarely-hit ones), per-message object construction, and `Decimal` arithmetic in a tight loop.

Exactness is non-negotiable where money is involved. `docs/plan/24-internal-schemas.md` is the authority on the domain types; if a hot path currently uses `Decimal` and a scaled integer would be faster, the change is only acceptable with a property-based test over the instrument's tick/step grid proving identical results, and a comment stating the invariant. A rounding difference introduced for speed in an order-adjacent path is a P0 defect class, not a perf trade-off.

Bounded-buffer audit: produce a table of every in-memory accumulator (owner module, key, bound type — count or time, eviction path, tested?) and put it in the ticket. An accumulator without a bound is the thing that kills the 72 h soak, and a table makes the absence visible in a way that reading code does not.

Per-symbol attribution: if symbols run as asyncio tasks in a shared process, `psutil` cannot attribute RSS per task. Options: run symbol workers as separate processes (a structural change — needs the Architect and probably an ADR), or use `tracemalloc`/`memray`-derived attribution plus a documented accuracy bound. Choose with the Architect and record the choice; do not quietly report a number whose derivation is unstated.

## Test plan
- **Unit** (≥85 %): every rolling buffer's bound and eviction; fast-path parser selection per message type (table-driven over the Bybit topic set); property tests for any arithmetic change.
- **Integration**: recorded-fixture replay asserting aggregation outputs are byte-identical before and after optimisation — an optimisation that changes a footprint or profile value is a bug, not a speedup.
- **Load/soak**: §9 ingestion soak 24 h × 10 symbols with per-symbol RSS/CPU sampling; burst-isolation scenario; §6.4 stress composite.
- **Memory**: `memray` over a multi-hour window with the growth slope reported.
- Coverage ≥85 % on changed backend lines.

## Security notes
Optimising hot paths must not weaken validation: input parsing of exchange frames is a trust boundary (`docs/plan/04-security-program.md`), and a "fast path" that skips a length/bounds/type check to save microseconds is a vulnerability, not an optimisation. Any parsing change must keep the same rejection behaviour for malformed input, proven by a fuzz/negative-fixture test. `memray` captures contain in-memory data including order state — same handling rules as E46-T04 (gitignored path, access-controlled, never attached to an issue).

## Accessibility notes
N/A — backend only.

## Performance notes
Binding: budget #8 ≤300 MB per symbol (hard); budget #11 ≤0.5 vCPU per symbol (soft, capacity-plan basis); budget #5 zero undetected message loss; §6.4 no OOM/restart; §10.2 provisioning target 4–6 vCPU / 8–16 GB.

## Observability
`engine_process_seconds{engine}` per order-flow engine (from T04) asserted against budget; per-symbol RSS/CPU gauges added with their derivation documented; `ingest_queue_depth{stage}` used as the saturation signal; the bounded-buffer table published in the module docs so the invariant is discoverable.

## Definition of Done
- [ ] All five Gherkin scenarios verified.
- [ ] Bounded-buffer audit table completed and published; every unbounded structure fixed with a regression test.
- [ ] Before/after per-symbol CPU and RSS numbers in the PR body.
- [ ] Aggregation outputs proven byte-identical on recorded fixtures.
- [ ] Per-symbol attribution method documented with its accuracy bound; ADR raised if a structural change was chosen.
- [ ] Coverage ≥85 % on changed lines; fuzz/negative-fixture parsing tests green.
- [ ] Reviewed by a backend code owner + the Architect.

## Dependencies
- **E46-T04** supplies the hot-path and allocation report.

## Branch
`feat/e46-perf-backend-cpu-memory`. PR size ≤400 LOC per change; the bounded-buffer audit may be a docs-only PR landing first.

## References
`docs/plan/06-performance-and-load-standard.md` §6.1, §6.2, §6.4, §9, §10.2, §10.3, §2 budgets #5, #8, #11 · `docs/plan/20-architecture.md` §4, §12.1 · `docs/plan/24-internal-schemas.md` · `docs/plan/04-security-program.md`
"""))

tickets.append(T("E46-T08", "Task",
    "Tune QuestDB replay-scan queries and the engine_metrics write path",
    ["type/tech", "area/backend-platform", "priority/p2", "perf"],
    "infra", "Sprint 24", "P2 Medium", "Development", "R3 Real-time cost", 3, "E46",
    ["E46-T04", "E26"],
    """## Context
Replay is a hard budget: **#15** requires sustaining up to 100× playback "without violating budget #1's frame floor… must not crash/desync", and §9's replay scenario runs it against a recorded 24 h fixture. At 100× the data-fetch path, not the render path, is the likely limiter: replay scans `trades`, `orderbook_deltas`, `orderbook_snapshots`, `bars_time`, `footprint_cells` and `heatmap_cells` in QuestDB (`docs/plan/21-database-schema.md` §4) over wide time ranges, and `orderbook_deltas` is noted there as "the largest stream by far" (~10.6 GB/day/symbol at 200 depth per §'s sizing table). These queries have never been tuned or even systematically measured.

Additionally, E46-T01 optionally writes 2 Hz engine telemetry into `engine_metrics` (§4.13), and `questdb_write_seconds` (`docs/plan/20-architecture.md` §12.1) is listed as a saturation signal — the new write volume must not disturb the ingestion write path that budget #5's zero-loss guarantee depends on.

## Scope / Deliverables
- Build a replay-scan benchmark: for each of the six tables above, measure cold and warm query latency for the access patterns replay actually uses (a forward window scan with a moving cursor, a point-in-time snapshot fetch, and a bulk pre-fetch of the next N seconds), at 1×, 20× and 100× playback against a recorded 24 h fixture.
- Tune what the measurements show. Candidates to confirm: partition-aligned range predicates so QuestDB prunes partitions rather than scanning; designated-timestamp ordering exploited rather than re-sorted; `SAMPLE BY`/`LATEST ON` used where it replaces an application-side loop; column selection narrowed (never `SELECT *` on `orderbook_deltas`); symbol-column indexing where the cardinality justifies it; prefetch window sized so replay stays ahead of playback at 100× without pulling the whole day into memory.
- Verify the replay prefetch honours the backend memory budget (#8) — pulling a 100× window must not become an unbounded buffer, which would also violate E46-T07's bounded-buffer rule.
- Validate the cold-tier path: replay over a window that has been archived to Parquet/DuckDB (`21-database-schema.md` §5, the `read_parquet` views) must work and be measured too, because the 30-day retention default means any replay older than that hits cold storage. Record the cold-tier numbers separately — they will be slower, and the product needs to know by how much.
- Measure `engine_metrics` write cost at the 2 Hz × panes rate and confirm ingestion write latency (`questdb_write_seconds`) is unaffected; if it is affected, batch the telemetry writes or drop the `engine_metrics` sink (it is explicitly secondary — "Prometheus remains the primary metrics path", §4.13).
- Confirm the retention/eviction jobs (§'s retention table: `orderbook_deltas` 7 d hot, `heatmap_cells` 7 d hot, `engine_metrics` 14 d then drop) run without disturbing live ingestion, since a compaction storm during market hours is a realistic cause of a budget breach.

## Out of scope
- Changing the schema, partitioning strategy or retention policy as a product decision — measuring and proposing is in scope; a schema change requires an ADR and the storage owner (E16/E03).
- Postgres query tuning (no evidence it is hot; file a separate ticket if E46-T04's report says otherwise).
- Replay UX, scrubbing or speed controls (E26).

## Acceptance criteria
```gherkin
Scenario: Replay sustains 100x from hot storage
  Given a recorded 24-hour fixture in QuestDB and replay at 100x speed
  Then the data-fetch path keeps the replay cursor supplied without stalling
  And frame rate stays at or above the 30fps floor and no desync is detected, satisfying budget #15

Scenario: Query cost is measured per table and per pattern
  When the replay-scan benchmark runs
  Then cold and warm latency is reported for each of trades, orderbook_deltas, orderbook_snapshots, bars_time, footprint_cells and heatmap_cells, for each of the three access patterns

Scenario: Prefetch stays bounded
  Given replay at 100x with a wide prefetch window
  Then the replay buffer respects a documented maximum size
  And backend resident memory stays within budget #8

Scenario: Cold-tier replay works and its cost is known
  Given a replay window older than the hot retention period so it resolves through the Parquet/DuckDB views
  Then the replay completes correctly
  And its measured latency is recorded and documented as the cold-tier expectation, distinct from the hot-tier number

Scenario: Telemetry writes do not disturb ingestion
  Given engine_metrics is being written at the 2Hz sampling rate while 10 symbols ingest at full cadence
  Then questdb_write_seconds for the ingestion path is unchanged within measurement noise
  And the ingestion message-loss counter remains zero
```

## Technical notes / design
Partition pruning is the single highest-leverage item in QuestDB: a range predicate on the designated timestamp that the planner can use to skip partitions turns a full scan into a bounded read. Verify with the query plan, not by timing alone — a query that got faster because the OS page cache was warm teaches nothing.

`orderbook_deltas` is the table that will hurt. If per-delta replay at 100× cannot be made to work from raw deltas, the correct answer is likely to replay from `orderbook_snapshots` plus a shorter delta tail (the same shape the retention policy's downsample-to-1 s-snapshots action already uses past 180 days). That is a replay-architecture proposal, so raise it with E26's owner and the Architect rather than implementing it unilaterally.

Keep measurements honest: report cold (page cache dropped) and warm separately, state which is which, and run ≥3 repetitions per §7.4's flake-tolerance rule.

## Test plan
- **Unit**: query-builder tests asserting the generated SQL carries a partition-aligned timestamp predicate and an explicit column list for every replay query (a `SELECT *` on `orderbook_deltas` should fail a test, not a review).
- **Integration**: replay correctness over a recorded fixture — the reconstructed book at time T must equal the recorded book at time T, before and after tuning (no optimisation may change replayed data).
- **Perf**: the replay-scan benchmark at 1×/20×/100×, hot and cold tier, 3 runs each; §9's replay scenario end-to-end.
- **Soak-adjacent**: telemetry write load concurrent with a 1 h ingestion run, asserting `questdb_write_seconds` unchanged.
- Coverage ≥85 % on changed backend lines.

## Security notes
Query construction must remain parameterised — a replay window or symbol arriving from the UI and concatenated into SQL is an injection surface (`docs/plan/04-security-program.md`); assert parameterisation in the query-builder tests and keep the SAST rule that flags string-built SQL (E46-X02 owns the rule). Recorded market data is not secret, but a replay endpoint that accepts an arbitrary unbounded range is a denial-of-service surface against the database — confirm the range is validated and bounded server-side, not merely by the UI.

## Accessibility notes
N/A — backend/storage only.

## Performance notes
Binding: budget #15 (100× replay, no crash/desync, 30 fps floor); budget #8 ≤300 MB per symbol including replay buffers; budget #5 zero undetected ingestion loss while replay and telemetry writes run; `questdb_write_seconds` unchanged for the ingestion path; §12 storage growth figures unaffected.

## Observability
Adds a `replay_scan_seconds{table,pattern,tier}` histogram (tier = hot|cold) — currently no metric describes replay fetch cost at all, which is why this is a measurement ticket as much as a tuning one. `questdb_write_seconds` asserted, not just scraped.

## Definition of Done
- [ ] All five Gherkin scenarios verified.
- [ ] Per-table, per-pattern, hot and cold latency table recorded in the ticket and summarised in `docs/plan/21-database-schema.md` §4.14 operational notes.
- [ ] Query plans (not just timings) evidencing partition pruning attached.
- [ ] Replay-correctness integration test green before and after tuning.
- [ ] Any proposed schema/replay-architecture change raised as an ADR with E26 and the Architect rather than implemented here.
- [ ] Coverage ≥85 % on changed lines.
- [ ] Reviewed by a backend code owner + the storage owner.

## Dependencies
- **E46-T04** for the backend profile that shows whether storage is on the hot path.
- **E26** owns the replay engine whose queries are being tuned.

## Branch
`feat/e46-perf-questdb-replay-scans`. PR size ≤400 LOC; benchmark first, tuning second.

## References
`docs/plan/06-performance-and-load-standard.md` §9, §2 budgets #5, #8, #15 · `docs/plan/21-database-schema.md` §4.1, §4.2, §4.9, §4.12, §4.13, §4.14, §5, retention table · `docs/plan/20-architecture.md` §12.1 · `docs/plan/04-security-program.md`
"""))

tickets.append(T("E46-T10", "Task",
    "Promote every hard budget to a CI-enforced required check with regression alarms",
    ["type/tech", "area/backend-platform", "area/chart-engine", "priority/p0", "perf"],
    "infra", "Sprint 25", "P0 Critical", "Development", "R2 Render performance", 8, "E46",
    ["E46-T02", "E46-T03", "E46-T05", "E46-T07", "E46-T08", "E46-T09"],
    """## Context
This is the ticket that makes E46's work permanent. `docs/plan/06-performance-and-load-standard.md` §7.4 specifies the enforcement model precisely and it is currently implemented only for the chart-engine's B1–B10 gates (`docs/plan/26-chart-engine-design.md` §13): every merge to `main` (or nightly for the expensive variants) runs the relevant harnesses, compares p95 against a stored baseline, fails the build on a **>5 % regression** of any hard-budget metric as a **required check**, moves baselines forward only through an explicit reviewed "update performance baseline" PR, and reports p50/p95/p99 across **≥3 repeated runs** with the gate comparing medians to suppress runner noise.

The remaining budgets — WS tick→screen, fan-out, ingestion, memory ceilings, bundle size, startup, backend CPU, storage growth, REST latency, heatmap cadence, replay — have no gate. Without this ticket, every optimisation in E46 decays silently over the first post-GA quarter. The R5 quality gate in `docs/plan/30-release-roadmap.md` §9.4 and the epic's first acceptance scenario both require that a deliberate 6 % regression fails the build.

## Scope / Deliverables
- A single **budget registry** (`bench/budgets.yaml` or equivalent, version-controlled) that is the machine-readable form of `06-…` §2: one entry per budget with id, target, hard/soft, harness that measures it, metric key in the harness report, comparison mode (absolute threshold and/or ≤5 % vs baseline), CI trigger (per-PR / nightly / per-release), and the owning plan-doc anchor. One source of truth; the markdown table and this file must not drift, so add a CI check that the registry lists every numbered row in §2.
- A shared **comparator** consuming the E46-T01 report schema (also emitted by T09 and the load harnesses) that applies the §7.4 rules: ≥3 runs, median comparison, absolute-threshold check for hard budgets, ≤5 % regression check vs baseline, >+10 % for the bundle soft gate, and a clear failure message naming the budget, the stage (where applicable), the baseline, the measured value and the delta.
- CI wiring per budget with the right cadence — per-PR for the fast engine benches and bundle size; nightly for Electron, soaks, ingestion, k6/Locust load and replay; per-release-candidate for the manual reference-hardware items (startup absolute figure, 72 h soak).
- **Required-check** registration on `main` for every hard budget's gate, per `docs/plan/01-sdlc-and-branching.md`'s required-checks model.
- The **baseline-forward-only** workflow: a `bench/baselines/` directory, a documented "update performance baseline" PR template requiring harness output plus a written rationale, a CODEOWNERS entry so baseline changes need the Architect's approval, and a CI check that a baseline change is never bundled with a functional change in the same PR.
- **Soft-budget alerting**: Prometheus alert rules for sustained breach of the soft budgets (backend CPU/symbol, storage growth/day/symbol, bundle size trend) with the "repeated identical alerts are grouped with an occurrence count" behaviour required by US-OBS-004, and the epic's 3-consecutive-alert escalation to a tracked ticket.
- A **Grafana "Performance budgets" dashboard**: one panel per §2 budget showing the live/field value with the CI baseline drawn as a threshold line.
- The **injected-regression self-test**: a CI job (or a documented, periodically-executed procedure) that injects a 6 % regression into each hard-budget metric and asserts the gate fails — a gate nobody has ever seen fail is not a gate.

## Out of scope
- Writing new harnesses (T01, T06, T09 and the QA tickets own those) — this ticket consumes their outputs.
- Changing any budget target. If a measured reality cannot meet a documented budget, the budget is changed via a reviewed docs PR with the Architect (owned by the ticket that measured it), not by loosening a gate here.
- Post-GA capacity re-planning (§10.3).

## Acceptance criteria
```gherkin
Scenario: Every hard budget has a gate
  Given the budget registry
  Then every hard budget in docs/plan/06-performance-and-load-standard.md §2 has a registry entry with a harness, a metric key and a CI trigger
  And a CI check fails if a budget row exists in the markdown table but not in the registry

Scenario: A regression fails the build
  Given a 6% regression is injected into a hard-budget metric
  When the gate runs
  Then the build fails
  And the failure message names the budget, the measured value, the baseline and the percentage delta

Scenario: Runner noise does not fail the build
  Given three repeated harness runs with normal CI-runner variance and no real regression
  Then the gate compares medians and passes
  And the individual run values are recorded in the job output

Scenario: Baselines only move forward deliberately
  Given a pull request that changes a stored baseline
  Then the PR must contain the harness output and a written rationale
  And it requires Architect approval via CODEOWNERS
  And a PR that mixes a baseline change with a functional change is rejected by a CI check

Scenario: Soft budgets alarm rather than block
  Given backend CPU per symbol exceeds 0.5 vCPU for a sustained window
  Then an alert fires without blocking any build
  And repeated identical alerts are grouped with an occurrence count
  And three consecutive alerts escalate to a tracked ticket

Scenario: The dashboard shows budget versus reality
  Given the Performance budgets Grafana dashboard
  Then each §2 budget has a panel showing the current value with the CI baseline as a threshold line
```

## Technical notes / design
One comparator, one report schema, one registry. The failure mode to avoid is fifteen bespoke gate scripts that each interpret §7.4 slightly differently and rot at different rates; the registry plus comparator is what keeps the enforcement cost near zero as budgets change.

Hard budgets get **two** checks where both are meaningful: the absolute target (e.g. p95 frame ≤16.6 ms) and the ≤5 % relative-to-baseline check. A build that is inside the absolute target but 5 % worse than last week is still a regression worth catching, and a build that improved the baseline should ratchet the baseline forward (via the reviewed PR, never automatically).

Cadence honesty: putting a 24 h soak on a per-PR trigger would be absurd, so the registry's trigger field is load-bearing and the PR-level gate must state clearly which budgets it does *not* cover, so nobody mistakes a green PR for a fully-validated build. The release checklist in `docs/plan/07-release-and-prr.md` is where the nightly/per-release budgets get their sign-off.

Reference-hardware budgets (startup absolute, 72 h soak) cannot be CI-enforced on a CI runner; the registry marks them `trigger: release-manual` with a named owner and a procedure link, and the PRR gate checks the recorded evidence exists. Marking them as automated when they are not would be the worst outcome — a false sense of coverage.

## Test plan
- **Unit** (≥85 %): comparator arithmetic (median-of-3, percentage delta, absolute vs relative, soft vs hard); registry parsing and validation; the markdown-vs-registry drift check with a deliberately-desynced fixture.
- **Integration**: the injected-regression self-test per hard budget; the mixed-PR rejection check; the baseline-update workflow exercised end to end on a scratch branch.
- **Contract**: the harness report schema version pinned; a schema bump without a comparator update fails a test.
- **Operational**: alert rules unit-tested with `promtool`; grouping behaviour verified per US-OBS-004.

## Security notes
CI gates that publish performance artefacts must not publish profiling captures, heap snapshots or diagnostics bundles as build artefacts — those can contain order/account data (per E46-T04/T06/X01). Restrict published artefacts to the JSON reports and confirm those carry no market/order data. The baseline-update path is a supply-chain-adjacent control surface: CODEOWNERS approval on `bench/baselines/` prevents a silent "just bump the baseline" that would hide a real regression, and that control is itself worth a line in the security review (E46-X02).

## Accessibility notes
N/A — CI/infrastructure. Related: the axe-core a11y CI checks already required by `docs/plan/05-accessibility-standard.md` are unaffected by this work and must remain green.

## Performance notes
Meta-budget: the per-PR gate subset must complete within the existing CI time budget for `main` PRs; if the engine benches at 3 runs each exceed it, move the expensive scenarios to nightly and record that decision in the registry rather than reducing the repetition count below the §7.4 minimum of three.

## Observability
Grafana "Performance budgets" dashboard; alert rules for soft budgets with grouping; CI job output retained per run so a trend can be reconstructed; budget pass/fail published as a build status per budget id so the PRR checklist can read it mechanically.

## Definition of Done
- [ ] All six Gherkin scenarios verified.
- [ ] Budget registry covers every §2 row; drift check green.
- [ ] Required checks registered on `main` for every hard budget.
- [ ] Injected-regression self-test passes for each hard budget (evidence in the ticket).
- [ ] Baseline-update PR template, CODEOWNERS entry and mixed-PR rejection check in place.
- [ ] Soft-budget alert rules merged as version-controlled config (US-OBS-004 NFR) and `promtool`-tested.
- [ ] Grafana dashboard merged.
- [ ] `docs/plan/06-performance-and-load-standard.md` §7.4 and `docs/plan/07-release-and-prr.md` updated to reference the registry and the release-manual budgets.
- [ ] Coverage ≥85 % on new comparator/registry code.
- [ ] Reviewed by DevSecOps + the Architect.

## Dependencies
All optimisation tickets land first so the baselines captured here are the post-optimisation numbers: **E46-T02, T03, T05, T07, T08, T09**. Baselining before the optimisations would lock in the numbers E46 exists to improve.

## Branch
`feat/e46-perf-ci-budget-gates`. PR size: registry+comparator one PR, CI wiring a second, alerting+dashboard a third.

## References
`docs/plan/06-performance-and-load-standard.md` §2, §7.4, §9 · `docs/plan/26-chart-engine-design.md` §13 · `docs/plan/01-sdlc-and-branching.md` (required checks) · `docs/plan/07-release-and-prr.md` · `docs/plan/30-release-roadmap.md` §9.4 · `docs/plan/11-user-stories.md` US-OBS-004
"""))

tickets.append(T("E46-T11", "Task",
    "Write ADR-0016 on budget enforcement and seed the perf-incidents log",
    ["type/tech", "area/backend-platform", "priority/p2", "perf", "type/docs"],
    "docs", "Sprint 25", "P2 Medium", "Architecture", "R2 Render performance", 2, "E46",
    ["E46-T10", "E46-K01"],
    """## Context
`docs/plan/06-performance-and-load-standard.md` §8 step 6 requires "a short written note (added to a running perf-incidents log referenced from `07-release-and-prr.md`)" for any hard-budget production-impacting regression — the log is referenced but has never been created. §8 step 7 requires a quarterly/per-major-release full profiling pass by the Architect plus a rotating engineer, which needs a documented procedure and an owner, not just a sentence.

Separately, E46 makes several decisions that outlive it and that a future engineer will otherwise have to reverse-engineer from CI config: the budget-registry-plus-comparator model, the baseline-forward-only policy with CODEOWNERS approval, the split between CI-enforced and release-manual budgets, the profiling toolchain chosen by E46-K01, and the handling rules for profiling artefacts. `docs/plan/02-definition-of-ready-done.md` §5.2 requires a spike's decision to be recorded as an ADR; the existing ADR set runs to ADR-0015 (`docs/plan/27-adrs/`).

Note the numbering collision risk: E44-T06 also writes an ADR for environment separation. Confirm the next free number against `docs/plan/27-adrs/` at implementation time and use it; this ticket says ADR-0016 for planning purposes and the actual number must be reconciled, not assumed.

## Scope / Deliverables
- **ADR** in `docs/plan/27-adrs/` (next free number; referenced here as ADR-0016) titled "Performance budget enforcement and baseline policy", following the existing ADR template, covering: context (why R5 needed this), the decision (registry + shared comparator + §7.4 rules as code), the CI-enforced vs release-manual split and why reference-hardware budgets cannot be CI-gated, the baseline-forward-only policy and its CODEOWNERS control, the profiling toolchain chosen in E46-K01 with its measured overheads, the profiling-artefact handling rules, the consequences (what future work this constrains and what it costs), and the alternatives rejected with reasons.
- **Perf-incidents log** (`docs/plan/` or `docs/ops/`, agreed with the Architect — reference it from `07-release-and-prr.md` either way) with a fixed entry template: date, budget affected, how it was detected, measured before/after, root cause, fix, **why the CI gate did not catch it earlier**, and the follow-up action. Seed it with any regression found and fixed during E46 itself so it starts populated rather than aspirational.
- **Quarterly full-profiling-pass procedure** (§8 step 7) written down: what is run (the §3.2/§6.4 worst-case stress composite), by whom (Architect + rotating engineer), what is recorded, where the output goes, and how a finding becomes a ticket. Add it to the release checklist in `07-release-and-prr.md` so it is triggered rather than remembered.
- **Doc reconciliation**: update `docs/plan/06-performance-and-load-standard.md` where E46 measured something different from the planned number — with the divergence explained rather than silently rewritten (an epic DoD item). Update §7.3's variance band (from E46-T06), §2 budget #10's `workspace_ready` definition (from E46-T09), §7.4's registry reference (from E46-T10), and §4.3's stage allocation if E46-T02 changed it.
- Cross-reference the ADR from `docs/plan/26-chart-engine-design.md` §13 and `docs/plan/20-architecture.md` §13.2 so an engineer arriving at either budget table finds the enforcement model.

## Out of scope
- Writing the GA runbooks and user-facing documentation (E48).
- Creating new budgets or changing targets.
- The E46-K01 spike's own ADR entry if K01 chose to file a separate one — in that case this ADR references it rather than duplicating it.

## Acceptance criteria
```gherkin
Scenario: The ADR is complete and numbered correctly
  Given the ADR is submitted
  Then it uses the next free number verified against docs/plan/27-adrs/ at the time of writing
  And it contains context, decision, consequences and rejected alternatives per the existing ADR template
  And it records the profiling toolchain decision from E46-K01 with its measured overhead figures

Scenario: The perf-incidents log exists and is referenced
  Given the release documentation
  Then docs/plan/07-release-and-prr.md links the perf-incidents log
  And the log contains a fixed entry template including a "why the CI gate did not catch it" field
  And at least one real entry from E46's own work is present

Scenario: The quarterly profiling pass is triggerable, not remembered
  Given the release checklist
  Then it contains the full-profiling-pass step with a named owner role, the scenario to run and the artefact to produce

Scenario: Divergences are explained, not hidden
  Given a budget whose measured reality differed from the planned number during E46
  Then docs/plan/06-performance-and-load-standard.md states the new number and the reason it changed, with the decision's approver named
```

## Technical notes / design
The "why the CI gate did not catch it" field is the highest-value part of the incident template: every entry that answers it either produces a new gate or a documented, accepted blind spot, which is how the enforcement model improves instead of ossifying.

Keep the ADR honest about cost. The registry-plus-comparator model buys drift resistance at the price of CI time and a mandatory baseline-update ritual; a future team that finds the ritual burdensome should be able to read why it exists rather than deleting it and rediscovering the reason.

## Test plan
- Docs CI: markdown link checker green (all relative anchors resolve); ADR template conformance check if one exists; the registry-vs-§2 drift check from E46-T10 green after the doc edits.
- Review: Architect approval on the ADR; DevSecOps review of the artefact-handling rules.
- No code, so no coverage target; the doc build must pass.

## Security notes
The ADR documents the profiling-artefact handling rules (gitignored paths, access control, never attached to issues, deletion after analysis) that E46-T04, T06 and X01 depend on — this is the durable home for those rules, so Security must review the wording. The perf-incidents log must itself contain no order, account or credential data: incident entries reference artefacts by path and access-controlled location, never inline them.

## Accessibility notes
N/A — documentation. The docs must meet the repo's existing markdown accessibility conventions (heading hierarchy, table headers, descriptive link text rather than "here").

## Performance notes
N/A — no runtime impact. The documented budgets are the subject, not the object.

## Observability
Documents the "Performance budgets" dashboard and the soft-budget alert routes from E46-T10 so an on-call reader can find them from the release docs.

## Definition of Done
- [ ] All four Gherkin scenarios satisfied.
- [ ] ADR merged with the correct next-free number and Architect approval.
- [ ] Perf-incidents log created, templated, seeded and linked from `07-release-and-prr.md`.
- [ ] Quarterly profiling-pass procedure added to the release checklist with a named owner role.
- [ ] `06-performance-and-load-standard.md` reconciled with measured reality; every divergence explained and approved.
- [ ] Cross-references added in `26-chart-engine-design.md` §13 and `20-architecture.md` §13.2.
- [ ] Docs CI green; Security reviewed the artefact-handling section.

## Dependencies
- **E46-T10** must land first — the ADR documents the enforcement model as built, not as imagined.
- **E46-K01** supplies the toolchain decision and its measured overheads.

## Branch
`docs/e46-adr-budget-enforcement`. PR size: small; docs-only.

## References
`docs/plan/06-performance-and-load-standard.md` §4.3, §7.3, §7.4, §8 · `docs/plan/07-release-and-prr.md` · `docs/plan/27-adrs/` (ADR-0001..0015, template) · `docs/plan/02-definition-of-ready-done.md` §5.2 · `docs/plan/26-chart-engine-design.md` §13 · `docs/plan/20-architecture.md` §13.2
"""))
