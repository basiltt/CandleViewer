# ADR-0016 — Statechart contracts, executed by `xstate-statemachine`, for long-lived lifecycles

- Status: **Accepted (2026-09-24)** — pin `xstate-statemachine==0.9.1` (tag `v0.9.1` = `45bb7f3`, `sha256:d832d4d9a17b7b8003f61fa0714a8e57eaff316bcd5dd699d81d410362687162`, PEP 740 attested). **Owner decision: full adoption** — every catalogue lifecycle B1–B20 is executed by the library via `cv.statechart.factory` from the first line of code; there is no in-house shim and no dual-runtime harness. See **§ Decision (final)** below. Parts 2–3 of the original decision outcome and Amendments 1–14 are retained as history. *(Previous status: Proposed (gated); Amendment 14 = ADOPT WITH CONSTRAINTS, decision-table row 8.)*
- **Pin (Amendment 8):** **git commit `6db65d8`** plus its **source sha256**, evaluation only — endorsement withheld. **Key the pin on the commit, never the version string**; `__version__` still reports `0.8.0` on it while the CHANGELOG targets 0.8.1, eight verification passes running. **Do not pin a 0.8.1 tag cut at this commit** — it would release R8-01 (a silent, unbounded, unobservable priority-lane livelock plus silent destruction of external priority events) and remove the commit-keyed escape hatch. On adoption the pin becomes `xstate-statemachine == 0.8.1` **once tagged, and only if the tag is cut after R8-01 lands**. A **vendored copy per MUST-08** is carried for the non-order machines going live now.
- **Constraints in force (Amendment 8): CV-C01…CV-C45**, per `docs/research/xstate/49-r8-final-readiness-verdict.md` §7. **Retired:** CV-C38 (the engine bounds invoke cycles itself now — CV-LINT-XS16 downgraded from error to warning), CV-C31′ (retired on the async lane; re-issued as CV-C31″ for plain-`def` services only), and the `maxIterations`-is-inert annotation (it is live again and lane-independent). **Widened:** CV-C42 — `priority=True` is now forbidden **everywhere, any origin**. **New:** CV-C43 (out-of-process progress supervisor; no in-process watchdog may be the sole order-path detector), CV-C44 (per-child bring-up bound + coroutine entry actions on invoke-bearing states), CV-C45 (completion events never accepted from a wire). **CV-C32 stands, and for the first time comfortably** — the coroutine lane is now the healthy one on every track, and CV-C32 is exactly what keeps us off the uncancellable, un-rolled-back `def` path.
- **Pin (Amendment 7):** **git commit `221ce7c`**, evaluation only — endorsement withheld. *(superseded by Amendment 8)*
- **Constraints in force (Amendment 7): CV-C01…CV-C42**, per `docs/research/xstate/44-r7-final-readiness-verdict.md` §7. **Retired:** W-04a (#170 — `Receipt.denied` alone is a correct discriminator again; the W-04b half stands), CV-C37 (#171 fixed the children-ready race), and CV-C36's original rationale (the rule stands on new grounds). **New:** CV-C38 (no unguarded invoke cycle), CV-C39 (`await start()` always bounded), CV-C40 (no snapshot before the post-start settle observation), CV-C41 (root-only snapshots; child state via explicit `sendTo`), CV-C42 (`priority=True` forbidden outside wrapper code). **CV-C32 stands, uncomfortably** — it is what keeps R6-09's downgrade valid and exactly what puts every machine on R7-01's unprotected lane.
- **Pin (Amendment 6):** **git commit `cec108b`**, evaluation only — endorsement withheld. **Key the pin on the commit, never the version string**; `__version__` still reports `0.8.0` on it while the CHANGELOG targets 0.8.1, six verification passes running. **Do not pin a 0.8.1 tag cut at this commit** — it would release two silent unbounded-CPU Blockers (R6-01, R6-03) and remove the commit-keyed escape hatch. *(superseded by Amendment 7)*
- **Pin (Amendment 3, superseded):** `xstate-statemachine == 0.8.1` **once tagged**; until then **git commit `3c527b0d04c0d2d0ebb565af7e9e905f7178f620`** with source sha256. **Key the pin on the commit, never the version string** — `__version__` still reports `0.8.0` on that commit while its CHANGELOG targets 0.8.1, two verification passes running. **The pin records what was tested, not what is endorsed:** the gate decision on this commit is DEFER.
- **Constraints in force (Amendment 6): CV-C01…CV-C37**, per `docs/research/xstate/39-r6-final-readiness-verdict.md` §7. **Retired:** CV-C27 (→ the one-line residual CV-C27′), CV-C30 (parallel regions safe again — #142/#143), CV-C31 (**retired and inverted** — #145 makes `"fail"` safe; R6-03 makes `"rollback"` the dangerous policy on the order path), CV-C34 (done). **CV-C32 stands**, restated per-engine — R6-09's downgrade depends on it, and sync parity is therefore *unavailable* for any machine with services. **New:** CV-C27′ (`state_ids ⊆ configuration` on restore), CV-C31′ (no `"rollback"` with a raisable entry action on an `invoke`-carrying state), CV-C35 (no `always` into an invoked child), CV-C36 (every `send_threadsafe` future is read), CV-C37 (`children_ready()` barrier — `await start()` is not "the machine is up").
- **Constraints in force (Amendment 3, superseded):** **CV-C01…CV-C22**, per `docs/research/xstate/26-verify-3c527b0-verdict.md` §5. CV-C15's case-insensitivity clause is **retired** and the rule is **re-scoped** to the six `ENGINE_EVENT_SHAPES` prefixes; CV-C06's `deferred_count` clause is **withdrawn as unsound** and replaced by a prohibition; CV-C19 (never forge `Event(system=True)`), CV-C20 (persistence owns the mailbox across a snapshot boundary), CV-C21 (`onError` reads `ErrorEvent.error`) and CV-C22 (no global `-W error::DeprecationWarning`) are **new**. Amendment 2's retirements (CV-C06 fresh-`Event`, CV-C14 gateway validation) and additions (CV-C16…CV-C18) stand.
- Date: 2026-09-15 (amended 2026-09-17)
- Deciders: Owner (as both CandleViewer owner and `basiltt/xstate-statemachine` maintainer), Architect, Backend lead, QA lead, DevSecOps
- Consulted: `docs/research/xstate/01-library-core.md`, `02-quality-and-tests.md`, `03-docs-examples-gaps.md`, `04-performance-concurrency.md`, `05-semantics-probes.md`, `06-alternatives-ecosystem.md`, `10-fit-analysis.md` (Parts A–E, B1–B20), `11-adversarial-review.md` (§3 MUST/MUST-NOT, §5 adopt-for / do-not-use-for), `12-challenge-register.md` (LC-01…LC-62, adoption-gate summary)
- Related: ADR-0004 (modular monolith / internal bus), ADR-0006 (OMS state machine), ADR-0007 (rule IR), ADR-0008 (trade-group fan-out), ADR-0012 (testing pyramid), ADR-0013 (CI pipeline), `docs/plan/28-statechart-catalogue.md`, `docs/plan/24-internal-schemas.md`, `docs/plan/20-architecture.md` §3–§4

---

## Context and problem statement

CandleViewer contains roughly twenty **long-lived, event-driven lifecycles**: the order, the trade group and its legs, four emulated algos, the native-SL protection invariant, the rule instance, the alert, the recording and replay sessions, the exchange connection, the book-health FSM, the auth session, the live-enablement gate, the kill switch, the reconciliation job and the risk lockout. Every one of these is, today, planned as a hand-rolled Python state machine scattered across `24-internal-schemas.md` prose, enum columns and per-module `if status ==` ladders. That is how the existing E08/E16/E26/E29/E32/E33/E34/E35/E39/E40/E44/E45 tickets are written.

Hand-rolled lifecycles have two costs that this project cannot absorb quietly:

1. **They are not reviewable as a whole.** The order lifecycle's correctness argument lives in thirteen places. A reviewer cannot answer "can a fill be dropped while a cancel is in flight?" without reading all of them. The adversarial review's INV-5 ("no delivered `exec_id` is ever unaccounted for") is exactly the kind of property that a scattered implementation makes untestable and a declarative one makes trivially testable.
2. **They drift from the document that specifies them.** `24-internal-schemas.md` §8.2 and the implementation are related by good intentions, not by CI.

A candidate runtime exists and is unusually convenient: `basiltt/xstate-statemachine` 0.7.0 — an XState-v5-shaped Python statechart interpreter, 12,104 LOC, zero runtime dependencies, MIT, **maintained by this project's owner**. Studies `01`–`06`, the fit analysis `10` and the adversarial review `11` evaluated it in depth, including twenty-eight new probes and nine benchmarks written for the purpose.

The result was not a clean yes. `12-challenge-register.md` records **62 deduplicated findings**, of which **7 are Blockers** and **19 are High** *relative to a trading OMS*. The Blockers share one root cause, stated in `11` §5 as the one-line version of the whole review:

> The library is correct where correctness is hardest and wrong where wrongness is quietest.

Specifically: an action that raises still commits its transition (`LC-01`) and that broken state is then **durably persisted as truth** (`LC-15`); an `always` self-target deadlocks silently (`LC-02`); events with no handler in the current state are silently discarded (`LC-03`); the mandated deferral buffer is persisted but never drained after a crash (`LC-17`); `sendTo` cannot address an actor by its `invoke` id, so events go to the wrong child or nowhere (`LC-16`). Every one has a CandleViewer-side mitigation, and every mitigation **fails silently if a developer forgets it**.

The owner's position is therefore explicit and is the premise of this ADR:

> **CandleViewer will not adopt `basiltt/xstate-statemachine` until the Blocker and High items in `12-challenge-register.md` are fixed *upstream* and re-verified by the adoption gate in `docs/research/xstate/20-adoption-gate.md`.**

That leaves a real question that must be answered *now*, not in twelve months: **what shape should the twenty lifecycles be built in, while the library is not adopted?**

Doing nothing and hand-rolling twenty ad-hoc machines means that if the gate ever passes, adoption is a rewrite — which means it will never happen, which means the research was wasted. Blocking the lifecycles on the gate means R3 does not ship.

## Decision drivers

- **The lifecycles must be specified declaratively and reviewably, from day one.** This is worth doing on its own merits even if the library is never adopted.
- **Adoption must remain a swap, not a rewrite.** Whatever executes the lifecycles in R0–R3 must consume the same artefact the library would.
- **The hot paths must be structurally excluded.** Measured: a statechart transition is 33 µs against 15–60 µs of real work in the book engine; plain Python evaluates rule predicates **744× faster** than a statechart fleet; a statechart admission-control decision is **~238,000× slower** than a token bucket and cannot answer synchronously at all. These are architectural ratios that better hardware does not fix.
- **Safety enforcement must never depend on an interpreter.** Kill switch, live gate, risk caps and rate budgets must be synchronous flags/functions.
- **The gate must be mechanical.** "Is it fixed upstream?" must be answered by a script against a released version, not by reading a changelog.
- **The owner is the upstream maintainer.** Upstream fixes are a scheduling decision, not a hope — which makes a *gated* adoption honest rather than aspirational.

## Considered options

1. **Design every long-lived lifecycle as XState-v5-compatible statechart JSON from day one; execute it initially with a thin in-house interpreter shim; swap to `xstate-statemachine` only when the adoption gate passes.**
2. **Adopt `xstate-statemachine` now**, with the twelve MUST mitigations from `11` §3 as house rules.
3. **Hand-roll all twenty lifecycles as ordinary Python**, treat the research as a negative result, and close the question.
4. **Adopt a different runtime** (`transitions`, `python-statemachine`, `sismic` — see `06-alternatives-ecosystem.md`).
5. **Author the JSON as documentation only**, and hand-roll the implementations without any conformance relationship between them.

## Decision outcome

**Chosen: option 1.** The decision has three parts, and they have different statuses.

### Part 1 — Binding now: statechart JSON is the contract

Every lifecycle on the **adopt-for list** (`11` §5, enumerated below as B1–B14, B16–B20) is specified as an **XState-v5-compatible statechart JSON document**, checked into the repository, validated in CI, and published in `docs/plan/28-statechart-catalogue.md`. The JSON is:

- **The normative behavioural contract** for that lifecycle. Where the JSON and a module's Python disagree, the JSON is right and the Python is a defect.
- **Runtime-agnostic.** It names states, events, guards, actions and services. It does not name an interpreter, a library or a Python module.
- **Stately-compatible.** It must load in the Stately editor / `@xstate/*` tooling unmodified, so the owner can *look at* the order lifecycle as a diagram generated from the artefact that runs (`10` C4.3).
- **Hashed.** `machine_hash` is computed in CI; a hash change without a version bump or a registered upcaster with a golden-snapshot test **fails the build** (MUST-12).

This part is binding from the first lifecycle ticket, independent of any library decision.

### Part 2 — *(SUPERSEDED 2026-09-24 by Decision (final): no shim is built)* — execution by a thin in-house interpreter shim

Until the gate passes, the JSON is executed by **`services/api/candleviewer/statechart/`** — a deliberately small in-house interpreter shim (target ≤ 1,500 LOC) implementing the subset of XState v5 the catalogue actually uses: compound states, parallel regions, guarded transition arrays with first-match, `entry`/`exit` actions, `always`, final states, `tags`, wildcard `*` handlers, and snapshot/restore.

The shim is written against the *corrected* semantics — i.e. the ones the Blockers describe as wrong in the library:

| Shim behaviour | Closes |
|---|---|
| An action that raises **aborts the transition and rolls back**; the machine goes to `quarantined` with `_fault` set; the snapshot writer refuses to persist a faulted context | LC-01, LC-15 |
| An explicit self-target is **external** by default (XState v5 semantics); `always` with a self-target is a **build-time error** | LC-02, LC-04 |
| An event with no handler in the current state is **deferred, counted and logged**, never discarded | LC-03 |
| The deferral buffer is drained **at boot, unconditionally, before invokes are re-driven** | LC-17 |
| Child actors are addressed through an **application-owned registry**, never by library id resolution | LC-16 |
| Targets are **absolute only**, resolved against the state tree at build time; unresolvable or ambiguous targets fail CI | LC-06, LC-07, LC-08 |
| A guard that raises is a **loud error** and is treated as **deny** | LC-09 |
| Restore merges machine-default context keys over the restored context | LC-22 |
| Timing is external: the shim has no `after`; deadlines are absolute `*_us` timestamps in context, armed by the `MonotonicScheduler` | LC-20, LC-26, LC-27 |

The shim is **not** a reimplementation of the library and is not intended to grow into one. It exists because the catalogue subset is small, and because the seven Blockers are exactly the places where we need behaviour the library does not currently offer.

### Part 3 — *(RESOLVED 2026-09-24: gate passed, row 8; library adopted fully)* — Gated: `xstate-statemachine` replaces the shim if and only if the gate passes

`xstate-statemachine` becomes the execution runtime for the catalogue **only** when **all** of the following hold, verified by `docs/research/xstate/gate/run_gate.py` against a released version and reviewed at the Sprint 08 go/no-go (`E50-X01`):

1. **Every Blocker in `12-challenge-register.md` is closed upstream** — `LC-01`, `LC-02`, `LC-03`, `LC-15`, `LC-16`, `LC-17` — with the corresponding repro under `docs/research/xstate/issues/repro/` now **passing** against the released version.
2. **Every High item has either an upstream fix or a documented, tested, mechanically enforced CandleViewer mitigation** — the 19 items listed in `12` "High (19)".
3. **The conformance suite passes on both runtimes.** Every machine in `28-statechart-catalogue.md` produces an identical state/action trace under the shim and under the library for the same event sequence (`E50-T03`).
4. **The performance gate holds** at the budgets in `06-performance-and-load-standard.md`: ≥ 8,000 machine-ev/s aggregate with 500 resident order machines, and the per-family latency budgets of `10` C6.
5. **`tests/xstate_contract/` runs in under 60 s**, because a gate slow enough to be skipped is not a gate (`11` "Reconsider adoption if").
6. **The prerequisites have shipped**: the machine-definition linter (`E29-T10`), `SafeInterpreter`/`MachineGateway` (`E29-T11`), machine persistence with the versioned envelope (`E29-T12`), and the supervisor reaper. MUST-09 is explicit that these ship *before* the first statechart, not alongside.
7. **The pin and the vendor copy exist**: `xstate-statemachine == <version>` exactly, with source sha256, plus `third_party/xstate_statemachine/` and a documented one-line import switch (MUST-07, MUST-08).

If the gate passes, adoption is a **feature flag** (`CV_STATECHART_RUNTIME=shim|library`, default `shim`) flipped per machine family, with the conformance harness green on both sides — not a code change in any lifecycle module. If the gate does not pass by the Sprint 08 review, the shim remains the runtime and this ADR is re-reviewed at the next train boundary; there is no schedule dependency on the outcome.

### Scope — what is a statechart, and what is never one

**Adopt-for list (statechart contracts, `11` §5 "Adopt for"):**

| # | Lifecycle | Catalogue | Owning epic |
|---|---|---|---|
| B1 | Order (two-region: `lifecycle` × `protection`) | §B1 | E29 |
| B2 | TradeGroup | §B2 | E34 |
| B3 | TradeGroupLeg (incl. nested unwind) | §B3 | E34 |
| B4 | EmulatedAlgo: OCO | §B4 | E33 |
| B5 | EmulatedAlgo: Iceberg | §B5 | E33 |
| B6 | EmulatedAlgo: TWAP | §B6 | E33 |
| B7 | EmulatedAlgo: Chase | §B7 | E33 |
| B8 | Position protection / native-SL invariant | §B8 | E32 |
| B9 | Rule instance **lifecycle only** | §B9 | E35 |
| B10 | Alert lifecycle | §B10 | E40 |
| B11 | RecordingSession | §B11 | E16 |
| B12 | ReplaySession | §B12 | E26 |
| B13 | ExchangeConnection | §B13 | E08 |
| B14 | Book **health** FSM (data path excluded) | §B14 | E08 |
| B16 | AuthSession / step-up | §B16 | E09 |
| B17 | LiveEnablement gate | §B17 | E44 |
| B18 | KillSwitch (record-and-orchestrate only) | §B18 | E39 |
| B19 | Reconciliation job | §B19 | E45 |
| B20 | RiskLockout | §B20 | E39 |

B15 (paper-account liquidation, §B15) is catalogued as a contract because it is a genuine three-state FSM, but the surrounding paper **matcher** is on the do-not-use-for list.

**Do-not-use-for list (never a statechart, in any form, including internal actions-only transitions — `11` §5, MUSTNOT-01/02/05):**

1. Book-engine delta application, bar builders, footprint aggregation.
2. Per-tick rule **condition evaluation** (the rule *lifecycle* is B9; the *evaluation* is a compiled Python predicate).
3. Paper-matcher fill model, queue-position estimator, fee/funding arithmetic.
4. Per-account rate-limit governor / fan-out admission control.
5. Any synchronous safety **enforcement** point — kill switch, live gate, risk caps, rate budgets. A statechart may *record and orchestrate* these; a synchronous flag or function **enforces** them.

### Binding constraints imported from `11-adversarial-review.md` §3

These are normative for every catalogue machine, under either runtime, and are enforced by the machine-definition linter (`E29-T10`) and the conformance suite (`E50-T03`) — not by review discipline.

**MUST NOT**

| # | Constraint |
|---|---|
| MUSTNOT-01 | No hot-path work (book deltas, bar builders, footprint aggregation, paper fill/queue arithmetic, per-tick rule evaluation) in a statechart, in any form. |
| MUSTNOT-02 | The per-account rate-limit governor / fan-out admission control is not a statechart. |
| MUSTNOT-03 | No path faster than ~100 Hz queries an interpreter. The machine publishes a plain `bool`/enum on state entry; hot paths read that. |
| MUSTNOT-04 | No reliance on event ordering across a defer/drain boundary, nor on interpreter FIFO as an OMS ordering guarantee. `apply_fill` and all aggregation actions are order-independent and sort by `(ts_exec, seq)`. |
| MUSTNOT-05 | No statechart is an enforcement point for a safety decision. |
| MUSTNOT-06 | No `SyncInterpreter`, ever. |
| MUSTNOT-07 | No bus message is acked before the resulting transition is observed. |
| MUSTNOT-08 | No more than 200 concurrently invoked child actors per process without re-measuring. |
| MUSTNOT-09 | No no-op upcaster is written to clear a `machine_hash` mismatch. |

**MUST**

| # | Constraint |
|---|---|
| MUST-01 | Snapshot persistence is gated on transition cleanliness; a context carrying `_fault` is never persisted — a `quarantined` marker row is written and P1 alerts. |
| MUST-02 | `machine_events` (write-ahead) is the sole book of record for the order family, with `actions_run` populated from the actual execution list. |
| MUST-03 | `_deferred` is drained at boot, unconditionally, **before** invokes are re-driven. |
| MUST-04 | Any machine with a non-empty `_deferred` for > 5 s alerts (`cv_machine_deferred_depth`). |
| MUST-05 | The rule trigger pre-filter achieves **≥ 99 %** rejection, asserted as a test. Below 99 %, rule dispatch is disabled and alerts. |
| MUST-06 | Restore merges `{**machine_defaults, **snapshot_context}`. |
| MUST-07 | The library, if adopted, is pinned `==` exactly, with source sha256 and the contract-suite pass as one gated artefact. |
| MUST-08 | The library, if adopted, is vendored at the pinned version with a one-line import switch and a quarterly vendored-copy test. |
| MUST-09 | The machine-definition linter ships **before** the first statechart. |
| MUST-10 | `cv_machine_unhandled_events_total{kind,event}` exists, and CI fails if any event name a gateway sends is absent from the target machine's descriptor set. |
| MUST-11 | Every machine reaching a terminal state is explicitly stopped and evicted by a supervisor reaper; `cv_machine_live_count{kind}` is exported and alerts on monotonic growth. |
| MUST-12 | `machine_hash` is computed in CI; a shipped machine's hash change without a version bump or a registered upcaster with a golden-snapshot test fails the build. |

Plus the Part-A house style from `10-fit-analysis.md`: no action may raise (A1); timing lives outside the statechart (A2); every transient state has an explicit deferral handler (A3); self-transitions declare `reenter: true` (A4); absolute targets only, validated at build time (A5); guards are pure, total and deny-polarity on safety paths (A6); the statechart is never the book of record (A7); operational hygiene (A8).

### Consequences

Positive:

- **The twenty lifecycles become reviewable artefacts.** "Can a fill be dropped while a cancel is in flight?" is answered by reading one JSON document and one invariant test, not thirteen modules.
- **The document and the code cannot drift**, because the document *is* the code's input and CI hashes it.
- **Adoption stays cheap and reversible.** The decision that usually costs a rewrite costs a flag flip, and the conformance harness makes "did the swap change behaviour?" a green/red answer rather than a judgement call.
- **The hot-path exclusion is written down before anyone is tempted.** The governor (CR-5) is the canonical example: it has states, it has transitions, it looks textbook, and it must not be one. An ADR is where that is recorded.
- **The upstream relationship is productive rather than blocking.** The gate runner, the conformance suite and the benchmarks are contributable artefacts (`E50-C01`/`E50-C02`), and the owner is the maintainer.
- **A genuine diagram of the order lifecycle exists**, generated from the running contract, which is the single most useful review artefact on the order path.

Negative / risks:

- **The shim is real code with real cost** (≈ 1,500 LOC plus tests) and it is on the order path. Mitigated by keeping it to the catalogue subset, by the conformance suite testing it as hard as it tests the library, and by the fact that the alternative — twenty ad-hoc machines — is *more* code with *less* structure.
- **Two runtimes must be kept green** for the period between the first statechart and the go/no-go. Mitigated by the feature-flagged conformance harness (`E50-T03`) running both in one CI job; the cost is CI minutes, not developer time.
- **A shim that is comfortable enough reduces the pressure to ever adopt the library.** Accepted and made explicit: `E50-X01` is a real decision ticket with "keep the shim permanently" as a first-class outcome, not a failure state.
- **Authoring twenty JSON contracts is front-loaded work** (E50 carries 47 pts across R0–R1) that produces no user-visible feature. Mitigated by the fact that it is work the lifecycle epics would otherwise do worse and later, and by scheduling it against the R0/R1 buffer rather than against feature scope (see `30-release-roadmap.md` §3.1).
- **JSON is a poor authoring format.** Mitigated by Stately-editor round-tripping (`E29-K02`) and by the schema/lint gate catching the class of mistakes a type system would.
- **The gate may never pass.** Explicitly acceptable. Nothing in R0–R5 is scheduled behind it.

### Why not the alternatives

- **Option 2 — adopt now.** Refused by the owner, and the refusal is well-founded: seven Blockers whose mitigations all fail *silently*, on the path where a silent failure is a financial loss. `11` is explicit that the cost of adoption is not the library but "the linter, the contract suite, the boot procedure and the reaper", and those must exist under either runtime anyway.
- **Option 3 — hand-roll everything, close the question.** Discards the reviewability win, which is the larger of the two benefits, and guarantees that adoption can never happen later because it would be a rewrite. It also leaves the hot-path exclusion undocumented, which is how the governor gets built as a statechart by someone reading only `24`.
- **Option 4 — a different runtime.** `06-alternatives-ecosystem.md` found none that combine XState-v5 JSON compatibility, parallel regions, invoke/actor semantics, zero dependencies and a maintainer we control. Switching runtimes does not remove the need for the JSON contract; it only changes which interpreter reads it — which is exactly what this ADR makes a swap.
- **Option 5 — JSON as documentation only.** This is the failure mode this ADR exists to prevent. An unenforced contract is a comment. The conformance relationship (`E50-T02`/`E50-T03`) is the whole mechanism.

## Validation

- **`E50-T01`/`E50-T02`** — every catalogue machine is authored, schema-validated, target-resolved and hashed in CI; a deliberately broken machine fails the gate (negative test).
- **`E50-T03`** — the contract suite (`tests/xstate_contract/`) runs each machine's JSON on `xstate-statemachine` via `cv.statechart.factory`, asserting the catalogue's golden state/action traces; any divergence fails the build. *(2026-09-24: no shim, no `CV_STATECHART_RUNTIME` switch.)*
- **`E50-T04`** — `docs/research/xstate/gate/run_gate.py` runs as a scheduled CI job against new upstream releases; a newly passing repro is reported, and a regression in a previously passing repro is escalated.
- **`E50-C0*`** — the conformance suite and benchmarks are offered upstream, so the gate criteria are also the library's own regression tests.
- **`E50-X01`** — *(closed 2026-09-24: outcome **adopt**, see Decision (final))* Adoption go/no-go review at **Sprint 08**, with the gate report as the input and one of three outcomes recorded here as a dated amendment: *adopt*, *defer to the next train boundary*, or *keep the shim permanently and close ADR-0016's Part 3*.
- Standing: `tests/xstate_contract/` under 60 s; `cv_machine_*` metrics live; the machine-definition linter blocking; the reaper's `cv_machine_live_count{kind}` flat across a 24 h soak.

## References

- `docs/research/xstate/10-fit-analysis.md` — Part A (ground rules), Part B (B1–B20), Part C (hosting, bus, persistence, observability, testing, performance), Part E (plan/backlog change list)
- `docs/research/xstate/11-adversarial-review.md` — §1 confirmed risks, §2 refutations, **§3 required design constraints**, **§5 final recommendation**
- `docs/research/xstate/12-challenge-register.md` — LC-01…LC-62 and the adoption-gate summary
- `docs/research/xstate/20-adoption-gate.md` — the gate specification (criteria, runner, reporting)
- `docs/research/xstate/gate/run_gate.py` — the gate runner
- `docs/plan/28-statechart-catalogue.md` — the twenty contracts
- `docs/plan/backlog/E50.json` — the epic implementing this ADR

---

## Decision (final) — 2026-09-24: full adoption of `xstate-statemachine==0.9.1`

**Status: Accepted.** This section supersedes Parts 2 and 3 of *Decision outcome* and every amendment below where they conflict. Part 1 (statechart JSON is the contract) stands unchanged. The amendments are retained as the history of how the gate was passed (14 verification rounds; final record `docs/research/xstate/79-r14-final-readiness-verdict.md`).

### Runtime

- **The runtime for every catalogue lifecycle (B1–B20, `28-statechart-catalogue.md`) is `xstate-statemachine`**, constructed only through `cv/statechart/factory.py` (`cv.statechart.factory`). No other module may call `create_machine`, `Interpreter`, or `Interpreter.from_snapshot` (lint `CV-LINT-XS01`).
- **No in-house shim, no dual-runtime harness, no `CV_STATECHART_RUNTIME` switch, no phased shim retirement.** The contract suite (`tests/xstate_contract/`) runs the catalogue JSON against the library on both engines (`Interpreter` and — for contract tests only — the `def`/`async def` service spellings); it is not a parity harness.
- Gate result carried in: decision-table **row 8, ADOPT WITH CONSTRAINTS**. Library board 0 Blocker · 0 High · 1 Medium (`R14-01`, contained by `CV-C68`). The remaining constraints are **our architecture**, not library defects.

### Hot-path exclusions (permanent)

Unchanged from *Scope* above and MUSTNOT-01…03: book deltas, bar builders, footprint aggregation, paper fill/queue arithmetic, **per-tick rule condition evaluation** (BENCH-2 measured 380.9 ev/s against a 2,000 ev/s bar — architectural, not expected to close with any Python engine), the rate-limit governor, and all synchronous safety enforcement points stay plain Python. Charts are lifecycle-only, fed through a ≥99 % pre-filter. Orders run on a dedicated order loop (BENCH-1). `after:` / `raise(delay=)` are permitted only for coarse timeouts with ≥250 ms tolerance (BENCH-6 p99 55–92 ms on the dev host; `CV-C12′`); algo timing (TWAP, chase, iceberg) stays on `MonotonicScheduler`.

### Mandatory machine configuration (FINAL — binding, both engines, both spellings)

Copied verbatim from `79-r14-final-readiness-verdict.md` §7. `cv.statechart.factory` is the only place this code exists.

```python
machine = create_machine(chart, logic=logic, strict_config=True)
interpreter = Interpreter(
    machine, strict=True, event_schemas=CV_EVENT_SCHEMAS,
    max_queue_size=CV_INBOX_BOUND,     # async only; SyncInterpreter(max_queue_size=...) -> ValueError (#245)
    overflow_policy="refuse",
).use(CvErrorHooks())
# chart root: "onUnhandled": "defer" (+ ordered unguarded audit arm), "maxIterations": 500 (CV-C62)

# restore
interpreter = Interpreter.from_snapshot(machine, blob, minimum_version=3,
                                        plugins=[CvErrorHooks()])   # kwarg, not .use() (R13-W1)
assert interpreter.last_transition_ok is not None                    # before start() (CV-C60)
_cv_bring_up(interpreter)                                            # CV-C66'
await interpreter.start()   # on_interpreter_start fires; branch on restored_from_snapshot

# supervision
if interpreter.chain_trips > 0: page_operator(interpreter.last_chain_error)
if interpreter.dropped_receipts > 0: alert("receipt dropped")        # CV-C69

# shutdown (CV-C65')
drained = await interpreter.drain_pending()     # [priority..., inbox...]
journal(drained)                                # replay exactly once after restore
blob = interpreter.get_persisted_snapshot()
await interpreter.stop()

# provenance (CV-C68)
ev2 = cv_re_mint(ev, data=patched)              # never type=/src=
# timing: after:/raise(delay=) coarse only, >=250 ms tolerance, >=10 ms (CV-C12', CV-C55)
# actions: coroutine functions directly (CV-C67); no external send() in actions (CV-C25)
```

### Constraints that stand, and how each is enforced

| ID | Rule | Enforcement |
|---|---|---|
| MUST-* / MUSTNOT-* | `11-adversarial-review.md` §3, table above (MUSTNOT-06 reads: no `SyncInterpreter` in production) | machine-definition linter `E29-T10`; contract suite |
| `CV-C12′` | `after:`/`raise(delay=)` coarse only, ≥250 ms tolerance; hard/algo timing on `MonotonicScheduler` | chart linter (delay literals); BENCH-6 CI gate on target hardware (P3-G6) — reverts to `CV-C12` ban if p99 >100 ms there |
| `CV-C25` | no external `send()` from inside an action — gateway queue only | AST lint over `logic` modules |
| `CV-C43`-class | all `send()` on the owning loop; cross-thread via `run_coroutine_threadsafe` | runtime assert in factory wrapper |
| `CV-C45″` / `CV-C60` | read `last_error`/`last_transition_ok` after `from_snapshot`, before `start()` | factory restore path (only path) |
| `CV-C49′` / `CV-C58` | never re-persist an interpreter that has not been `start()`ed; compaction/migration jobs `start()` first | snapshot writer refuses; contract test |
| `CV-C55` | no delay <10 ms, either spelling | chart linter |
| `CV-C59` / `CV-C63` | chain health = `chain_trips > 0` only; never poll `last_error` | lint + `cv_machine_chain_trips` alert |
| `CV-C62` | `maxIterations` = 500, sized to the descent-seeded plateau | chart linter |
| `CV-C64′` | no in-step `await send(wait=True)` on own interpreter | lint |
| `CV-C65′` | shutdown = `drain_pending()` → journal → `get_persisted_snapshot()` → `stop()`; check `Receipt.error`; de-dup re-submits (R14-02) | factory `shutdown()`; drain round-trip contract test |
| `CV-C66′` | `on_interpreter_start` telemetry only; bring-up in `_cv_bring_up` | lint |
| `CV-C67` | actions are coroutine functions directly | lint |
| `CV-C68` | `re_mint` payload-only (`data`, `error`, `fired_at`, `scheduled_for`) via `cv_re_mint`; `type=`/`src=` banned | wrapper raises + lint over plugin/listener modules; retires when upstream fixes R14-01 |
| `CV-C69` | receipt-drop supervision via `dropped_receipts`/`on_receipt_dropped`; hook thread-safe, loop-free | lint + alert |
| `R11-W-1` | every chart deadline has a stable `send_id` | chart linter |

Retired constraints (CV-C01…CV-C67 minus the above) are listed per round in the amendments and in `79` §7; they are not re-imposed.

### Upgrade policy

- The pin is exact: **`xstate-statemachine==0.9.1`** with hash lock and a CI PEP 740 attestation-verify step (`pypi_attestations verify pypi --repository https://github.com/basiltt/xstate-statemachine`). **Never `~=`, `>=`, or an unpinned VCS ref.**
- Each new upstream release: run `docs/research/xstate/gate/run_gate.py`, the `tests/xstate_contract/` suite on both engines, and `docs/research/xstate/bench/bench_c_timers_v2.py` (BENCH-6) **before** bumping the pin. A bump is a PR that records the gate output as a dated amendment here. Any new Blocker, suite/coverage regression, or snapshot-format change fails the bump.
- A constraint retires only when the upstream fix is verified on both engines by our repro.

### Upstream liaison

Library defects and our constraint status are tracked on upstream meta issue **#26** (`basiltt/xstate-statemachine`). Open item: `R14-01` (re_mint override). Optional: `EventDrainedError` (R14-02), finaliser note for `on_receipt_dropped` (T-5). Postables are staged in `docs/research/xstate/issues/post-v0.9.1/`.

### Preconditions for live order traffic (ours)

P3-G1: the corrected B16, B18, B11 charts and the B8 attempt counter are merged into `28-statechart-catalogue.md` (done 2026-09-24) and `tests/xstate_contract/` is green on them. P3-G4: BENCH-1 re-measured on an idle host. P3-G6: BENCH-6 ≤100 ms p99 on target hardware.

---

## Amendment 1 — 2026-09-17: the 0.8.0 re-evaluation, and the mandatory machine configuration

**Status after this amendment: still Proposed (gated).** Part 1 and Part 2 are
unaffected — they were never gated. Part 3 does not yet take effect, but the
reason has changed, and the change is the point of this amendment.

### What happened

`basiltt/xstate-statemachine` 0.8.0 ("Fortify", commit `9bf6065`) was released and
re-evaluated in full against the gate: `docs/research/xstate/13`–`16` (benchmarks,
51 semantic probes, 11 purpose-built adversarial probes, a complete source-diff
review), 34 per-issue re-verifications in `issues/verify-0.8.0/`, and the verdict
in **`docs/research/xstate/17-reeval-0.8.0-verdict.md`**.

Of the 34 filed issues: **23 FIXED-DEFAULT, 6 FIXED-OPT-IN, 5 PARTIAL,
0 NOT-FIXED.** All four filed Blockers are closed. The library's own suite went
from 2,805 to 3,170 tests; timer starvation improved 14.5× (2530 ms → 174.4 ms);
five of seven benchmark thresholds are now met, up from two.

### Gate criteria (Part 3), answered

| # | Criterion | Met? | Evidence |
|---|---|---|---|
| 1 | Every Blocker closed upstream | **Yes, conditionally** | LC-02 and LC-16 FIXED-DEFAULT; LC-01 and LC-03 **FIXED-OPT-IN**; LC-15 and LC-17 close as consequences. The condition is criterion 6. |
| 2 | Every High fixed or mechanically mitigated | **Partly** | 13 FIXED-DEFAULT, 3 FIXED-OPT-IN, 4 PARTIAL (LC-07, LC-26, LC-38, LC-43). Each has a specified mechanism in the verdict §6 — but the mechanisms are not built yet. |
| 3 | Conformance parity on both runtimes | **No** | `E50-T03` has not shipped. |
| 4 | Performance gate holds | **No** | BENCH-2 (380.9 vs ≥2000 ev/s) and BENCH-6 (174.4 vs ≤100 ms) still missed. |
| 5 | `tests/xstate_contract/` under 60 s | **No** | The suite does not exist. |
| 6 | Prerequisites shipped (`E29-T10/T11/T12`, reaper) | **No** | **This is now the binding constraint.** |
| 7 | Pin + vendored copy | **No** | Re-pin target is `== 0.8.0` with sha256. |

### The decision, and why it is not "adopt"

The verdict's honest reading of the decision table is **ADOPT WITH CONSTRAINTS,
conditional** — decision-table row 6 with its precondition unmet, which today
reads as row 7. The reasoning, stated the way it must be stated in a record:

> **LC-01 and LC-03 — two of the four Blockers — are closed by a per-machine
> policy whose default still reproduces 0.7.x behaviour.** They are closed for a
> caller that sets the option and open for one that does not. Every Blocker in
> this register is a *silent* failure, and MUST-09 is explicit that an unenforced
> rule is not a rule. So these count as closed only while the mandatory
> configuration below is enforced by the machine-definition linter.

What has genuinely changed since 2026-09-15 is **where the remaining work is**. At
0.7.0 the gap was upstream and unbounded. At 0.8.0 the gap is `E29-T10` and
`tests/xstate_contract/` — our own prerequisites, which MUST-09 already required
before the first statechart ships regardless of runtime. That is a materially
better position, and it is why this amendment does not extend the deadline.

Consequently:

- **Order path:** remains on the shim. No change to delivery.
- **Non-order paths** (replay/backtest, rule-runtime lifecycle, B10–B14,
  B16–B20): may proceed on the library under the *legitimate* partial-adoption
  path in `20-adoption-gate.md` §8, since every Blocker affecting them is
  FIXED-DEFAULT and a silent no-op there costs a wrong chart, not money. This
  still requires the boundary to be written down and the contract suite in place
  for those families.
- **`E50-X01` (Sprint 08)** proceeds as scheduled with this verdict as its input.

### Retired constraints

0.8.0 lets us delete real complexity, and the re-verification protocol requires us
to actually delete it rather than carry dead scaffolding:

| Retired | Because |
|---|---|
| **MUST-06** (merge context defaults on restore, in our wrapper) | LC-22 fixed. Keep the regression *test*; delete the wrapper. |
| House rule **A3** (`"*": defer` on every transient state + `drain_deferred` in every entry) | LC-03 closed by native `onUnhandled: "defer"`, verified 9/9. Delete the scaffolding and its workaround tests; keep INV-5 per family. |
| **MUST-03 / MUST-04** as written | Re-expressed against the library's own buffer: alert on `deferred_count` / `pending_events`, both snapshot-durable. The alert stays; the hand-rolled buffer goes. |
| Gate constraint "LC-27 open ⇒ replay cannot use `after`" | `SimulatedClock` is real and deterministic. |
| Gate constraint "cross-thread via `run_coroutine_threadsafe`" | **Inverted** — that pattern now raises. Replaced by CV-C14. |

**MUST-07** is re-pinned to `== 0.8.0` with sha256. All other MUSTs and every
MUST-NOT stand. **MUSTNOT-06** (never use `SyncInterpreter`) is *reinforced*, not
relaxed: 0.8.0 removed the thread-per-timer defect but introduced two new
sync-engine defects (N-2, N-3).

### Mandatory machine configuration

**Normative, and binding on Part 1 as well as Part 3.** Every machine in
`docs/plan/28-statechart-catalogue.md` — B1–B20, without exception — carries this
block, and every interpreter is constructed through the single factory
`cv.statechart.factory`. This applies to the shim too: the shim must accept and
honour these keys, so that adoption stays a flag flip rather than a rewrite.

```jsonc
{
  "id": "order",
  "initial": "…",

  // ── 0.8.0 mandatory policy block — identical in every catalogue machine ──
  "actionErrorPolicy": "rollback",   // "fail" for B8/B17/B18/B20 (invariant machines)
  "onUnhandled":       "defer",      // "error" for B13/B14/B18 (control machines)
  "guardErrorPolicy":  "raise",      // never "false"; a crashed guard is not a denial
  "strictTargets":     true,         // kill the 0.7.x sibling fallback (LC-07)
  "strict":            true,         // reject undeclared event names at the call site
  "spawnBlockingTimeout": 5000,      // ms; never rely on the 30 s default

  "states": { /* … */ }
}
```

Interpreter construction, in one place only:

```python
# cv/statechart/factory.py — the ONLY place these constructors may be called.
interp = Interpreter(
    create_machine(defn, logic=logic,
                   strict_targets=True,               # never False (removed in 1.0)
                   event_schemas=EVENT_SCHEMAS[kind]),
    clock=clock or RealClock(),                       # SimulatedClock in tests/replay
    strict=True,                                      # ctor wins over machine config
    max_queue_size=BOUNDS[kind],                      # never None
    overflow_policy=(OverflowPolicy.RAISE if kind in ORDER_PATH
                     else OverflowPolicy.DROP_NEWEST),
)
interp.use(CvErrorHooks()); interp.use(CvMetricsPlugin())
```

Rationale for each key, the per-kind values, the operational rules
(`stop(drain=True)`, `pending_invocations()` on restore, JSON-string snapshots,
`send(wait=True)` with freshly-constructed events) and the **CI lint rule
CV-LINT-XS1…XS10** are specified in full in
`docs/research/xstate/17-reeval-0.8.0-verdict.md` §4, which this section
incorporates by reference. The lint rule is part of `E29-T10` and is the
mechanism on which criterion 1 depends.

Two consequences worth stating in the ADR body rather than only in the research:

1. **The mandated configuration is not free.** `actionErrorPolicy="rollback"`
   costs **−22.4%** throughput while armed and never firing (35,532 → 27,586
   ev/s). BENCH-1's 3.17× headroom becomes ~2.46×, below its 3.0× bar. This is
   accepted as constraint **CV-C13** and is why the order path keeps its
   dedicated event loop. Future gate runs must report BENCH-1 both ways.
2. **`rollback` is a context + configuration transaction, not an effect
   transaction.** An outward `sendTo` or `raise` emitted by an earlier action in
   the same list survives the rollback. Constraint **CV-C02** therefore requires
   that any action which talks to the outside world is the **last** in its list,
   or lives on the entry of a state only reached once the transition has
   committed. This is a design rule for every machine in the catalogue.

### New constraints introduced by this amendment

**CV-C01…CV-C15**, specified in `17-reeval-0.8.0-verdict.md` §6 and binding
alongside `11-adversarial-review.md` §3. The ones that change how machines are
*written* (as opposed to how they are hosted) are CV-C02 (effects last),
CV-C06 (fresh `Event` per `send(wait=True)`), CV-C12 (`after` still banned —
BENCH-6 is still missed) and CV-C15 (no event may be named `error.*` or `done.*`,
because such names are invisible to `"*"` handlers and exempt from
`onUnhandled: "error"`).

### New defects found, and what we owe upstream

The re-evaluation found **17 defects not in the 0.7.0 register** (N-1…N-17:
2 High, 9 Medium, 6 Low, 0 Blocker). The two High ones sit inside features 0.8.0
added: `send(wait=True)` hangs forever when the same `Event` instance is in
flight twice, and `SyncInterpreter` `after` deadlines become unreachable by
`tick()` inside a running asyncio loop. Five are drafted as new upstream issues
with runnable repros (`docs/research/xstate/issues/new-0.8.0/`) and eleven
follow-up comments are drafted (`issues/followups-0.8.0/`). None has been filed;
filing is tracked on the `E50-C*` chores.

### Re-review trigger

Unchanged: `E50-X01` at Sprint 08. This amendment does not decide the gated half;
it records the evidence the review will use, and narrows the open question to a
single, tractable one — *is `E29-T10` green?*

---

## Amendment 2 — 2026-09-18: verification of `main` @ `5327ba6` (pre-0.8.1)

**Scope.** A full verification pass against the unreleased `main` branch of
`basiltt/xstate-statemachine`, commit
`5327ba69fb735cfe24c7b3772050dac0a71a7b3d` (CHANGELOG `[Unreleased] — targeting
0.8.1`). Inputs: `docs/research/xstate/22-verify-main-verdict.md` (the verdict),
`18-verify-main-gate.md`, `19-verify-main-diff-review.md`,
`21-verify-main-adversarial.md`, `issues/verify-main-5327ba6/*.result.md`.

> **Identify this build by commit, never by version string.** `__version__`
> still reports `0.8.0` on `5327ba6`. Any pin, gate baseline, vendored-copy
> contract test or CI assertion keyed on the version string will silently accept
> 0.8.0 for 0.8.1 and vice versa.

### What happened

**No regressions.** Every status delta against the 0.8.0 register moved in the
fixing direction; no test function was deleted and no skip/xfail was added
across the whole `v0.8.0..5327ba6` diff; the public API is additive only and the
snapshot format is unchanged. The library's own suite grew to 3,234 passing and
coverage rose to **90%**.

**Nine issues are closable, six stay open, all narrowed.** Critically, the two
0.8.0-era High defects that had no mitigation other than "don't do that" are
genuinely fixed under adversarial probing: `send(wait=True)` no longer hangs on
a reused `Event` (held at 500-way concurrency under three policies), and
`SyncInterpreter` `after` deadlines are reachable by `tick()` inside a running
loop.

### Gate criteria (Part 3), re-answered

| # | Criterion | Met? | Evidence |
|---|---|---|---|
| 1 | Every Blocker closed upstream | **Yes, conditionally** | Unchanged. LC-01 and LC-03 remain FIXED-OPT-IN; the condition is still criterion 6. |
| 2 | Every High fixed or mechanically mitigated | **Improved, still partly** | 4 High open (was 4, but a different and smaller set): LC-07 narrowed to the `strict_targets=False` opt-out we never take, plus three new (M-1, F-1, F-2). LC-26, LC-38 and LC-43 are now closed. |
| 3 | Conformance parity on both runtimes | **No** | `E50-T03` has not shipped. |
| 4 | Performance gate holds | **No** | BENCH-2 and BENCH-6 still missed; BENCH-1 with `rollback` armed measures **2.43×** against the ≥3.0× bar — statistically unchanged from 0.8.0's ~2.46×, not a regression. |
| 5 | `tests/xstate_contract/` under 60 s | **No** | The suite does not exist. |
| 6 | Prerequisites shipped (`E29-T10/T11/T12`, reaper) | **No** | **Still the binding constraint, and now the *only* one for non-order paths.** |
| 7 | Pin + vendored copy | **No** | Re-pin target is `== 0.8.1` once tagged; until then commit `5327ba6` with sha256. |

### The decision, restated

Unchanged in form: **ADOPT WITH CONSTRAINTS, conditional** — decision-table row
6 with its precondition unmet, which still reads honestly as row 7. What changed
is the substance:

> **Nothing upstream blocks adoption on a non-order path.** Every Blocker is
> closed; both 0.8.0-era High defects that lacked a mitigation are fixed; two
> CandleViewer constraints retired *into the library*. The remaining upstream
> items are each behind an opt-out we never take, a capacity-planning line item,
> an ergonomics gap, or a namespace CV-C15 already bans. **Once `E29-T10` and
> `tests/xstate_contract/` are green, non-order adoption is unconditional.**

- **Order path:** remains on the shim, and now has a second, specific reason —
  **M-1** (below) — in addition to the linter.
- **Non-order paths:** unchanged from Amendment 1; the §8 partial-adoption path
  is now on firmer ground.
- **`E50-X01` (Sprint 08)** proceeds as scheduled with this verdict as its input.

### The finding that governs the order path — M-1 (High)

The two library features our order path is **mandated** to use together —
`onUnhandled: "defer"` (CV-C01) and `send(wait=True)` receipts (CV-C06) — are
individually correct and jointly wrong. A deferred event's receipt resolves
immediately with `changed=False, error=None`, indistinguishable from "the
machine looked at your event and correctly decided to do nothing" — for an event
that is parked and *will* drive its transition on replay, after the caller has
already acted on the receipt.

This matters because its trigger is our mandated configuration, not a misuse of
it. A FILL arriving one microstep early — the precise scenario `defer` was
adopted to fix — returns a receipt saying the fill did not land. It is not a
hang and not data loss; it is a gate that says *no* about an event that is about
to say *yes*, and carefulness is not a control that detects a confidently wrong
answer.

**Order-path adoption is deferred until M-1 is fixed upstream, or covered by the
new CV-C06 clause** implemented in `cv.statechart` and locked by
`test_receipt_is_inconclusive_when_deferred`.

### Constraints — retired, standing, new

**Retired (delete the code, keep the tests):**

| Retired | Because |
|---|---|
| **CV-C06, fresh-`Event` clause** — "never reuse an `Event` across concurrent `wait=True` sends" | Fixed by construction upstream (`Interpreter._detach()` at the send boundary). Delete `test_send_receipt_fresh_event_only` and the **CV-LINT-XS9** clause. |
| **CV-C14, gateway-validation clause** — the gateway performing the `strict`/`event_schemas` check itself | The library now does this on the calling thread before queuing. Delete the gateway's duplicate validation. **The `run_coroutine_threadsafe` ban stands**; CV-C14 becomes a ban-only rule. |

**New:**

| ID | Constraint | Enforcement |
|---|---|---|
| **CV-C16** | No action may call `send()` on its own interpreter; self-directed events use the `raise` built-in, the only shape the runaway budget bounds on the async engine. | **CV-LINT-XS11** (AST); `test_no_self_send_in_actions` |
| **CV-C17** | No catalogue machine relies on a `raise` chain deeper than 1,000; the cut is silent (`status` stays `"running"`, `last_transition_ok` stays `True`, no hook fires). | Design-review checklist; `test_chain_depth_under_budget` per family |
| **CV-C18** | `MachineLogic` instances are never shared across `create_machine()` calls, and one spelling per implementation is registered — `create_machine()` mutates the registry in place and the ambiguity guard misses the common case. `MachineLogic(strict=True)` is mandated in the factory. | Factory assertion on logic-object identity; **CV-LINT-XS12**; `MachineLogic(strict=True)` |

**CV-C06 strengthened.** New mandatory clause: *a `wait=True` receipt with
`changed=False, error=None` must be treated as **inconclusive** unless
`interpreter.deferred_count` is `0` at the same instant.*

**Standing.** CV-C01…CV-C05, CV-C07…CV-C15 all stand, with two rationale shifts
worth recording: **CV-C03** (async-only) now stands on the new sync-engine
defects rather than the old ones, and **does not** protect us from M-2 (an
*async* hole) — hence CV-C16. **CV-C15** must stay because the library's new
build-time warning covers reserved `on` keys only, does not cover `send()`, and
is case-sensitive; **`E50-T05`'s event-name gate must therefore run and must be
case-insensitive.**

### The mandatory machine configuration is unchanged

**No library default changed on this commit.** The six-key policy block in
Amendment 1 and `docs/plan/28-statechart-catalogue.md` remains normative
**verbatim**. Two *additive* changes to the factory (not the machine JSON):
`MachineLogic(strict=True)` per CV-C18, and the CV-C06 deferred-receipt wrapper.
One deletion: the gateway's duplicate validation.

### New defects found, and what we owe upstream

Thirteen defects not in the 0.8.0 register (**3 High, 6 Medium, 3 Low, 1 Info,
0 Blocker**), after de-duplicating the diff review against the adversarial pass.
Eight are drafted as new upstream issues with runnable repros
(`docs/research/xstate/issues/new-main/`); five ride along on existing issues.
Sixteen verification comments and a meta-issue update are drafted
(`issues/comments-main-5327ba6/`). **Nothing has been filed**; filing remains
tracked on the `E50-C*` chores.

Three of the new defects are in the #77 fix's own code path, which is the one
item we would want resolved before pinning — along with the `__version__` bump,
which is mechanical but makes the pin meaningful.

### Re-review trigger

Unchanged: `E50-X01` at Sprint 08. Re-run the gate when **0.8.1 is tagged** (to
confirm the tagged artefact matches the commit verified here and that
`__version__` is corrected), and on every release thereafter per
`20-adoption-gate.md`. The open question is narrower still: *is `E29-T10` green,
and is M-1 closed?*

---

## Amendment 3 — 2026-09-18: verification of `main` @ `3c527b0` (unreleased 0.8.1, PR #83)

**Scope.** A full verification pass against `basiltt/xstate-statemachine` `main`
commit `3c527b0d04c0d2d0ebb565af7e9e905f7178f620`, the merge of PR #83
(functional commit `2459c82`: `ErrorEvent` #80, provenance-based system events
#79, one task per invoked child #43). Inputs:
`docs/research/xstate/26-verify-3c527b0-verdict.md` (the verdict),
`23-verify-3c527b0-findings.md`, `24-verify-3c527b0-gate.md`,
`25-verify-3c527b0-diff-review.md`,
`issues/verify-main-3c527b0/{43,79,80}.result.md`.

> **Identify this build by commit, never by version string.** `__version__`
> still reports `0.8.0` on `3c527b0` — two verification passes running. Any
> pin, gate baseline, vendored-copy contract test or CI assertion keyed on the
> version string will silently accept 0.8.0 for 0.8.1 and vice versa.

### What happened

**Three good fixes, one regression, and the gate moves for the first time
since 0.7.0.**

#43, #79 and #80 all verify against their own acceptance criteria (7/7, 10/10,
8/8). #43 is excellent: the poll loop is gone, the task budget is `children + 1`
(1.0 tasks/child at n=2/10/50, was 2.0, independently reproduced three ways),
`onDone` latency drops to 0.96 ms median, 1 000 spawn/complete cycles leak
nothing, and the exit-vs-completion race is handled under a ±2 ms scan. The
gate's LC-28 check flips FAIL → PASS; the suite grows to 3 242/13/0 at 90%
coverage; no gate, suite, bench or probe row regressed.

**But two features that shipped in the same release each met the snapshot
boundary (#47) without being taught about it.**

- **G-2 (High) — provenance does not survive a snapshot.** A restored
  `escalate` event comes back as user traffic: it fails a machine configured
  `onUnhandled: "error"` and is swallowed by `"*"`. Under the previous
  name-based rule the exemption was a pure function of `event.type` and gave
  the **same answer either side of a restore**. **This is the one behavioural
  regression in the window**, and it was found by reading the diff — no gate,
  suite, bench or probe row catches it.
- **G-3 (High) — a pending `ErrorEvent` is silently dropped by
  `get_persisted_snapshot()`.** The inbox filter is `isinstance(e, Event)` and
  `ErrorEvent` is a `NamedTuple`. #47 exists so a crash between accept and
  process cannot lose an event; #80 routed *every* service and child failure
  through a class that falls through that filter. A machine restores believing
  the invoke never failed and no `onError` ever fires. The filter does not even
  log.
- **G-1 (High) — `Event.system` is a public, user-settable dataclass field.**
  `send(Event("X", system=True))` bypasses `strict`, `event_schemas`,
  `onUnhandled` and `"*"` on both engines and through `send_threadsafe`.

**G-2 and G-3 are the two findings with our name on them** — the order path is
snapshot/restore-based by CV-C08 and reconciles invokes on restore by CV-C07.

### Gate criteria (Part 3), re-answered

| # | Criterion | Met? | Evidence |
|---|---|---|---|
| 1 | Every Blocker closed upstream | **Yes, conditionally** | Unchanged. LC-01 and LC-03 remain FIXED-OPT-IN; the condition is criterion 6. |
| 2 | Every High fixed or mechanically mitigated | **No — and worse than at `5327ba6`** | **7 High open** (was 4): LC-07/#31, M-1, F-1, F-2 carried forward, plus G-1, G-2, G-3 new from PR #83. |
| 3 | Conformance parity on both runtimes | **No** | `E50-T03` has not shipped. |
| 4 | Performance gate holds | **No** | BENCH-2 and BENCH-6 still missed; BENCH-1 with `rollback` armed measures ~**2.03×** (1.56–2.37 over three runs) against the ≥3.0× bar — noisy, unchanged, no source touched on this path. **Improved:** the actor task budget is now `children + 1`, pinned by the library's own tests. |
| 5 | `tests/xstate_contract/` under 60 s | **No** | The suite does not exist. |
| 6 | Prerequisites shipped (`E29-T10/T11/T12`, reaper) | **No** | Still not shipped — but **no longer the binding constraint**; criterion 2 now binds first. |
| 7 | Pin + vendored copy | **No** | Re-pin target is `== 0.8.1` once tagged; until then commit `3c527b0` with sha256. |

### The decision — CHANGED

**DEFER**, on `20-adoption-gate.md` §7 **decision-table row 5**: all Blockers
closed, **more than 5 High open** (7 against a bar of 5).

Three things need saying about that:

1. **It is arithmetic, not a re-weighting.** The table is applied in order and
   row 5 matches on the merits. Nothing was promoted in severity to force it.
   All four originally-filed Blockers remain closed.
2. **This is a pre-release build.** Fixing G-2 and G-3 before 0.8.1 tags
   returns the count to 5 and restores row 6 ("adopt with constraints"). That
   is the outcome we expect and would prefer, and it is what our upstream
   filings ask for.
3. **Parts 1 and 2 of this ADR are unaffected.** Statechart JSON remains the
   contract, and the in-house interpreter shim remains the execution path.
   Nothing here changes the plan to adopt once the count comes back under the
   bar. Non-order-path prototyping in a sandbox with no real credentials
   remains permitted.

### Pin (Amendment 3)

```
xstate-statemachine == 0.8.1        # once tagged
# until then: git commit 3c527b0d04c0d2d0ebb565af7e9e905f7178f620, with sha256
```

Superseding the `5327ba6` pin. **The pin records what we tested, not what we
endorse** — the gate decision on this commit is DEFER, and Part 3 has not taken
effect. Do not read the pin as authorisation to add the dependency.

### Constraints — retired, withdrawn, standing, new

**Retired:**

| Retired | Because |
|---|---|
| **CV-C15, case-insensitivity clause** — "`E50-T05`'s event-name gate must be case-insensitive" | #79 makes a user event named `error.*`/`done.*` visible to `"*"`, trippable by `onUnhandled` and rejected by `strict` — **case variants included**, because neither spelling is exempt any longer. |

**Withdrawn as unsound (this is not a good-news retirement):**

| Withdrawn | Because |
|---|---|
| **CV-C06's `deferred_count` clause** — "treat `changed=False, error=None` as inconclusive unless `interpreter.deferred_count` is `0` at the same instant" | **It does not work.** At the caller's `await` point `deferred_count` reads `0` for the deferred case **and** for the genuine no-op. `test_receipt_is_inconclusive_when_deferred` cannot be written as specified. Replaced by a hard prohibition (below) until a working discriminator exists. |

**CV-C06 restated.** *A `wait=True` receipt reading `changed=False,
error=None` is **inadmissible** as a gate on any machine configured
`onUnhandled: "defer"`. No order-path statechart ships until M-1 is fixed
upstream — the receipt learns the disposition — or `cv.statechart` obtains an
out-of-band defer discriminator, which the library does not currently expose.*
Enforced by **CV-LINT-XS9** (re-purposed from the retired fresh-`Event` rule)
and by the absence of an order-path machine in the registry.

**CV-C15 re-scoped.** The rule becomes: *no CandleViewer event may be named
with any prefix in `ENGINE_EVENT_SHAPES` — `done.invoke.`, `done.state.`,
`error.platform.`, `after.`, `xstate.`, `___xstate`.* These are the only names
`models.is_known_event` still exempts **by name** (G-7), so a typo in them is
silent under `strict`. The old blanket `done.`/`error.` ban is over-broad and
retires with its case-insensitivity requirement. **`E50-T05` must be
re-specified accordingly.**

**New:**

| ID | Constraint | Enforcement |
|---|---|---|
| **CV-C19** | No CandleViewer code constructs an `Event` with `system=True`, and no code trusts `is_system_event()` / `Event.system` as a security or routing boundary. It is provenance-shaped but not provenance-guaranteed (G-1). Routing that must distinguish engine from user traffic uses our own gateway-stamped envelope. | **CV-LINT-XS13** (AST: `Event(` with a `system=` keyword); `test_no_forged_system_events` |
| **CV-C20** | `cv.statechart.persistence` owns the mailbox across a snapshot boundary. Quiesce before `get_persisted_snapshot()` (inbox drained, no in-flight invoke completion); reconcile every `pending_invocations()` entry against the order/exec store on restore. The library's snapshot **silently drops** `ErrorEvent`/`DoneEvent` (G-3) and **silently loses** provenance (G-2); neither is detectable after the fact. | `persistence.snapshot()` asserts `queue_depth == 0 and deferred_count == 0`; `test_snapshot_refuses_non_quiesced_interpreter`; `test_restore_reconciles_every_pending_invocation` |
| **CV-C21** | Every `onError` action branches on `isinstance(event, ErrorEvent)` and reads `event.error`. Never `.data` (deprecated, removed in 0.9), never `event.type.startswith("error.")`, never `event.payload.get(...)` on an error-shaped event — `_resolve_event_spec` can hand you an `Event` whose `payload` is the exception (G-5). `escalate` is the exception and is handled by name: still a plain `Event` with the error under `payload["error"]` (G-6). | **CV-LINT-XS14**; `test_onerror_reads_error_not_data`; `test_escalate_payload_shape` |
| **CV-C22** | CI does not run a global `-W error::DeprecationWarning` against library code until G-4 is fixed — the library trips its own `ErrorEvent.data` deprecation from `plugins.py:435` and `base_interpreter.py:1781`. Filter by module, not globally. | `pyproject.toml` `filterwarnings` entry with a `# G-4, remove when fixed upstream` comment |

**Standing.** CV-C01…CV-C05, CV-C07…CV-C14, CV-C16…CV-C18 all stand, with
three rationale shifts worth recording: **CV-C03** (async-only) gains a fourth
sync-only gap (G-8: a failed invoked child machine never reaches `onError` on
`SyncInterpreter`) and still does **not** protect us from G-1/G-2/G-3, all of
which are async-side; **CV-C07** is now load-bearing for *correctness* rather
than liveness, because G-3 means invoke reconciliation is the only way a
restored machine can learn its invoke failed; **CV-C11** is reinforced by the
still-silent #77 overflow.

**Constraint set in force: CV-C01…CV-C22.**

### The mandatory machine configuration is unchanged

**No library default changed on this commit.** The six-key policy block in
Amendment 1 and `docs/plan/28-statechart-catalogue.md` remains normative
**verbatim**. Every change is outside the machine JSON — in the factory
(`MachineLogic(strict=True)`), the gateway (CV-C19's `system=` ban and CV-C15's
re-scoped event-name rule), the persistence layer (CV-C20's quiesce-and-
reconcile), and the action layer (CV-C21's `ErrorEvent` accessors). The CV-C06
deferred-receipt wrapper specified in Amendment 2 is **withdrawn**.

### New defects found, and what we owe upstream

Twenty-four canonical findings after de-duplication (**6 High, 11 Medium,
7 Low, 0 Blocker**), merging the 12 still-present `5327ba6` findings with the
12 from the PR #83 diff review. Sixteen become new upstream issues (every High
and Medium with a runnable repro); eight ride along on existing issues as
comments. Per-issue: **13 confirm closed, 3 reopen** (#31 engine parity under
`strict_targets=False`, #77 raise-on-overflow, #79 provenance spoofable and not
persisted) — reopening only where an acceptance criterion is unmet **by code**,
not by wording, naming or architectural framing.

All bodies are finalised in
`docs/research/xstate/issues/post-3c527b0/` with a `manifest.json` posting
plan. **Nothing has been filed**; filing is the Post phase's job and remains
tracked on the `E50-C*` chores.

### Re-review trigger

Unchanged: `E50-X01` at Sprint 08. Re-run the gate when **0.8.1 is tagged**, to
confirm the tagged artefact matches what was verified here, that `__version__`
is corrected, and — critically — **whether G-2 and G-3 were fixed before the
tag**. If they were, the High count returns to 5 and the decision reverts to
ADOPT WITH CONSTRAINTS. The open questions are now: *are G-2 and G-3 fixed, is
`E29-T10` green, and is M-1 closed?*

## Amendment 4 — 2026-09-18: round-4 battle-test of `main` @ `5e07ba8` (pre-0.8.1)

**Decision: DEFER (order path) on decision-table row 1 — open Blockers.** All 19 round-3 issues verified (17 closed, #91/#99 partial); **no regressions**; suite 3 276 / 0 failed; coverage 90 %. The first deep battle-test (persistence property tests, determinism, concurrency, SCXML conformance, fuzzing, security, 25-min soak, observability) found, after adversarial refutation, **2 Blocker · 6 High · 18 Medium · 12 Low** library defects (`docs/research/xstate/30-r4-findings-register.md`). Governing items: **R4-01** — a snapshot taken mid-macrostep restores as a permanently inert machine that reports `status="running"` (45 % of interruption points torn); **R4-04** — non-terminating `SyncInterpreter.start()`; **R4-06** — external events sent during a macrostep are charged to the chain budget and can be discarded (introduced by the #90 fix); **R4-07** — `Receipt.deferred` keyed on `id(event)`.

**For the first time the operative blocker is upstream, not our linter.** The in-house shim remains the order-path runtime. Non-order paths (B10–B14, B16, B17, B19, B20) may begin on the library under the constraints below; **B18 KillSwitch is order-path-adjacent and waits.**

- **Pin (Amendment 4):** commit `5e07ba8` for evaluation only; endorsement withheld. Re-verify per `29-r4-final-verdict.md` §8 when R4-01/04/06/07 land.
- **New constraints (Amendment 4): CV-C23…CV-C29** — snapshots only at quiescence via the factory `snapshot()` wrapper (C23); never trust `Receipt.deferred` alone (C24); no external `send()` from inside an action / while processing — gateway queue only (C25); parent↔child data via explicit `sendTo`, never `output` (C26); our own legality check on every `from_snapshot()` (C27); `LoggingInspector` never in production, `CvMetricsPlugin` redacts context (C28); linter forbids `always` targeting the machine root (C29). Amendment-3 constraints CV-C01…CV-C22 stand.
- **Exit condition:** R4-01 and R4-04 closed with pinned upstream tests → row 1 clears; with R4-06 and R4-07 also closed the open-High count is 4, all mechanically mitigated → **ADOPT WITH CONSTRAINTS** for the order path, gated only on `E29-T10` + `tests/xstate_contract/` (the 0.8.0 position).

## Amendment 5 — 2026-09-19: round-5 final readiness check of `main` @ `3ed3099` (pre-0.8.1)

**Decision: DEFER for the order path (B1–B9, B18); GO for non-order paths (B10–B17, B19, B20) under CV-C01…C34.** All 39 round-4 issues verified (34 closed, 5 partial); no regressions; suite 3 322 / 0; coverage 90 %. Battle re-run and the first end-to-end execution of all 20 catalogue machines on the library found **4 Blocker · 8 High · 8 Medium · 1 Low** library defects (`docs/research/xstate/33-r5-findings-register.md`): R5-01 the #102 mid-step check is any-leaf not per-region (parallel tears still snapshot), R5-02 no read-side configuration-legality check on restore, R5-04 nested-invoke `onDone`-to-ancestor livelocks `start()`, R5-12 `actionErrorPolicy:"fail"` reverts to the source state and bricks the interpreter. Root requirement stated upstream: a single configuration-legality invariant enforced on both snapshot write and restore.

- **Our own catalogue had 10 defects** (OC-01…OC-10, register §6). OC-01 — the 0.7-era `"*": {"actions":["defer"]}` scaffolding is live and disables `strict` — is a Blocker on our side and is fixed in `28-statechart-catalogue.md` by CV-C34. OC-02…OC-06 are genuine invariant gaps in B2/B4/B11/B16/B19 and are ticketed.
- **Constraints:** retired CV-C24, CV-C25 (runtime guard only; lint stays), CV-C26, CV-C29. New **CV-C30** no parallel regions on order-path machines until R5-01 closes; **CV-C31** `"fail"` forbidden — invariant machines use `"rollback"` + explicit `halted` state; **CV-C32** every service `async def`; **CV-C33** `send_threadsafe` only via the gateway; **CV-C34** no wildcard-defer scaffolding.
- **Mandatory config block change:** `actionErrorPolicy` is `"rollback"` for every machine (the `"fail"` row is withdrawn until R5-12 is fixed).
- **Pin:** commit `3ed3099`, evaluation only. **Runtime:** in-house shim stays on the order path; non-order machines may move to the library now.
- **Exit condition:** R5-01/02/04/12 closed with pinned tests **and** open-High ≤ 5 → ADOPT WITH CONSTRAINTS for the order path (`34-r5-final-readiness-verdict.md` §9).


## Amendment 6 — 2026-09-20: round-6 final readiness check of `main` @ `cec108b` (pre-0.8.1)

**Decision: DEFER for the order path (B1–B9, B18); GO for non-order paths (B10–B17, B19, B20) under CV-C01…C37 as recomputed below.** 26 issues verified — **24 closed** (2 with a documented scope caveat), **1 partial** (#122), **1 not-fixed** (#157, reopened on narrower grounds). **3 Medium regressions**; a fourth reported regression (LC-01) was our own harness asserting a pre-#145 contract. Suite **3 399 / 0**, coverage **92.77 %** against the new 90 % floor (PR #163). After independent adversarial refutation of every Blocker and High: **2 Blocker · 2 High · 7 Medium · 9 Low** (`docs/research/xstate/38-r6-findings-register.md`). Refutation moved **6 of 10** Blocker/High candidates *down* and none up; three of those were corrections to claims of ours that did not survive contact.

- **The block is one upstream defect class, and it is narrow.** The async engine does not share the sync engine's chain/macrostep termination accounting. (a) `interpreter.py:1427` exempts *every* system event from the chain budget, where `sync_interpreter.py:770-828` (#94) spares a completion only at the moment of the trip; (b) #144's termination rule ("a chain ends only when nothing self-generated remains queued") shipped in `sync_interpreter.py` and was never ported to `interpreter.py::_run_event_loop`. That one change closes **R6-01** (`await send(wait=True)` never resolves, core pegged, `status="running"`), **R6-02** (unbounded silent invoke cycle) and **R6-03** (`rollback` + `invoke.onDone` re-invokes ~1 400×/s with `error=None`). The sync engine is provably correct on all three.
- **The round's pattern, recorded because it is the risk going forward:** *"fixed" has meant "fixed on the engine the issue was filed against."* Three of the four candidate Blockers are async-only faults. The highest-value upstream ask in this amendment is not a fix but a test: an `Interpreter`/`SyncInterpreter` **parity test class**.
- **The structural win.** #142/#143 landed **one** configuration-legality predicate — exactly one leaf per region — on **both** the snapshot write side and the read side, with the read side provably reusing the write-side function. Torn parallel snapshots **27.4 % → 0 %**; 2 000 quiescent snapshot/restore cycles give 2000/2000; a 350-machine random-parallel property yields 1 217 snapshots with zero illegal configurations. This is the single design change Amendments 4 and 5 both demanded, delivered at the root.
- **Constraints — retired:** **CV-C27** (retired to a one-line residual, CV-C27′), **CV-C30** (parallel regions are safe again — the reason it existed is fixed), **CV-C31** (retired **and inverted**: #145 makes `"fail"` safe — `status="stopped"`, configuration cleared, halted blob refused by `from_snapshot` — while R6-03 makes `"rollback"` the dangerous policy on the order path), **CV-C34** (done — applied throughout the catalogue). **CV-C32 does *not* retire**: R6-09's downgrade to Low depends on it, and it is restated per-engine (async → `async def` only; sync → plain `def` only, so **sync parity is unavailable, not merely untested, for any machine with services**).
- **Constraints — new:** **CV-C27′** restore asserts `set(state_ids) ⊆ set(configuration)` (R6-16). **CV-C31′** order-path machines must not combine `"rollback"` with a raisable entry action on a state carrying an `invoke`; use `"fail"` + an explicit `halted` state (R6-03). **CV-C35** no `always` may descend into a child carrying an `invoke`, nor target an ancestor of its own source (R6-01, R6-02). **CV-C36** every `send_threadsafe` future is read; refusals increment a shed counter (R6-05). **CV-C37** the factory awaits an explicit `children_ready()` barrier — `await start()` is not "the machine is up" (R6-11).
- **Mandatory config block change:** `"fail"` is **re-permitted** and is now *required* on order-path machines whose states carry an `invoke` with raisable entry actions; `"rollback"` remains the default everywhere else. Recomputed block in `39-r6-final-readiness-verdict.md` §7 and mirrored into `docs/plan/28-statechart-catalogue.md`. Note that C-07 is outstanding on our side: CV-C31 promised explicit `halted` states and they were never written.
- **Pin:** commit `cec108b`, **evaluation only; endorsement withheld.** `__version__` still reports `0.8.0` — key on the commit. Do **not** pin a 0.8.1 tag cut at this commit: it would put two silent unbounded-CPU Blockers into a released version and remove the "key on the commit" escape hatch.
- **Runtime:** in-house shim stays on the order path. Non-order machines move to the library now — they drove **zero** new library defects across 46 control scenarios and 9 snapshot-every-macrostep runs.
- **Exit condition:** R6-01 and R6-03 closed with **pinned async tests** → the Blocker row clears and open-High is **2** (R6-02, R6-06), inside the bar of 5, each with a mechanically enforced mitigation → decision-table row 6, **ADOPT WITH CONSTRAINTS** for the order path. R6-02 closes with the same change. Re-verification recipe (~45 min) in `39-r6-final-readiness-verdict.md` §9. Decision owner unchanged: `E50-X01`.


## Amendment 7 — 2026-09-20: round-7 final readiness check of `main` @ `221ce7c` (pre-0.8.1)

**Decision: DEFER for the order path (B1-B9, B18); GO for non-order paths (B10-B17, B19, B20) under CV-C01…CV-C42 as recomputed in `docs/research/xstate/44-r7-final-readiness-verdict.md` §7.** 12 issues verified — **7 fixed** (#157, #166, #169, #170, #171, #172, #173), **2 partial** (#167, #168 — one defect, not two), **2 documentation-only** (#122 **correct as designed**, and we withdraw our own previous reopen; #174 documented but unchanged), **1 not-fixed** (#175 Case D). Suite **3 418 passed / 13 skipped** plus one flake that does not reproduce standalone or under either hash seed; coverage **92.64 %** against the 90 % floor, with `interpreter.py` up from 89 % to **91 %**. Post-refutation: **2 Blocker · 4 High · 6 Medium · 8 Low**.

- **The block is two lines of provenance accounting in `interpreter.py`, and it is narrower than round 6's. WHO issued an event has been replaced by WHEN it arrived.** (a) **R7-01** — an `async def` invoked service publishes its completion on the *public inbox lane* (`:2414`; child-actor `onDone` at `:2882`) instead of the charged priority lane (`_finish_plain_service` → `_deliver_priority`, `:2690`, charging at `:2287-2288`), so it never passes the charging site under *any* value of `_processing`; arriving `from_inbox` it also resets the settle budget every lap (`:1647`). Measured: **28 108 service calls vs 23** for the identical chart with `def`, `last_error=None`, and one variant settles into an **empty configuration** 10/10 while reporting `ok=True` — at the same instant the library's own `get_persisted_snapshot()` refuses as `SnapshotMidStepError`. (b) **R7-02** — external `send(priority=True)` *is* charged to the chain budget: 751 of 1 500 external sends dropped as `chain_budget`, control without `priority=True` drops zero, against the run loop's own promise at `:1510-1516`. Fix (a) by routing coroutine and child-actor completions through `_deliver_priority`; fix (b) by gating the charge on provenance (`_issued_from_own_action()` or an explicit internal flag) rather than on `_processing`.
- **Neither Blocker is wrappable, and this round tested that rather than asserting it.** DC-4: the only mitigation for R7-01 is plain-`def` services, which #174 documents as blocking the machine's own `after` timers — and B19's `backing_off` ladder depends on `after` firing during a service. Our own refutation of R7-04 then showed plain `def` has its *own* inbox-starvation failure on the same shape. **There is no service kind that is safe on both axes.** CV-C32 (async-only services), which is what keeps R6-09's downgrade valid, is precisely what puts every contract machine on the unprotected lane.
- **The round's pattern, recorded because it is the risk going forward:** *"fixed" has meant "fixed on the service kind the test was written against."* It is Amendment 6's lesson one level down. All three pinned regression tests (`tests/test_round6_findings.py:124/184/486`) declare `def svc`, so the library's suite is structurally blind to the lane its own documentation recommends. **Six independently filed findings collapse into R7-01, and one `@pytest.mark.parametrize("kind", ["def", "async def"])` would have caught every one.** A matrix over (engine × service kind) closes both rounds' failure classes permanently. This now binds our own gate too — standing amendment 12 in `20-adoption-gate.md`.
- **Three regressions were introduced by this round's fix work, and the gate cannot see any of them:** R7-02 (Blocker), R7-03 (High — #171's untimed `gather` makes `await start()` hang on a slow child), R7-11 (Medium). The gate itself shows **zero true PASS→FAIL transitions**, confirmed by direct check-by-check JSON diff. That is the point: no check existed for any of the three.
- **What closed, and it is real.** The `send(wait=True)` livelock is dead — 6/6 hangs → 0 on every ablation, 500 fuzzed cyclic configs across both engines with zero livelocks and the trip observable at the same lap count. The root-level snapshot refusal holds across 320 generated parallel machines and 7 622 attempts from 8 distinct windows with zero raw exceptions. The receipt matrix `(denied, error, deferred, changed)` is **injective**. The threadsafe counter balances against a deliberately hostile race. Raw `send()` is the fastest recorded at 257 k ev/s.
- **Constraints — retired:** **W-04a** (#170 makes `Receipt.denied` alone a correct denial discriminator again; the **W-04b** half stands — `onUnhandled:"defer"` still outranks `guard_denied`), **CV-C37** (#171 fixed the children-ready race — `_actors` is populated the instant `start()` returns), and CV-C36's *original* rationale (#157 is verified exactly-once; the rule itself stands on the new grounds of R7-14 and R7-02).
- **Constraints — new:** **CV-C38** no invoke cycle without a bounded attempt counter (linter CV-LINT-XS16) — containment for R7-01. **CV-C39** `await start()` is always bounded via `asyncio.wait_for`; nothing may `await start()` bare — R7-03. **CV-C40** no snapshot before the factory's post-start settle observation — R7-05. **CV-C41** snapshots capture the **root only**; child state is reported upward by explicit `sendTo` — R7-07 and R7-08. **CV-C42** `priority=True` is forbidden outside wrapper code and a non-zero `chain_budget` shed on an external send pages immediately — R7-02 containment only, **not a fix**.
- **Mandatory config block:** unchanged in its keys from Amendment 6 and reproduced with updated annotations in `28-statechart-catalogue.md` §1.3b. The material change is the note that `maxIterations` is **inert against R7-01** for a different and more specific reason than Amendment 6 recorded — not the system-event exemption, but the publication lane — and that the health signal is a **progress counter**, never `status` or `last_error`.
- **Pin:** commit `221ce7c`, **evaluation only; endorsement withheld.** `__version__` still reports `0.8.0` — key on the commit. **Do not pin a 0.8.1 tag cut at this commit:** it would release two silent Blockers and remove the commit-keyed escape hatch. Pin policy on adoption: `xstate-statemachine == 0.8.1` once tagged, **and only if the tag is cut after R7-01 and R7-02 land**.
- **Runtime:** the in-house shim stays on the order path **and on B18**, whose kill-switch path is itself the unbounded shape. Non-order machines move to the library now. B19 is included because CV-C38 bounds its only invoke cycle.
- **Exit condition:** R7-01 and R7-02 closed with pinned tests **parametrised over service kind** → the Blocker row clears and open-High is **4** (R7-03, R7-05, R7-07, R7-08), inside the bar of 5, each with a mechanically enforced mitigation and a contract test. That is decision-table **row 6 — ADOPT WITH CONSTRAINTS**. If R7-03 and R7-05 land alongside (both one-liners in the same file), the count is 2 High. Re-verification recipe: `44-r7-final-readiness-verdict.md` §9.

---

## Amendment 8 — 2026-09-21: round-8 final readiness check of `main` @ `6db65d8` (pre-0.8.1)

**Decision: DEFER for the order path (B1–B9); GO for non-order paths (B10–B17, B19, B20) under CV-C01…CV-C45 as recomputed in `docs/research/xstate/49-r8-final-readiness-verdict.md` §7.** 16 issues verified — **15 fixed in code** (10 clean: #167, #168, #175, #182, #183, #184, #187, #188, #189, #190; 5 narrower than claimed: #179, #180, #181, #185, #186), **1 documentation-only** (#174), **0 not-fixed** — the first round in this series with no not-fixed row. Suite **3 457 passed / 13 skipped** plus one load-sensitive flake that passes 3/3 standalone; coverage **92.70 %** against the 90 % floor. Post-refutation: **1 Blocker · 3 High · 7 Medium · 4 Low** — the best position in eight rounds.

- **The block is one function, and it is the regression surface of this release's own #180. R8-01: the priority lane charges by provenance and sheds by position.** `_deliver_priority` (`interpreter.py:2342-2389`) charges only on `engine_completion`, which is `False` for every public `send(priority=True)` whatever the issuer — so a priority event **issued from an action** is never charged: 2/2 cells livelock past the watchdog with `trip_observable: false`, `status="running"`, `last_error is None`, no drop hook and `start()` never returning, while the plain-lane control on an identical machine is bounded at 27 laps with `RunawayChainError` + a `chain_budget` drop. The shed test (`:1598`, `over = self._raise_depth > limit`) carries **no** provenance test and operates on the same FIFO, so a genuinely **external** priority event arriving at an already-tripped chain is silently destroyed as `chain_budget` — 8–9 of 2 000, `send()` accepted, `last_error is None`; the `priority=False` control loses 0 on both service kinds. The **non**-priority `send()` path already does this correctly at `:898-908` via `_issued_from_own_action()` (#90). Fix: tag provenance on the event at enqueue time, charge self-raised and engine completions, and refuse to shed anything tagged external.
- **It is not wrappable, and the reason is specific rather than rhetorical.** We can ban `priority=True` in our own code (CV-C42, widened) — but the library routes its own completions onto that same queue, so an external priority event our gateway never sent can still be shed; and the self-send half starves the very loop thread any in-process watchdog would run on, so `asyncio.wait_for` never fires. The only detector is out-of-process and keyed on progress counters (CV-C43), which tells you the order path is wedged without stopping it from wedging.
- **The round's pattern, third statement of the same lesson:** *"fixed" has meant "fixed on the issuer the test happened to use."* Round 6 was the engine, round 7 the service kind, round 8 the **issuer provenance and chain state**. R8-01 survived a fix, a pinned upstream test and a full battle round because `tests/test_round7_findings.py:413-520` only ever sends externally into an untripped chain. The general form, now standing amendment 13 in `20-adoption-gate.md`: **when a fix distinguishes two cases, the test must exercise both sides — and the arm expected to fail must be given work that can actually fail.** The corollary has its own finding: `tests/test_round7_findings.py:557` parametrises over `KINDS` but gives the `def` arm `time.sleep(0.05)` against the async arm's `asyncio.sleep(3.0)`, so the parametrisation is decorative and R8-03 shipped green. **A parametrised test whose arms are not equally capable of failing is not parametrised.**
- **What closed, and it is the largest single improvement in the series.** Amendment 7's one ask — parametrise every service-invoking test over `def` / `async def` — shipped. Consequences: the async livelock config fuzz went **58/120 RUNAWAY → 0/120**; a 500-config × 2 spellings × 2 engines sweep found **0 hangs, 0 silent runaways, 0 lap mismatches**; `maxIterations` is a real bound again and **lane-independent** (2 / 5 / 100 → 4 / 7 / 102 service calls, `max + 2` exactly, identical cell for cell); the B18 kill-switch storm that hit **3 547 service calls in 3.0 s**, still accelerating, now **plateaus at 1 002** with `last_error = RunawayChainError`; an 80 s / 200-machine async soak gave 12 350 external priority events with **0 dropped, 0 wedged, 0 torn snapshots, 0 task leaks**. **Both Amendment-7 Blockers (R7-01, R7-02) are closed.**
- **Refutation moved 3 of 6 Blocker/High candidates down and none up**, and two of the three killed claims *we* had rated Blocker or High: R8-02's "a `def` service runs inline and blocks the process" is **false** (#149 moved it to `run_in_executor`; the stall starves only that machine's inbox and is documented at `docs/_guide/production-characteristics.md:93`), and R8-06's security framing is **false** (`structure_hash` is a public unkeyed checksum, not a MAC, so an attacker who can edit the blob needs no version downgrade). Third consecutive round in which our own claims were the thing that did not survive contact — which is the argument for keeping the refutation step.
- **Constraints — retired:** **CV-C38** (no invoke cycle without a bounded attempt counter) — the engine bounds the cycle itself now, verified on the real contract machines at identical lap counts on both spellings; the lint CV-LINT-XS16 is **downgraded from error to warning**, not deleted. **CV-C31′** (no `"rollback"` with a raisable entry action on an `invoke`-carrying state) — retires on the async lane, re-issued as **CV-C31″** for plain-`def` services only, on the different ground that a `def` invoke is not unwound by rollback at all. **The `maxIterations` "inert, do not rely on it" annotation** — it is live again; the one residual inertness (a priority event issued from an action) is recorded in the config block instead.
- **Constraints — widened:** **CV-C42** — `priority=True` is now forbidden **everywhere, on any event, from any origin**, not merely outside wrapper code. Both halves of the lane are unsafe.
- **Constraints — new:** **CV-C43** the order-path liveness signal is an **out-of-process** progress counter; no in-process watchdog may be the sole detector, because the failure being detected starves the thread it runs on — R8-01. **CV-C44** child bring-up is bounded **by us, per child**; entry actions on `invoke`-bearing states are coroutines that yield — R8-03. **CV-C45** completion events are **never accepted from a wire**: the restore path strips every `DoneEvent`/`AfterEvent` from `pending_events` and the gateway rejects externally submitted instances — R8-05.
- **Mandatory config block:** keys unchanged; annotations materially revised and reproduced in `28-statechart-catalogue.md` §1.3b. The substantive changes are that `maxIterations` is **no longer annotated as inert**, CV-C31′ is replaced by CV-C31″, and the health-signal note is strengthened from "progress counters, not `status`" to "**out-of-process** progress counters".
- **Pin:** commit **`6db65d8`** plus its **source sha256**, **evaluation only; endorsement withheld.** `__version__` still reports `0.8.0` — **key on the commit, never the version string**, eight verification passes running. **Do not pin a 0.8.1 tag cut at this commit:** it would release R8-01 and remove the commit-keyed escape hatch in the same motion. Pin policy on adoption: **`xstate-statemachine == 0.8.1` once tagged, and only if the tag is cut after R8-01 lands.** A **vendored copy per MUST-08** is carried for the non-order machines going live now, so a retag or a force-push cannot move what production runs.
- **Runtime:** the in-house shim stays on the order path (B1–B9). **B18 moves out of the library-blocked column** — CV-221-01 is closed and the kill-switch storm is bounded and observable — and into the *ours-blocked* column behind **C-07b**. Shim retirement is phased: B17/B20 now; B10–B15 and B19 as their contract defects close; B16/B18 once C-04 and C-07b are fixed; B1–B9 only after R8-01 lands and then only through the dual-runtime conformance harness on both service kinds.
- **What is now on the critical path is ours, not upstream's, for two machines.** C-04 (B16 elevation survives `LOGOUT`/`REVOKE`) and C-07b (B18 kill switch bricked by a guard-denied `RELEASE`) are Blockers on **any** runtime, on machines the library has already cleared.
- **Exit condition:** R8-01's two repros exit 0 at the commit under test — the self-send livelock terminates bounded with an observable trip on both service kinds, and the external-shed repro loses 0 of 2 000 events against an already-tripped chain — **and** the upstream fix ships with a test parametrised over issuer provenance × chain state × service kind. The Blocker row then clears and open-High is **3** (R8-02, R8-03, R8-05), inside the bar of 5, each with a mechanically enforced mitigation and a contract test. That is decision-table **row 6 — ADOPT WITH CONSTRAINTS, order path included**. Re-verification recipe: `49-r8-final-readiness-verdict.md` §9.

---

## Amendment 9 — 2026-09-22: round-9 final readiness check of `main` @ `f28719c` (pre-0.8.1)

**Decision: ADOPT WITH CONSTRAINTS — on all four lifecycle families, order path included (B1–B20), under CV-C01…CV-C46 as recomputed in `docs/research/xstate/54-r9-final-readiness-verdict.md` §7.** This supersedes Amendment 8's DEFER on the order path. 12 issues verified — **11 fixed in code** (9 clean: #181, #186, #192, #194, #196, #198, #199, #200, #201; 2 narrower than claimed: #193, #195), **1 partial** (#197), **0 not-fixed**, **0 documentation-only**. Post-refutation: **0 Blocker · 2 High · 5 Medium · 8 Low** — the best position in nine rounds, and the trajectory across the series is **4 Blocker · 8 High at round 5 → 0 · 2 now**.

- **Amendment 8's exit condition was met exactly as written, and nothing else had to move.** R8-01 is closed by **#192**: the priority lane's *drop* site now carries the provenance rule its *charge* site already knew — self-issued sends are charged, externally-issued ones are shielded, by issuer rather than by FIFO position. Verified on **both engines and both service kinds**, and on the real B18 kill switch: **12/12 presses accepted, 0 shed as `chain_budget`, and the press pre-empts the chain.** The Blocker row is empty for the first time in the series, which lands decision-table **row 6**.
- **Refutation moved 3 of 5 Blocker/High candidates down and none up — and one of the three was our own headline.** **R9-01 (Blocker→Low):** every forgery vector needs a capability that already dominates the engine — a held engine-minted event, an unexported private class, or arbitrary snapshot authorship — all documented as the intended trust boundary; XState v5 performs **no** provenance check on completions and SCXML 6.4 treats `done.invoke.<id>` as a plain event name, so this library is stricter than both. **R9-03 (High→REFUTED outright):** its "permanent starvation" was an artefact of reading a counter after a fixed `sleep(1.0)` — polling to drain gives **500/500 applied, inbox 0, priority 0** — its "silent, no error" claim was backwards (both lanes now trip `RunawayChainError`, which *is* the #179/#201 fix), and its chart is an unguarded `always` into its own region that the docs already name invalid. **R9-05 (High→Medium):** snapshot authenticity is a documented wrapper obligation, not a library defect. Fourth consecutive round in which our own claims were the thing that did not survive contact — the standing argument for keeping the refutation step.
- **The two open Highs are each one branch of one function, and both are mechanically contained.** **R9-02:** `base_interpreter.py:4523` selects `after` transitions on the **public exported** `AfterEvent`, never on #195's `_EngineAfter`, unlike the `DoneEvent`/`ErrorEvent` branch eight lines below. The decisive vector is a forged `pending_events` record carrying **no `"engine"` flag**, which `_enqueue_restored` (`:1768`) hands straight to the inbox — so **with `strict=True` the machine still fires a 60-second timer instantly from untrusted snapshot data, with no API call at all.** Contained by **CV-C45 (widened)**. **R9-04:** a `def` service armed by a transition an `always` rolls **forward** is still submitted — **3 of 6 lanes leak** — contradicting `docs/_guide/production-characteristics.md:97` verbatim and SCXML 6.4 (`exitStates` removes the state from `statesToInvoke`). Contained by **CV-C32 + new CV-C46**, which together make all three leaking lanes unreachable for us.
- **The round's pattern is a new one, and it is why amendments 12/13 did not catch these.** Rounds 6–8 were "fixed on the axis the test was written against" (engine, then service kind, then issuer provenance). Round 8 followed that instruction and **it worked** — the service-kind axis is now flat across every battle track, and the only surviving `def`/`async` divergence in the whole corpus is R9-04's. Round 9's two Highs are a different shape: **a good mechanism applied to a proper subset of its call sites.** #195 minted three private engine event classes and wired two of three into transition selection; #193 cancelled the `def`-service handoff on the rollback epilogue but not the roll-forward one. Both are *second* incomplete landings of the same fix. Now standing amendment 14 in `20-adoption-gate.md`: **when a fix introduces a trust mechanism, enumerate every call site it governs and assert the list is exhausted.**
- **Two tests upstream are actively misleading, and they are recorded because they shaped our triage.** `test_round8_findings.py::test_always_rollforward_matches_sync` **pins the leaking behaviour** that `production-characteristics.md:97` says cannot happen — so the green suite certifies the inverse of the published claim and R9-04 shipped uncovered. And `test_round6_findings.py::TestAsyncRollbackRearmCycleBounded` fails ~80 % of runs on **correct** behaviour: it reads a counter at 0.6 s when the `def` lane converges at ~1.0 s. We initially carried the latter as a possible regression and **reclassified it after polling to convergence** — both lanes plateau at exactly **1003 = `maxIterations` + 2** and stay there. Together these are standing amendment 15: a test that pins current behaviour while claiming to pin the contract, and a convergence assertion that sleeps a guessed interval, are the two ways a green suite stops meaning anything.
- **Constraints — retired:** **CV-C43** (out-of-process progress counter as the *sole* permitted order-path liveness detector) — its entire ground was R8-01's unobservable livelock, which starved every in-process detector; with that closed, `status` and `last_error` are liveness signals again and the out-of-process counter drops to a **recommendation** we still keep. **CV-C31″** (no `"rollback"` with a raisable entry action on an `invoke`-carrying state, `def` services only) — #193 fixed exactly its ground; the surviving roll-forward half is a different shape carried by CV-C32 + CV-C46, and keeping CV-C31″ would misstate the reason.
- **Constraints — widened: CV-C45.** The restore filter now matches the **serialised record** (`kind` ∈ {`done`, `error`, `after`}) as well as the deserialised class, and the gateway rejection explicitly names `AfterEvent`. This matters because R9-02's decisive vector carries no `"engine"` flag and never passes through a `send()`-time check — a class-only filter would miss it. **This single constraint contains R9-02 end-to-end.**
- **Constraints — new: CV-C46.** The order path **never** runs on `SyncInterpreter`; every order-path machine is constructed on the async `Interpreter` with an explicit `service_pool_size`. Covers 2 of R9-04's 3 leaking lanes, R9-09's sync/async lap divergence, and the `167` sync-only gate FAIL. Enforced by a factory assertion, a lint on direct `SyncInterpreter(` construction, and `test_cv_c46_order_path_engine_is_async`.
- **Mandatory config block:** keys unchanged; annotations revised and reproduced in `28-statechart-catalogue.md` §1.3b. Substantive changes: `maxIterations` is confirmed live and lane-independent with the plateau measured by polling rather than asserted from a changelog; CV-C31″ removed; the engine line now states the order path is async-`Interpreter`-only; the `strict` annotation records its two residuals (R9-02, R9-13) and the containment that covers both.
- **One measurement is owed and is recorded as owed, not as a pass.** The full suite + coverage run did not finish inside the wall-clock bound (~51 % of collected tests observed green; 92.70 % at `6db65d8`). Decision-table **row 2 keys on coverage**, so this is an **open measurement** and it leads the round-10 recipe. Also outstanding: `bench_c_timers`, `bench_e_actors`, and the RSS/open-order figure which is now **unbisected for a third round** (3.10 → 5.18 → 2.128 KB/order) — bisect it or replace the metric.
- **Pin:** **`xstate-statemachine == 0.8.1` once tagged, and only if `__version__` on that tag actually reports `0.8.1`**; until then commit **`f28719c`** plus its **source sha256**. A **vendored copy per MUST-08** is what CI and production build against, so a retag or force-push cannot move what we run. Nine rounds have now keyed on commits because `__version__` reports `0.8.0` on a 0.8.1 tree.
- **Standing gate:** `tests/xstate_contract/` enters CI as a **blocking** gate on **both service spellings** — the 20 contract machines end-to-end, the three mandated drives, the R9-02/R9-04 containment tests, and a lane-matrix pin on R9-04 so an upstream fix is *detected* rather than assumed. This is the mechanism row 6 rests on; a red cell returns us to row 7 (DEFER), because a documented convention is not a mitigation.
- **Runtime:** shim retirement is phased, **order path last and behind the contract suite**. *Phase 1, immediate (B10–B15, B17, B19, B20):* retire the `always`-ordering shim (#196), the `children_timeout` wrapper bound as a mandate (#194), the one-sided-agreement restore check as primary gate (#186) and the `on_interpreter_start` guard as primary gate (#199) — each after one green nightly on both spellings. *Phase 2 (B16, B18):* **blocked on us, not the library** — both are LIBRARY-GO; **C-04** and **C-07b** are catalogue Blockers on any runtime. *Phase 3 (B1–B9, B18):* five consecutive green nightlies, CV-C45/C32/C46 linted and covered, the coverage measurement completed at ≥ 86 %, and a two-week low-notional canary.
- **For the first time in this study, the binding constraint on our order path is our own catalogue, not the library.** C-04 (B16 elevation survives `LOGOUT`/`REVOKE`) and C-07b (B18 kill switch bricked by a guard-denied `RELEASE`) are the only Blockers of any kind left open, they are ours, and they should be the next thing worked.
- **What would reverse this decision:** a red contract-suite cell; coverage returning below 86 % when the full run completes; evidence that CV-C45 does not in fact contain R9-02 (a vector reaching `:4523` without passing the gateway or `_enqueue_restored`); or a third round of the same fix landing incompletely. The honest ceiling for this library in our system is **row 8**, not row 9 — BENCH-1 and BENCH-2 miss by ~3× and ~14× respectively, which are architectural gaps, so the dedicated-loop rule, the ≥99 % pre-filter and the external `MonotonicScheduler` are permanent features of our design rather than temporary mitigations.

---

## Amendment 10 — 2026-09-22: round-10 final readiness check of `main` @ `19cb1f1` (pre-0.8.1, merge of PR #211, commit `4dbf86e`)

**Decision: ADOPT WITH CONSTRAINTS — decision-table ROW 8**, up from Amendment 9's row 6, on all four lifecycle families (B1–B20), under CV-C01…CV-C50 as recomputed in `docs/research/xstate/59-r10-final-readiness-verdict.md` §7. Row 8 is *"all Blocker **and High** closed, all Medium triaged, benchmark thresholds not all met"*: **the constraints that remain are benchmark-derived architectural consequences, not containment for open library defects.** Amendment 9's own closing line named row 8 as the honest ceiling for this library in our system. **We have reached it.**

8 issues verified — **all eight FIXED, clean: 0 partial, 0 not-fixed, 0 documentation-only.** Post-refutation: **0 Blocker · 0 High · 5 Medium · 7 Low**, plus 1 refuted outright. Trajectory: **4 Blocker · 8 High at round 5 → 0 · 2 at round 9 → 0 · 0 now.**

- **Amendment 9's exit condition was met in full, and both of its open Highs are closed at the sites it named.** **R9-02 → #203:** `base_interpreter.py:4624` now gates `after` selection on `isinstance(event, AfterEvent) and is_system_event(event)` — the same test the `Done`/`Error` branch eight lines below already used, which is exactly the one-line fix Amendment 9 specified. The discriminating control is dead: a public `AfterEvent` with the correct type string, which fired a 60-second timer instantly at the **default `strict=False`**, is now refused at `send()` with a named `UnknownEventError` on both spellings. **R9-04 → #204:** invoke arming moved into the eventless settle pass per SCXML §6.1 `statesToInvoke`, closing the roll-forward half on **both engines and both service kinds** — roll-forward submissions 0/8 cells, the `LD-01` lane matrix **3 leaks → 0 of 6**, B6–B10's `def` lane 51/52 → **52/52**, mandated drives 13/14 → **14/14**, and `167 rollback_reinvoke_spin` — which Amendment 9 recorded as a *permanent* expected-failure and built CV-C46 around — now passes **5/5 stably**.
- **This is the first round in ten where every fix landed on every axis it claimed.** Rounds 6, 7, 8 and 9 each found at least one fix holding on one engine or one service spelling and not the other; Amendment 9 warned that a third occurrence would "stop being a bug pattern and start being a process signal." Round 10 finds **zero**. The service-kind axis is now flat across the entire corpus, save the one documented, intended divergence (a `def` service is non-preemptable — `production-characteristics.md` §2).
- **The measurement Amendment 9 owed is discharged, and it was the largest single risk on the board.** Decision-table row 2 keys on coverage and fires *before* any adoption row. The suite finished this round: **3505 passed, 13 skipped, 0 failed, 566.57 s, coverage 92.78 %** — above the library's own 90 % floor and our 86 % bar, and up from 92.70 % at `6db65d8`. Row 2 is now not-triggered **on measured evidence rather than inference**.
- **Refutation moved all three Blocker/High library candidates down and none up — the fifth consecutive round in which our own claims were what did not survive, and the first in which it was total.** **R10-01 (Blocker → Low):** seven engine-event forgery vectors, every one reproducing exactly as filed — but they partition into **Class A** (in-process Python: `engine_after`, `type(held)(...)`, `pickle`, `deepcopy`, `_EngineAfter`, `_replace`), which is *strictly weaker than its own premise* since a plain registered action already writes context arbitrarily and a live `Interpreter` exposes `_enter_states`/`_exit_states`; and **Class B** (blob-write), where rather than accept the library's claim we tested it and found **a hand-edited snapshot with no event forgery whatsoever** restores the machine to an arbitrary state with arbitrary context. The flag adds zero capability over what the blob writer already holds, and the boundary #195/#203 actually target — external name/shape confusion — **holds in every probe** under `strict: True` + `onUnhandled: "error"`. **R10-02 (High → REFUTED outright):** a self-targeting `onDone` is an **internal** transition by contract; XState v5 makes internal the default with `reenter: true` the opt-in, and the library documents this three times including a troubleshooting entry naming this exact wedge shape. With `"reenter": true`, polled to convergence on both engines and both kinds: `entries == submits == 22 == maxIterations + 2`, `RunawayChainError`, stranded hook fired — **zero violations**. **R10-03 (High → Medium):** real, but implied by the #206 changelog and `json-config.md:110`, and the **documented** `after` idiom measures 93/92 beats in 3 s with zero drops against 9 for the `raise(delay=)` spelling.
- **On the contract side, two Blockers and two Highs came off the library's ledger — and this time we proved it by construction rather than by argument.** **R10-C1 → our C-04:** our chart omits the revocation events from the elevation region, while `REVOKE`, listed in *both* regions, clears correctly — which proves engine dispatch is sound; the corrected chart passes on both engines and both spellings. **R10-C2 → our C-07b:** `onUnhandled: "error"` is documented opt-in policy and a guard-denied event *is* an unhandled event (#170); SCXML §3.13 and XState v5 agree, and neither spec even defines an error-on-unhandled disposition — the fix is in our config alone. **R10-C3 (High → Medium):** `stale_lockout` **is** escapable by the operator via `RECONNECTED`, so the High premise fails. **R10-C4 (High → REFUTED, Low):** the kill event is declared only on *sibling* states — sibling-only 1.458 s versus **0.001 s** with an ancestor handler.
- **Contracts: 20/20 build clean on both service spellings, with ZERO library defects across all four groups.** A first in the study.
- **Constraints — retired: CV-C46** (the order path never runs on `SyncInterpreter`). Its entire ground was R9-04's sync-engine leaks, and `167` now passes 5/5 on that lane; it drops to a **design preference**, since the async engine remains our order-path engine for throughput and preemptability. **CV-C45's send-side clause** retires on the same basis — #203 closes it in the engine. **CV-C32 retires as a *safety* rule** while the rule itself stands verbatim, re-grounded on R10-D2 (an invoke-bearing state with an escape transition cannot be pre-empted on the `def` lane) rather than R9-04. Keeping the old justification is how constraints rot.
- **Constraints — widened: CV-C45 (restore side only).** Strip `Done`/`Error`/`After` records matching the **serialised `kind`** as well as the class, **and re-arm deadlines explicitly from context** — because a pre-0.8.1 persisted `after` record is now silently *refused* rather than demoted (R10-05), with no raise, no warning and nothing on `last_error`.
- **Constraints — new (5): CV-C47** no `raise(delay=)` self-paced periodic work on the async engine (R10-03) · **CV-C48** 0.8.0-era snapshots migrated before restore, with a refused deadline made loud in our code since it is silent in the library's (R10-05) · **CV-C49** no snapshot while a delayed self-`raise` debt is armed (R10-04) · **CV-C50** `CvErrorHooks` implements `on_invocation_stranded` and samples `on_event_dropped(..., "chain_budget")`; **never poll `last_error`, which is cleared on the `async def` lane and retained on `def`** (R10-13) · **CV-C4x** kill/cancel declared on an ancestor of every invoking state, statically lintable (R10-C4).
- **Mandatory config block:** keys unchanged; annotations revised and reproduced in `28-statechart-catalogue.md` §1.3b. Substantive changes: the `strict` annotation records #203 closing R9-02 and the two surviving restore-side residuals; the `maxIterations` annotation records that **cross-engine budget equivalence is NOT a safety property** on engine-work-only charts (R10-06: async ~`3·mi+3`, sync ~`2·mi+3`, 24/25 limits differ); a new self-transition rule requires `"reenter": true` on any self-targeting transition meant to restart a state's invoke or entry; and the engine line records CV-C46's retirement.
- **Benchmarks:** **BENCH-2 still misses** (443.6 market ev/s vs a 2 000 budget — ~4.5×, down from ~14×) and **BENCH-6 is UNMEASURED for a second consecutive round** (`bench_c_timers` timed out at 115 s with zero output, because it buffers all results to a single JSON dump). BENCH-1 reads as met (p95 144.6 ms vs 300 ms) and `bench_a` moved ~5× — but **no matched-load A/B was run**, the policy *ratios* held steady while the absolute baseline moved, and **neither improvement is relied upon**. The RSS/open-order figure is now **unbisected for a fourth round**: bisect it or replace the metric.
- **Pin:** **`xstate-statemachine == 0.8.1` once tagged, and only if `__version__` on that tag actually reports `0.8.1`**; until then commit **`19cb1f1`** plus its **source sha256**, vendored per MUST-08. **We would pin a tag cut at this commit**, with one blocking precondition (bump `__version__`, still reporting `0.8.0` for a tenth round) and three doc fixes preferred in the same release.
- **Runtime — Phase-3 order-path shim retirement MAY BEGIN.** Both gating Highs are closed and Phase 3's one measurement precondition (coverage ≥ 86 %) is met at 92.78 %. The three remaining acceptance conditions carry **no library dependency whatsoever**: five consecutive green nightlies of the contract suite on both spellings; CV-C45 (restore), CV-C47, CV-C48, CV-C49, CV-C50 and CV-C4x linted and covered by their named tests; and a two-week low-notional canary. **CV-C42, CV-C23's HMAC clause and the wrapper attempt counter do not retire in this phase** — they answer Mediums that remain open. **B18's shim retires with Phase 2, not Phase 3**, since C-07b gates it on any runtime.
- **The binding constraint on our order path is now entirely our own catalogue, and round 10 removed the last ambiguity about that.** **C-04 and C-07b are the only Blockers of any kind left in this ten-round study, they are ours, and they are open five rounds.** This round we built the corrected charts and watched them pass on every engine and every spelling — the engine follows the chart in every cell. They should be the next thing worked.
- **What would reverse this decision:** a vector reaching the `after` or `done` selection site from genuinely *outside* the process — neither attacker-controlled Python nor blob-write — which would restore R10-01 toward Blocker and put CV-C45's send-side clause back on duty (the refutation is falsifiable by construction and should be attacked first in round 11); coverage or the suite regressing on a later commit (row 2 outranks everything here); a catalogue machine turning out to depend on the `raise(delay=)` spelling, which returns R10-03 to High; a failed restore drill on R10-05's migration cliff; a fourth round of "fixed on one axis only"; or a 0.8.1 tag cut with `__version__` still reporting `0.8.0`. **Row 9 remains out of reach and we still do not plan for it** — the dedicated-loop rule, the ≥99 % pre-filter and the external `MonotonicScheduler` are permanent features of our architecture, not temporary mitigations.

---

## Amendment 11 — 2026-09-22: round-11 final readiness check of `main` @ `c78ce99` (pre-0.8.1, merge of PR #217, `fix/0.8.1-round10`)

**Decision: ADOPT WITH CONSTRAINTS — decision-table ROW 6**, *down one row* from Amendment 10's row 8, on all four lifecycle families (B1–B20), under CV-C01…CV-C62 as recomputed in `docs/research/xstate/64-r11-final-readiness-verdict.md` §7. Row 6 is *"all Blockers closed, 1–5 High open, each with a mechanically enforced mitigation and a passing test."* **The regression is real and it is not cosmetic:** row 8 meant every remaining constraint was an architectural consequence of our own benchmarks; row 6 means **one of them is containment for an open library defect**. 5 issues verified — **all five FIXED (#212–#216), 0 partial, 0 not-fixed, 0 regressed-on-one-axis.** Post-refutation: **0 Blocker · 1 High · 4 Medium · 5 Low.**

- **Amendment 10's position held on every axis except one, and the exception is a memory leak.** The release is unambiguously better than `19cb1f1`; our position is one row worse, because **the release made a legal usage that leaks**. Both statements are true simultaneously and the amendment records them together deliberately.
- **Second consecutive round in which every fix landed on every axis it claimed** — both engines, both service spellings. The service-kind axis, which produced six independent findings at round 7 and drove Amendment 7's single ask, has now been **flat across the entire corpus for two rounds**. That ask is fully paid off.
- **The round's one sentence: #212 opened no *semantic* hole, and it made a latent *resource* defect unbounded.** **R11-04 (the only open High):** `_timer_handles` retains **exactly 1.00 handle per `raise(delay=)` beat, for ever**, on both engines and both action kinds. `_schedule_send` keys the handle under `self.id` — the **machine** id — while the only pruner pops `_timer_handles[state.id]` on **state exit**, and the machine id is never an exiting state. The `after:` path uses `owner_id=state.id` and is **flat at 0.003/beat** under identical load. Measured on the container rather than inferred from RSS: **+455 MB / 24 s at 200 machines, strictly linear, no plateau**, polled to convergence at two independent sampling schedules. Before #212 it was capped at ~12 entries only because #206's trip killed the cycle first — which is why Amendment 10's soak read +1.2 MB and saw nothing. **One line per engine to fix**, and the correct pattern already exists four hundred lines away in the same file.
- **The interaction is what makes it binding rather than cosmetic.** #212 explicitly *endorses* the shape that leaks, and #213 makes `raise(delay=)` the **only restart-safe in-chart deadline primitive** (since `after` deadlines are deliberately not persisted, #128). So the documented path to snapshot-safe deadlines is currently also the leaking one, with no in-API way to avoid it. This is recorded as the **R11-04 / R11-DC-2 / K11 tension**, and landing the upstream one-liner dissolves it entirely.
- **It is contained by a lint we already run, and that is the whole difference between ADOPT and DEFER.** **CV-C47** was written in Amendment 10 against a *different* finding (R10-03, the heartbeat dying at `maxIterations`) and happens to ban exactly the shape that leaks. Had it not existed and been green, this round would be **row 7 — DEFER**. We did not have to invent a mitigation under pressure, which is the strongest practical argument this study has produced for writing constraints down early and precisely.
- **Both of the round's framing questions answer NO, and both were answered by controls rather than by argument.** **(1) Did #212 re-open any bounded-cycle class?** No: a purpose-built collateral-unboundedness probe found no previously-bounded shape that became unbounded (both lanes, watchdogs); the gate's 163 checks and a 527-script sweep produce **exactly one** stable PASS→FAIL delta, and it is **our own test encoding the #206 rule #212 deliberately reverses** (retired, not reported). **(2) Did snapshot v3 or the v2-upcast-as-engine-minted rule re-open the #195/#203 forgery boundary?** No: both candidates were filed at Blocker/High and **both died on control probes**.
- **Refutation moved every Blocker/High candidate down and none up, for the fourth round running — and the two the round's framing pointed at hardest are the two that fell.** **R11-01 (Blocker → Low doc nit):** the `"version": 2` downgrade really does mint `engine: true` onto forged completion records, but **an attacker who can edit `version` can equally edit `state_ids` and land in the target state with no event forgery at all**; `from_snapshot` is a **documented trusted-input boundary** (#205 applies `state_ids`/`configuration`/`context` verbatim, and `machine_hash` is explicitly *not a MAC*), and `minimum_version=3` raises `SnapshotVersionError` on the forged blob. **R11-03 (High → REFUTED, None):** control V1 — the only vector reachable from the documented public API — is **correctly refused with `UnknownEventError`**, which is precisely what #195/#203 claim; the other three vectors need a non-exported module, an already-held genuine engine event, or blob-write that reaches the target with no event at all. **R11-05 (High → REFUTED, none):** plain `after:` at the same sub-millisecond delays behaves **identically on the same charts** and has been exempt from `maxIterations` since long before #212 — the reversal opened no escape, it achieved **parity** with a path the budget never bounded by design. **R11-02 (High → Low):** no trust boundary crossed; what survives is an observability-grade contract inconsistency.
- **Third consecutive round in which a Blocker filed against engine-event provenance was refuted by our own probe — promoted from refutation step to triage precondition.** Standing amendment 18: *any finding whose threat model requires blob-write must first be tested against "what does the same writer achieve with `state_ids`/`context` alone?"* If the answer is "the same thing", it is hardening, not a vulnerability. **Corollary for our own documentation: the boundary is the HMAC tag on the blob (CV-C53); `strict` and `minimum_version` never were boundaries and must not be described as such.**
- **Constraints — three different outcomes from one release, which is why re-grounding is now mandatory.** **RETIRED: CV-C48** (its entire ground was R10-05b, the 0.8.0 `after`-record migration cliff, which **#214's v2 upcast closes** — and the security objection to that upcast was refuted, so there is no reason to re-erect the fence) and **CV-C45's stripping clause** (records are now admitted correctly and refusals are strict-checked). **REWRITTEN: CV-C49** — #213 persists the armed-delay debt exactly (600/600), closing its R10-04 ground, so it becomes *"never re-persist an interpreter that has not been `start()`ed"* on R11-08's mirror-image hop. **STANDS, WIDENED, NOW LOAD-BEARING: CV-C47** — its R10-03 ground is gone and R11-04 replaced it. Three constraints, three outcomes, and only an explicit per-constraint pass distinguishes them → **standing amendment 20**.
- **CV-C12 (`after` banned in catalogue machines) STANDS UNCHANGED, and the reason matters.** #212 did not touch `after`'s drift characteristics; it made `raise(delay=)` *equal* to `after`. CV-C12's ground is **BENCH-6**, which is not merely still missed (174.4 ms against ≤100 ms at last measurement) but **has now gone unmeasured for four consecutive rounds**. A constraint whose ground has not been re-measured cannot be retired — retiring it would be a decision made on absence of evidence. **Net effect of #212 on our timer rules: zero relaxation, one tightening.**
- **Constraints — new (12): CV-C51** no entry/exit action may await a receipt on its own interpreter (R11-06) · **CV-C52** `minimum_version=3` at every restore call site · **CV-C53** the snapshot journal is an integrity-protected artefact, MAC'd at rest · **CV-C54** reconcile persisted vs admitted record counts on restore · **CV-C55** no `delay` below 10 ms anywhere, either spelling · **CV-C56** every `start()` wrapped in `wait_for`, a timeout being a hard startup failure and never a retry (supersedes CV-C39) · **CV-C57** the wrapper runs its own **recursive** state-node key check · **CV-C58** never re-persist an un-`start()`ed interpreter · **CV-C59** never poll `last_error` for chain health · **CV-C60** read `last_error`/`last_transition_ok` immediately after `from_snapshot` and before `start()` · **CV-C61** the three-way timer split with a `_timer_handles` gauge · **CV-C62** budget sizing accounts for both plateaus. Plus three catalogue lints: stable `send_id`; **never register a user action colliding with a built-in** (a collision silently disarms the built-in — `beats=0`, `last_error=None`, no warning); `SimulatedClock` fires neither `after` nor restored `scheduled_sends`.
- **Mandatory config block:** one **new mandatory key** — `"strictConfig": true` (#216), set alongside the `strict_config=True` kwarg. Annotations substantially revised and reproduced in `28-statechart-catalogue.md` §1.3b: the `strict` annotation now records that **`strict` is not and never was a snapshot boundary**; the `maxIterations` annotation records that **it never bounded delayed work on any commit** and that a trip is erased by the next event; and the timer section is rewritten as the explicit three-way split.
- **Measurement debt is now the largest open risk on the board, and it is ours.** The full suite did **not** complete for the **third consecutive round** (~4 % of 3535 reached, **zero failures observed**), so decision-table row 2 — which fires *before* any adoption row — rests on Amendment 10's one-commit-stale **92.78 %**. Supporting evidence at this commit: `test_round10_findings.py` 15/15, and round8+9+10 **65/65 under both `PYTHONHASHSEED=1` and `=2`**. **BENCH-6 unmeasured for four rounds** while CV-C12 stands on it. Round 12 must run **the full suite alone and first**, then **BENCH-6 alone**.
- **Contracts: 20/20 LIBRARY-GO, ZERO library defects across all four groups, both spellings — second consecutive round.** B1–B5 **356 checks / 0 FAIL**. `strictConfig: true` applied to all 20 machines found **0 unknown root keys** — but per R11-07 its value is ~95 % unrealised until the recursion lands upstream, since our typo surface is ~200 state nodes, not ~10 root keys.
- **Pin:** **`xstate-statemachine == 0.8.1` once tagged, and only if `__version__` on that tag actually reports `0.8.1`** — it has been wrong for **eleven consecutive rounds**; until then commit **`c78ce99`** plus its **source sha256**, vendored per MUST-08. **We would pin a tag cut at this commit**, in preference to `0.8.0` and to `19cb1f1`, **with CV-C47/CV-C61 enforced in CI**. Staying on `19cb1f1` would keep the #206 rule, the unpersisted-deadline gap and the migration cliff — and `19cb1f1` leaks too, merely capped because a different defect kills the cycle first.
- **Runtime — Phase-3 order-path shim retirement CONTINUES.** R11-04 is **not** a Phase-3 gate: it is contained by a green lint and touches a primitive **no catalogue machine currently uses** (K11 — all 20 machines have zero `after` transitions and zero `raise(delay=)` actions). It **becomes** one the moment K11 is addressed, which is the direction E50 is heading, so that item is explicitly blocked on the upstream fix. The binding constraint is now the **CV-C5x test/lint build-out**, of which **CV-C57's recursive validator does not exist yet** and is the least-defended item.
- **C-04 and C-07b remain the only Blockers of any kind in this eleven-round study, they are ours, and they are now open SIX rounds.** Both were refuted as library defects in Amendment 10 by corrected charts that pass on both engines and both spellings; both are fixable **in config alone**; the Amendment-6 removal for C-07b still has not landed in `ka_killswitch`. They gate the two-week canary, and nothing else on this board does.
- **What would reverse this decision:** (a) **R11-04 fixed upstream → row 6 returns to row 8 immediately** — one line per engine, the single most valuable change available; (b) a completed suite run at this commit that **fails or drops coverage below 86 %** → row 2 fires and the verdict becomes **DEFER** regardless of everything else, which is why the measurement debt is the top risk; (c) **BENCH-6 measured and met** → CV-C12 retires and, with (a), the timer tension disappears from both ends; (d) a catalogue machine that genuinely requires a restart-safe periodic deadline → R11-04 becomes Critical **for us specifically**, since the containment is only free while K11 holds.

---

## Amendment 12 — 2026-09-23: round-12 final readiness check of `main` @ `de2da4e` (pre-0.8.1, merge of PR #223, `fix/0.8.1-round11`)

**Decision: ADOPT WITH CONSTRAINTS — decision-table ROW 8**, *up two rows* from Amendment 11's row 6 and level with Amendment 10, on all four lifecycle families (B1–B20), under **CV-C01…CV-C64** as recomputed in `docs/research/xstate/69-r12-final-readiness-verdict.md` §7. Row 8 is *"all Blocker and High closed; all Medium triaged; benchmark thresholds not all met."* **The recovery is not cosmetic and it is the mirror image of Amendment 11's regression:** row 6 meant **one of our constraints was containment for an open library defect**; row 8 means **every remaining constraint is an architectural consequence of our own benchmarks again**. 5 issues verified — **all five FIXED (#218–#222), 0 partial, 0 not-fixed, 0 regressed-on-one-axis**, and **3 of the 5 carry no scope residual at all**, a first. Post-refutation the **library** board is **0 Blocker · 0 High · 3 Medium · 6 Low**.

- **Amendment 11's regression is reversed at the mechanism, which is the only way a row should ever be recovered.** **R11-04** — `_timer_handles` retaining exactly 1.00 handle per `raise(delay=)` beat for ever, measured last round at **+455 MB / 24 s at 200 machines, strictly linear, no plateau** — is closed by **#218**. The evidence is of the kind that permits retiring a constraint rather than merely failing to find the defect: our round-11 repro **unmodified** now exits 0; a 200-beat heartbeat holds **peak 1 handle** on every engine/kind cell; a 500× arm/cancel storm peaks at **0** handles with **no double-release**; cancel-after-fire is a clean no-op; `stop()` releases; and the soak that read **+753 MB** now reads **RSS Δ 0.00 MB over 93,168 beats** at `handles_max_per_machine = 1`. Amendment 11 stated that closing R11-04 would flip the row. It closed, and it flipped.

- **The round's one sentence: the release fixed two library regressions and introduced one, and the one it introduced breaks a pattern our own architecture banned in round 5.** #218 closed the resource regression and **#219 closed the liveness one** (R11-06's *silent, permanent* `start()` deadlock with `last_error = None`, `status = running` and a legal configuration — now a loud immediate `ReentrantWaitError`). The net-new regression is **DE-L1**: #219's guard rides an **inheritable `ContextVar`**, so `asyncio.ensure_future` / `create_task` copy `_ACTIVE_ACTION_OWNER` into a spawned task **for its whole life**, and the guard cannot distinguish "in-step" from "descended from a step". It therefore refuses the **documented escape hatch itself** whenever the spawning action yields again, and refuses a background worker born in an action **300 ms after the machine goes idle** — shapes in which no deadlock is possible. The pinned upstream test passes only because its action returns immediately: **the idiom's safety is scheduling luck, not a property of the API.**

- **The row-deciding call was made in the open, with a falsifier attached, and it is the part of this amendment most worth attacking.** DE-L1 was **filed High** and is **resolved at Medium** on four independent grounds: (i) every refused shape has a deterministic documented alternative that we already mandate — **CV-C25** has banned external `send()` from inside an action since round 5, and **CV-C51** bans the self-receipt await outright; (ii) the failure is **loud and immediate**, where *every* High in this twelve-round study has been a **silent** failure; (iii) it is **strictly safer than the behaviour it replaced**, and scoring an improvement above its worse predecessor would be incoherent; (iv) **zero instances across 573 scripts and 20 contract charts**. **Falsifier, recorded so this can be overturned rather than re-argued: produce a shape with no fresh-context and no gateway alternative — or a catalogue action that must genuinely both emit and confirm within one step — and DE-L1 returns to High, taking the gate back to row 6.** Neither exists today.

- **Both round questions were answered NO, and both were answered positively rather than by assumption.** *Did #219 — a genuine breaking change — require any change to our catalogue actions?* **Zero changes.** A scan of all 573 sweep scripts and every failure tail finds **no script that raises, catches or mentions `ReentrantWaitError`**; our ≈30 `wait=True` call sites all await from **outside** an action; and the three plausible determinism-track candidates were individually audited. **This is CV-C25 doing its job, not luck, and the amendment records it as anticipation** — the strongest practical argument this study has produced for writing constraints down early and precisely, now demonstrated twice (CV-C47 containing R11-04 last round, CV-C25 absorbing #219 this round). *Did #220's new recursive key check reject any of our catalogue JSON?* **There is no rejection to adjudicate:** 20/20 charts build clean, **0 warnings, both lanes**, with **both controls positive** — planted nested typos refused **40/40** with path-named findings, and a full valid-key grammar (including `x-` / `meta` / `description` / `tags` at every level) accepted with **0** findings. **The load-bearing consequence is retroactive: nothing in B1–B20 was ever silently dropping an entry action or a transition**, a fact that could not be established before #220 existed and which validates the contract results of Amendments 4–11.

- **The measurement debt split, and the half that was paid changes what row 2 rests on.** **PAID:** the full suite **completed for the first time in four rounds** — **3545 passed, 13 skipped, 0 failed, 92.87 % coverage**, measured **at the commit under test**. Decision-table row 2 fires *before* any adoption row, and it no longer rests on a one-commit-stale carry-over. The diff **weakens no test**: `+794 / −1` lines, no `xfail`, no `skip`, and the single test edit *strengthens* a #219 pin while adding an assertion. Determinism: **59/59 under `PYTHONHASHSEED=1` and 59/59 under `=2`**. **NOT PAID: BENCH-6 is unmeasured for a FIFTH consecutive round**, and `bench_h_candleviewer_budgets` took **BENCH-1 and BENCH-2** down with it purely by sharing a timeout. **Row 9 is refused explicitly and on the record: *unmeasured* is not *met*, and a row that requires all thresholds met cannot be reached by absence of evidence.** The distance from row 8 to row 9 is one benchmark script that has not had a dedicated time slice in five rounds — **and it is ours.**

- **Constraints: the first retirement in this study driven by a defect being FIXED AT THE MECHANISM rather than by a rule being superseded — and it was tempting not to make it.** **CV-C47 RETIRES**: it had two grounds and both are closed (R10-03 by #212 in Amendment 11, **R11-04 by #218** now), across the fire, cancel, supersede and `stop()` paths. **CV-C61 retires with it**, having existed only to narrow CV-C47's ban around R11-04. CV-C47 had been re-grounded once already and had just proved its worth by containing R11-04, which makes it *feel* earned — but **a constraint with no surviving ground is not a safety margin, it is rot**, and rot in a lint file is what trains engineers to route around the linter. The discipline that makes the retirement safe is stated with it: retire the **rule**, keep the **instrument** (the `_timer_handles` gauge, demoted from mitigation to **telemetry** under CV-C28′ — it is what let us assert `1.00 per machine` rather than "we saw no growth"), and say explicitly what does **not** move: **CV-C12 STANDS UNCHANGED**, because its ground is BENCH-6 and **#218 fixed a handle-*retention* defect while saying nothing about *drift under load*** — retiring CV-C12 on #218's strength would answer a timing question with a memory measurement. **Nothing becomes newly legal for algo timing.** Also: **CV-C52 RE-LABELLED** (`minimum_version=3` is **hygiene, not a security control** — R12-02 demonstrates it by refusing a forged v2 blob while leaving the equivalent v3 verbatim write untouched); **CV-C51 and CV-C59 become agreements with the runtime rather than substitutes for it**, since #219 and #222 now enforce what they assert — the healthiest state a constraint can reach short of retirement; **CV-C57 re-grounded on Q-5** (#220 does not recurse into an inline-machine `invoke.src`); **NEW CV-C63** (chain-trip durability is the wrapper's job — the latch is process-local, so a restart silently resets "this machine discarded work" to zero) and **NEW CV-C64** (no action may await *or hand out an `ensure_future` receipt for* a `send(wait=True)` on its own interpreter; **run this lint BEFORE the dependency bump**, and cover the `def`-lane unawaited-`_Awaitable` shape too). **Net: 2 retired, 2 new, 62 standing — the count is flat and the character has changed: for the first time since Amendment 10, no constraint on this list is containment for an open library defect.**

- **Refutation moved every Blocker/High candidate DOWN and none up, for the fifth round running, and the security board is now Info.** Three library candidates, all filed Blocker: **R12-02 REFUTED** (the forged `"version": 2` upcast mint — reproduced exactly, then killed by its own control, since a plain v3 blob writing `configuration`/`context` verbatim reaches the **identical** outcome; the proposed mitigation refuses the forgery while leaving the trivial path open, **proving the trust boundary — not `upcast` — is load-bearing**; merged sources **D11-fuzz-1, D11-semantics-1 and R11-01 fall with it**); **R12-03 REFUTED** (no forgery vector uses only the public API); **R12-01 DOWNGRADED to Low** (the `engine` flag **is** consulted on the `scheduled_sends` path — without it the record restores as a public `Event` with `e.data == {}` and the payload never arrives). **Fourth consecutive round in which a provenance Blocker died on the same control probe.**

- **Contracts: 20/20 build clean under the new recursive `strictConfig`, 0 warnings, both spellings; ONE library defect across the entire contract corpus (DE-L1).** B1–B5 and B6–B10 and B11–B15 and B16–B20 all drive end to end on both lanes with a snapshot/restore round-trip at every quiescence point, `chain_trips == 0` on every happy path across all twenty charts, and **0 spurious `SnapshotMidStepError`**.

- **Pin:** **`xstate-statemachine == 0.8.1` once tagged, and only if `__version__` on that tag actually reports `0.8.1`** — it has been wrong for **twelve consecutive rounds**; until then commit **`de2da4e`** plus its **source sha256**, vendored per MUST-08. **We would pin a tag cut at this commit, with NOTHING required to land first — and this amendment recommends cutting and tagging 0.8.1 here.** The one thing that must ship **with** the tag is the `__version__` bump, in the same commit: harmless while unreleased because we key on the commit, but a *released* build carrying a wrong version string becomes a **distributed** problem that cannot be re-cut quietly.

- **Runtime — Phase-3 order-path shim retirement CONTINUES, and the library is no longer the binding constraint on any Phase-3 gate.** G-P3-1 (library adoption) is **met**. G-P3-2 is met for **17 of 20** charts. **G-P3-3 — the linter and `tests/xstate_contract/` — is NOT met and remains the single gating condition, and it matters more at row 8 than it did at row 6**: the entire row-8 argument rests on constraints being *mechanically enforced*, and an unenforced rule is not a rule (MUST-09). **G-P3-4 (the two-week order-path canary) is blocked by R12-13 and R12-14 only.** Note that Amendment 11's K11 caveat is now moot from the library side: R11-04 was the reason a restart-safe periodic deadline was blocked on an upstream fix, and #218 removed it.

- **The only Blockers in this twelve-round study remain OURS, and they are now open SEVEN rounds.** **R12-13** (B16 — elevation outlives the session; 12/12 lanes fail across both engines, both service spellings and four kill events) and **R12-14** (B18 — one guard-denied `RELEASE` under `onUnhandled: "error"` makes the machine fatal and **bricks the kill switch**; the subsequent *authorised* release is accepted by `send()` and silently dropped, `bricked: true`). Both are **config-only**; both fixes are proven (`f9_c04_c07b.py` 6/6, `fC_sharp.py` 13/13); the Amendment-6 removal for C-07b **still has not landed in `ka_killswitch`**. **A correction to our own prescribed remedy is recorded here because it would otherwise ship wrong:** the C-04 root hoist to a final `elevation.dead` state fixes **only 9 of 12 lanes**, because the deeper `elevated.on.REVOKE` handler **outranks the root arm** — **the region-level `REVOKE` handler must also be deleted.** Plus **R12-15** (B19 — under `onUnhandled: "defer"` an `OPERATOR_RESOLVED` event with no arm in `stale_lockout` **parks forever**, leaving an account locked until process restart): **High**, ours, config-only, fix verified in both lanes. **Three chart defects, three unmeasured benchmarks, one unshipped linter — six open items, and not one is upstream.**

- **What would reverse this decision:** (a) **a shape that genuinely needs an in-step self-receipt or an `ensure_future` receipt** → DE-L1 returns to High → **row 6**; (b) **`_timer_handles` growth reappearing on any shape** → CV-C47/CV-C61 **un-retire**, R11-04 reopens at High → row 6 (the retained gauge is precisely how this stays detectable, and it is the reason the retirement is safe to make); (c) a suite failure or coverage below 86 % at a future commit → **row 2 fires and the verdict becomes DEFER** regardless of everything else; (d) a `PASS → FAIL` delta that survives ×5 serial re-runs and is not superseded by a documented rule change → the first **true** regression in six rounds; (e) a forgery vector using **only** the public API that achieves more than the `state_ids`/`context`-only control → the security board reopens. **What would improve it: BENCH-6 measured AND met**, together with BENCH-1 and BENCH-2 → **row 9, unconstrained ADOPT, CV-C12 retires and the external `MonotonicScheduler` mandate — the single largest architectural constraint this study imposes on CandleViewer — is lifted or narrowed.** Note the asymmetry deliberately: **BENCH-6 measured and *missed* moves us not at all**, but it would re-ground CV-C12 on a fresh number instead of a five-round-old one, which is worth doing for its own sake. The last reading was **174.4 ms against a ≤100 ms bar**, so the honest prior is that it will be missed. **We should want the measurement either way, and we should not assume the outcome.**


---

## Amendment 13 — 2026-09-23: round-13 final readiness check of tag **`v0.9.0`** = `91bd979` (tree `main` @ `e3a1f22`) — **THE PIN**

**Decision: ADOPT WITH CONSTRAINTS — decision-table ROW 6**, on all four lifecycle families (B1–B20). Row 6 carries the **same decision label** as Amendment 12's row 8 ("ADOPT with constraints") but arrives by a different door and with a **materially smaller constraint set**. It is not a demotion: rows 8 and 9 both require an **empty High row**, and `R13-01` is a CONFIRMED High.

**THE PIN IS `v0.9.0`, AND IT IS FINALLY A REAL ONE.** This amendment supersedes every prior pin instruction in this ADR.

```toml
xstate-statemachine == 0.9.0
# lock file MUST carry:
#   sha256:018505a1b5e7ef1d53c6a820aa680541e87bf2b5b7ad0069e13bae12256c7c0c
# provenance anchor if source is ever needed: git tag v0.9.0 = 91bd979
```

Pinned with `==`, **never `~=` or `>=`** — #231 shows this project will tighten validation inside a minor release (inline-dict `invoke.src` now raises regardless of `strict_config`), and a floating pin would take that change unreviewed. Three things were verified in-session rather than taken on trust:

1. `git diff v0.9.0..HEAD --stat` = `.github/workflows/publish.yml` only (+14/−1). **No library source, no tests, no `pyproject.toml`** differs between the tag and the tested tree, so every finding applies to the tag as published.
2. **0.9.0 is on PyPI** — the environment briefing saying otherwise is stale. The wheel was unpacked and byte-compared against the tag source across **all 42 `.py` modules** after newline normalisation: **0 differ, 0 missing**. **The published artefact is the reviewed artefact**, which is the property a version-string check can never establish on its own.
3. Therefore **the vendoring / VCS-ref caveat carried since Amendment 1 is DROPPED**, and `CV-V08` is superseded. No vendoring. No git dependency.

### Why row 6 and not row 9

**Row 9 was genuinely in reach this round and is missed on exactly one row.** All eleven round-12 issues are fixed (#225–#235; 0 partial, 0 one-axis — the fourth consecutive round on that record and the first in thirteen with **zero** "fixed, but…" rows in the input set; #231 and #235 landed **stricter** than asked). The suite is green — **3577 passed, 13 skipped, 597 s, coverage 92.86 %** against a 90 % bar. There are **zero library regressions** across a 175-check gate and a 534-script sweep with 0 timeouts. All Medium are triaged. **Every benchmark threshold is met.** A single upstream commit draining `_priority_queue` before the inbox in `drain_pending()` would empty the High row and carry row 9 immediately.

The one row is **`R13-01`**: `Interpreter.drain_pending()` (`interpreter.py:1715`) reads only `_event_queue`, never `_priority_queue` (`:374`), while the sibling `_snapshot_pending_events()` (`:1675`) deliberately includes the lane (#107). Two documented durability views of the same interpreter return different sets, and the one whose docstring promises *"every accepted-but-unprocessed event"* is the lossy one. The "harmless, they stay queued" defence fails because `_teardown()` calls `_priority_queue.clear()` (`:1635`), so the documented `drain_pending()` → persist → `stop()` recipe **permanently destroys** fired `after` timers, invoke completions and `send_priority()` traffic. Reproduced on a **live async interpreter, no snapshot, public API only**, with the filed repro executed verbatim before filing (exit 0). It is pre-existing in the async engine — **#233 made it engine-dependent by correctly fixing the sync side.**

Per row 6, the open High and its **mechanically enforced** mitigation, stated explicitly for the decision record as row 6 requires:

| Open High | Enforcing mechanism | Test |
|---|---|---|
| `R13-01` | **`CV-C65`** — the shutdown wrapper persists via `get_persisted_snapshot()`, never `drain_pending()`; any drain result is a **lower bound**, telemetry only. Lint banning `drain_pending()` outside the telemetry module + a startup assertion on the shutdown path. | `tests/xstate_contract/test_shutdown_drain.py` — a `send_priority()` event issued immediately before shutdown must survive the wrapper's persist→restore round trip on both engines. Green on this build. |

### The timer constraint retires, and the reason is that OUR instrument was wrong

**`CV-C12` — the `after` ban standing since round 4, and the largest architectural constraint this ADR imposes — RETIRES to `CV-C12′`.** Its sole ground was BENCH-6, which **was never being measured with the right tool**: `bench_c_timers.py` does not reproduce upstream's "N busy machines" loaded-timer scenario, so five rounds of "174.4 ms, still missed" answered a question nobody asked. Re-run on **the library's own** `benchmarks/production_characteristics.py --quick` §2, ten runs on an idle host:

```
after: 10 ms deadline, 500 busy machines — median lateness beyond deadline
  min 52.1 · p50 53.4 · p99 55.8 · max 55.8 ms   (n = 10, spread 3.7 ms)   bar: 100 ms
```

Every run under the bar with ~44 ms headroom, and the tightest spread this programme has recorded. Round 12 read ~110 ms median on the same unchanged tool, and three conflicting round-13 submissions (71.0 / 87.5 / 97.9) resolved to **host load, not library variance**.

**`CV-C12′`:** `after` and `raise(delay=)` are permitted for **coarse timeouts and deadlines with ≥250 ms of tolerance**. **Hard sub-100 ms deadlines and all algo timing — TWAP intervals, chase repricing, iceberg release — remain on the external `MonotonicScheduler` with absolute `*_us` deadlines in context**, unconditionally. The relaxation is **conditional on re-measuring BENCH-6 on target hardware** (Phase-3 gate P3-G6); until then the linter narrows from "ban `after`" to "ban `after` on any state tagged `x-hard-deadline`" but the production relaxation does not take effect.

**`CV-C64` also retires to a lint (`CV-C64′`)** — #225 replaced the inheritable `ContextVar` with task identity (`_action_tasks`), so a worker outliving its action and the `ensure_future` hand-out are ordinary external traffic while the genuine in-step await is refused by the **library** with `ReentrantWaitError`. The prohibition's ground is closed; the lint stays, because the hand-out being legal again means the old ban no longer incidentally catches a hand-written reentrant await. **`CV-C25`** (no external `send()` from inside an action — gateway queue only) is untouched, and is the rule that made both #219 and #225 cost this catalogue nothing.

**Three constraints retired in one round — the most this programme has returned to the library's credit.** New in exchange: **`CV-C65`** (above), **`CV-C66`** (no per-process bring-up off `on_interpreter_start` — `R13-02`, it has **no working route** on a restored actor on either engine via either registration route, while `on_interpreter_stop` still fires, so the pair is *unbalanced*), **`CV-C67`** (register coroutine functions **directly**, never behind a sync `def` wrapper — `R13-21`, our own harness bug, which silently dropped coroutines and had been masking the #225 probes until `-W error::RuntimeWarning` surfaced it).

### The board has inverted, and the remaining risk is ours

The **library** carries **0 Blocker · 1 High · 3 Medium · 6 Low**. **We** carry **3 Blockers and 1 High**, all in our own chart definitions: `R13-13`/`R13-18` (B16 parallel-region revocation and its missing re-enter audit), `R13-14` (B18 — our opt-in root `onUnhandled:'error'` turns a guard-denied RELEASE into a permanently bricked kill switch), `R13-15`/`R13-16` (B11 — a guard ranked ahead of its own action reads pre-action context, and gap telemetry goes dark precisely while degraded), plus `R13-17` and `R13-19` at Medium. **Every one is config-only, every one has a fix proven green 11/11 in both spellings on this exact build, and in every case the engine is spec-correct per XState v5 and SCXML — the defect is our chart, not the runtime.**

Thirteen rounds in, **the remaining risk in this adoption is ours to discharge, and all of it is mechanical.** Eight Phase-3 gates are enumerated in `docs/research/xstate/74-r13-final-readiness-verdict.md` §10; **not one is blocked on upstream.** The FINAL mandatory machine configuration — which supersedes Amendment 1's — is in §7 of that document.

## Amendment 14 — 2026-09-24: round-14 final readiness check of tag **`v0.9.1`** = `45bb7f3` (tree `main` @ `801eacd`, an empty merge) — **THE PIN**

**Decision: ADOPT WITH CONSTRAINTS — decision-table ROW 8** (up from row 6), on all four lifecycle families.

- **10/10 round-13 issues closed** (#239–#248), both engines, both spellings. Suite 3601 passed, 92.93%. 0 true regressions.
- **Library board: 0 Blocker · 0 High · 1 Medium.** `R14-01` (`events.re_mint()` accepts `type`/`src` overrides and can forge a completion for another live invoke) is Medium: only in-process misuse reaches it. It is mitigated by the new **`CV-C68`** (payload-only `cv_re_mint` wrapper plus a lint).
- **Not row 9:** BENCH-2 is 380.9 against 2,000 ev/s, which is architectural and ours (lifecycle-only charts, ≥99% pre-filter). BENCH-1 was not re-measured (last 3.17×). BENCH-6 is met at p99 92.2 ms against 100 ms, with narrow headroom; P3-G6 is binding.
- **Constraints:** `CV-C65` relaxes to `CV-C65′` (drain then journal then persist), `CV-C66` relaxes to `CV-C66′` (the hook is telemetry, branching on `restored_from_snapshot`). New: `CV-C68`, `CV-C69` (`dropped_receipts`/`on_receipt_dropped`, finaliser-safe). All others stand.
- **Pin:** `xstate-statemachine==0.9.1`, `sha256:d832d4d9a17b7b8003f61fa0714a8e57eaff316bcd5dd699d81d410362687162`. The wheel equals the tag, 42/42. Verify the attestation in CI with `pypi_attestations verify pypi --repository https://github.com/basiltt/xstate-statemachine`.
- **Ours before live orders:** merge the R14-03 chart fixes (B16, B18, B11) into catalogue 28; add the B8 attempt counter (B610-OC-CD03).

Full record: `docs/research/xstate/79-r14-final-readiness-verdict.md`.
