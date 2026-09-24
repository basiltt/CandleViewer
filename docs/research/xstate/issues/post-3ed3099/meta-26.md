# Replacement body for meta issue #26

**Action:** replace the issue body (full replacement, not a comment)

---

> ## Status on `main` @ `3ed3099` (round 5, 2026-09-19, pre-0.8.1)
>
> **Identify this build by commit, not by version string.** `__version__` still reports `0.8.0` on this commit while `CHANGELOG.md` targets 0.8.1. This is the second round running with two version stories; any pin, CI assertion or baseline keyed on the version string will silently confuse the two builds. Every finding below was reproduced in a fresh process on `3ed3099`, CPython 3.13.7, Windows 11.
>
> **The 39 issues fixed in round 4 are genuinely fixed — 34 confirm-closed, 5 reopened narrowly.** No regressions at any level: suite **3 322 passed / 13 skipped / 0 failed** (+46 over the previous commit), coverage **90 %**, every prior verification set still green, probes unchanged. Five rounds in, the fix quality has been consistently high, and we want that on the record before the rest.
>
> **The single most important thing in this issue: three of the four new Blockers are the round-4 Blockers re-emerging one layer deeper.** Each round-4 fix addressed the *reproducer* it was given rather than the *invariant* behind it. #102 taught the snapshot to refuse when **no** leaf is active — but legality is *exactly one active leaf per region*, so a parallel machine with one torn region still snapshots. #110 taught `from_snapshot()` to refuse the *fields* we happened to name — but nothing checks configuration legality on the read side at all. #103 bounded the *specific* cross-region `always` case — but a nested-invoke `onDone` cycle still livelocks `start()` with the budget self-resetting.
>
> **The fix that closes all three is one design change, not four patches: a single configuration-legality invariant — every parallel region has exactly one active leaf, and every active state's ancestors are active — enforced on *both* the snapshot write side and the restore read side.** Plus a settle budget that is genuinely bounded per macrostep. We would rather say this once and clearly than file four patches' worth of tickets and watch the shape reappear in round 6.
>
> Round 5 re-ran all eight battle tracks with new attacks aimed specifically at this round's fixes, drove twenty contract machines end-to-end on the library, and put every Blocker and High through an independent adversarial refutation pass. **21 new library defects survive: 4 Blocker · 9 High · 7 Medium · 1 Low.**

## Gate result on this commit

```
Gate run 2026-09-19 — xstate-statemachine main @ 3ed3099 (unreleased 0.8.1)
DECISION: DEFER (order path)  ·  GO for non-order paths under constraints
  39 issues      : 34 confirm-closed, 5 partial (narrow reopens)
  regressions    : none confirmed
  new defects    : 4 Blocker · 9 High · 7 Medium · 1 Low  (post-refutation)
  suite/coverage : 3322 passed / 0 failed · 90%
  benchmarks     : order-path headroom 2.65× (bar 3.0×, FAIL, unchanged class);
                   rollback policy cost now ~0 (21.7k vs 21.4k ev/s — #27 fix confirmed);
                   500-order p95 0.10 ms PASS
  operative block: UPSTREAM — configuration-legality invariant (R5-01/02),
                   bounded settle (R5-04), fail-policy semantics (R5-12)
```

Our decision table's first row matches: any open Blocker → DEFER. Four are open, and each is independently sufficient.

To be explicit about what this does *not* mean: the paths that do not touch durable order state (recording, replay, connection supervision, ingestion, auth, live-enablement, reconciliation, risk lockout) **are proceeding on this library now**, under our standing constraints. Every relevant Blocker there is either on a path those machines do not use, or is mechanically avoidable. The deferral is specific to the durable, money-adjacent order path.

## Per-issue status — every issue in this tracker

### Round-1 set (#27–#60) — carried, unchanged

| # | Status on `3ed3099` | Action |
|---|---|---|
| #27 | FIXED-OPT-IN (`actionErrorPolicy`); rollback cost now ~0. See **`<R5-12>`** — the `"fail"` arm of this same feature is a new Blocker | closed |
| #28 | FIXED-OPT-IN (`onUnhandled`) | closed |
| #29 | FIXED-DEFAULT (`strict_targets`). See **`<R5-05>`** — `strict_targets=False` reopens #108 verbatim | closed |
| #30 | FIXED-DEFAULT | closed |
| #31 | FIXED — engine parity under `strict_targets=False`. See **`<R5-05>`** | closed |
| #32 | FIXED-DEFAULT | closed |
| #33 | FIXED-DEFAULT (error-observability hooks). See **`<R5-18>`** | closed |
| #34 | FIXED-DEFAULT | closed |
| #35 | FIXED-DEFAULT (observability) / FIXED-OPT-IN (`guardErrorPolicy`). See **`<R5-10>`** | closed |
| #36 | FIXED-DEFAULT | closed |
| #37 | FIXED | closed |
| #38 | FIXED-DEFAULT (`queue_depth`) / FIXED-OPT-IN (bounding). See **`<R5-16>`** | closed |
| #39 | FIXED | closed |
| #40 | FIXED-DEFAULT — the `sendTo` residual is #133 (reopened narrowly for `forwardTo`) | closed |
| #41 | FIXED-DEFAULT | closed |
| #42 | FIXED-DEFAULT | closed |
| #43 | FIXED at `3c527b0`; still holding | closed |
| #44 | FIXED — docs residual closed by #135 | closed |
| #45 | FIXED-DEFAULT (snapshot version + machine identity) | closed |
| #46 | FIXED-DEFAULT | closed |
| #47 | FIXED-DEFAULT — priority-lane persistence closed by #107 | closed |
| #48 | FIXED-DEFAULT (14.5× better; our own latency bar is separate and still FAIL at 2.65× of a 3.0× target) | closed |
| #49 | FIXED-DEFAULT (clock injection) — see **`<R5-13>`** for a sync-restore gap | closed |
| #50 | FIXED | closed |
| #51 | FIXED for the guardrail + static-`raise` validation; `strict` remains opt-in by the issue's own plan | closed |
| #52 | FIXED | closed |
| #53 | FIXED-DEFAULT (documentation) | closed |
| #54 | FIXED-DEFAULT (perf) | closed |
| #55 | FIXED-DEFAULT | closed |
| #56 | FIXED-DEFAULT | closed |
| #57 | FIXED-DEFAULT | closed |
| #58 | FIXED-DEFAULT | closed |
| #59 | FIXED-DEFAULT | closed |
| #60 | FIXED for every criterion that describes behaviour | closed |

### Round-2/3 set (#75–#99)

| # | Status on `3ed3099` | Action |
|---|---|---|
| #75 | FIXED | closed |
| #76 | FIXED | closed |
| #77 | FIXED | closed |
| #78 | FIXED | closed |
| #79 | FIXED | closed |
| #80 | FIXED | closed |
| #84 | FIXED (`Receipt.deferred` on both engines); the arity break is now declared — see #119. Ambiguity residual: **`<R5-11>`** | closed |
| #85 | FIXED — identity-sentinel provenance. See **`<R5-21>`** for the v1-restore path | closed |
| #86 | FIXED — snapshot layout v2 round-trips provenance | closed |
| #87 | FIXED — pending `ErrorEvent`/`DoneEvent` preserved | closed |
| #88 | FIXED — `tripped` scoped per chain. See **`<R5-09>`** | closed |
| #89 | FIXED — `**kwargs` no longer counts as clock consent | closed |
| #90 | FIXED — async action-side `send()` bounded | closed |
| **#91** | **FIXED on this commit** — criterion 4 (two config names normalising to one callable now warn) met by `_warn_collapsed_config_names` in `factory.py` | **confirm closed** |
| #92 | FIXED — machine-owned registry copy | closed |
| #93 | FIXED — `logic_modules` ambiguity rule | closed |
| #94 | FIXED — completions survive a trip; engine-scope gap closed by #120 | closed |
| #95 | FIXED | closed |
| #96 | FIXED — `_resolve_event_spec` dict payload | closed |
| #97 | FIXED — `escalate` mints an `ErrorEvent`; routability closed by #130, with residual **`<R5-15>`** | closed |
| #98 | FIXED — strict rejects forged engine-shaped names | closed |
| **#99** | **FIXED on this commit** — both engines; an unhandled invoked-child failure now fails the parent | **confirm closed** |

### Round-4 set (#102–#138) — the 37 verified this round

| # | Status on `3ed3099` | Action |
|---|---|---|
| **#102** | **FIXED as filed** (`SnapshotMidStepError`, all 4 criteria) — the invariant behind it is filed separately as **`<R5-01>`** | **confirm closed** |
| **#103** | **FIXED as filed** (bounded `start()`, O(1) trip, legal configuration after trip) — the invariant behind it is filed separately as **`<R5-04>`** | **confirm closed** |
| **#104** | **FIXED** — `OverflowPolicy.BLOCK` delivers fire-and-forget `send()`; no `RuntimeWarning` | **confirm closed** |
| **#105** | **FIXED** — external sends no longer charged to the chain budget (999/1500/3000-event bursts, 0 drops). See **`<R5-08>`** for the `send_threadsafe` bypass | **confirm closed** |
| **#106** | **FIXED** — `_deferred_this_step` is per-step and by reference; 0 false positives in 3 000 cycles | **confirm closed** |
| **#107** | **FIXED** — priority lane persisted and redelivered | **confirm closed** |
| **#108** | **FIXED** — root-targeting transitions rejected at `create_machine()`. See **`<R5-05>`**: the hole reopens verbatim under `strict_targets=False` | **confirm closed** |
| **#109** | **FIXED** — `done.invoke` carries `output`, not the child's private context, on both engines | **confirm closed** |
| **#110** | **FIXED as filed** (all 10 named fields → `SnapshotCorruptError`) — the invariant behind it is filed separately as **`<R5-02>`**, and the unnamed fields as **`<R5-03>`** | **confirm closed** |
| **#111** | **FIXED** — `_detach()` preserves engine provenance under `wait=True` | **confirm closed** |
| **#112** | **FIXED** — trip is observable and the configuration is repaired; save→restore→save stable | **confirm closed** |
| **#113** | **FIXED** — `InvalidEventError(XStateMachineError, TypeError)`. See **`<R5-17>`**: not enforced on the restore path | **confirm closed** |
| **#114** | **FIXED** — run-loop death published; `send(wait=True)` no longer hangs. See **`<R5-06>`** for the pre-first-turn window | **confirm closed** |
| **#115** | **FIXED** — `SimulatedClock._detach()` on both engines' `stop()` | **confirm closed** |
| **#116** | **FIXED** — sync/async invoke timing parity. See **`<R5-07>`**: the mechanism chosen runs plain-`def` services inline on the loop | **confirm closed** |
| **#117** | **FIXED** — `from_snapshot(clock=)` on both engines. See **`<R5-13>`** for the sync restore branch | **confirm closed** |
| **#118** | **PARTIAL** — real telemetry round-trips; a missing-keys `"after"` record still restores `0.0` (an affirmative "on time"), not `None` | **REOPEN (narrow)** |
| **#119** | **FIXED** — `Receipt.deferred` arity declared breaking in CHANGELOG + both docs pages | **confirm closed** |
| **#120** | **FIXED** — the async trip spares engine completions, matching the sync partition | **confirm closed** |
| **#121** | **FIXED** — `copy.copy` is now unconditional; duck-typed logic no longer mutated | **confirm closed** |
| **#122** | **PARTIAL** — `tick()` now loops and drains zero-delay chains; the real-delay (`after: 50`×3) ladder the issue names still needs one `tick()` per deadline | **REOPEN (narrow — may close as docs)** |
| **#123** | **FIXED** — sync `send()` fires `on_event_dropped(reason='not_running')` | **confirm closed** |
| **#124** | **FIXED** — init `on_transition` parity across engines | **confirm closed** |
| **#125** | **PARTIAL** — replay is its own macrostep on the async engine only; `SyncInterpreter.send()` still folds the replay into the triggering receipt | **REOPEN (narrow)** |
| **#126** | **FIXED** — `LoggingInspector` redacts by default. See **`<R5-19>`** for the DEBUG bypass and denylist gaps | **confirm closed** |
| **#127** | **FIXED** — `async def` hook overrides surfaced; `last_plugin_error` + `on_plugin_error` | **confirm closed** |
| **#128** | **FIXED** — `restart_timers=` and `has_dormant_timers` | **confirm closed** |
| **#129** | **FIXED** — `stop()` and `_enqueue_blocking` both fire `on_event_dropped` | **confirm closed** |
| **#130** | **FIXED** — `escalate()` reaches the parent's `onError`. See **`<R5-15>`**: only when the invoke declares an explicit `id` | **confirm closed** |
| **#131** | **FIXED** — `SnapshotSerializationError` naming the offending event, rather than silent stringification | **confirm closed** |
| **#132** | **FIXED** — ambiguous bare `stateIn` raises `InvalidConfigError` naming all candidates | **confirm closed** |
| **#133** | **PARTIAL** — `sendTo` fires `on_event_dropped(reason="unresolved_target")`; the `forwardTo` sibling branch still only logs | **REOPEN (narrow)** |
| **#134** | **PARTIAL** — `on_resolve_error` exists and fires on the async engine; `sync_interpreter.py` never calls it | **REOPEN (narrow)** |
| **#135** | **FIXED** — the `status`-is-not-liveness caveat documented in the docstring, the guide and a test | **confirm closed** |
| **#136** | **FIXED** — cyclic config raises `InvalidConfigError` naming the state path | **confirm closed** |
| **#137** | **FIXED** — `is_system_event`/`system_event` exported and documented | **confirm closed** |
| **#138** | **FIXED** — provenance survives `deepcopy`/`pickle`, and a user event still cannot be laundered into a system event | **confirm closed** |

**34 confirm closed · 5 reopen (narrow) · 1 meta update (this issue).** As in every prior round, we reopen only where an acceptance criterion is unmet **by code** — never for wording, naming, test-file paths or architectural framing. Where a criterion is unmet only because a design decision was made differently (#122), we say so and ask for the docs rather than asserting a defect.

## Round 5 — new findings

Filed against this commit, each with a standalone runnable repro. Issue numbers are filled in as the issues are created.

**Blockers (4)** — each independently sufficient to hold our order path.

- [ ] `<R5-01>` — `SnapshotMidStepError` is gated on an *any-leaf* test (`base_interpreter.py:1112`), not per-region legality: a parallel machine mid-transition in one region snapshots with that whole region absent and restores half-dead, and the same conjunct leaves the window open while entry actions run. Two tracks found this independently. **Deeper layer of #102.**
- [ ] `<R5-02>` — `from_snapshot()` performs no configuration-legality check: a truncated `configuration` (`['fz']` — ancestor kept, leaf deleted) passes the emptiness guard at `persistence.py:186`, is preferred over the still-correct `state_ids` at `base_interpreter.py:1442`, and restores a `running` machine with zero active leaves that is permanently inert. **Deeper layer of #110.**
- [ ] `<R5-04>` — Nested invokes whose `onDone` targets their common compound ancestor livelock `SyncInterpreter.start()`; `sync_interpreter.py:802-807` resets the chain counters, so `maxIterations` of `None`, `10` and `1000` all fail to bound it (RSS flat at 43 MB — a livelock, not a leak). The async engine returns but burns ~100 % CPU with `status=running` and no error. **Deeper layer of #103.**
- [ ] `<R5-12>` — `actionErrorPolicy: "fail"` reverts the configuration to the **source** state, bricks the interpreter, and `get_persisted_snapshot()` persists the bricked result without complaint. This policy is in our mandatory configuration block for invariant-bearing machines.

**High (9)**

- [ ] `<R5-03>` — `from_snapshot()` leaks raw `TypeError`/`AttributeError`/`ValueError` for `version`, `status`, `history`, `actors`, `system` and `deferred`, and for pre-parse payloads — escaping the documented `except XStateMachineError`. 10 of 11 single-field mutations were untyped; four independent fuzz runs agree.
- [ ] `<R5-05>` — `strict_targets=False` reopens the #108 root-target hole verbatim: the configuration empties while `last_transition_ok=True`, with no error on either engine.
- [ ] `<R5-06>` — An external cancel landing before the run loop's first scheduling turn is never published: `status` stays `"running"` while `is_running` is `False`, and `send(wait=True)` hangs forever.
- [ ] `<R5-07>` — *Regression of intent from #116*: a plain-`def` invoked service now runs **inline on the async run loop**, stalling every timer, actor and inbound send for its full duration.
- [ ] `<R5-08>` — The #105 self-send gate is a `contextvars` read, so `send_threadsafe` from an action-spawned thread is classified external and `maxIterations` becomes unenforceable.
- [ ] `<R5-09>` — The transient settle budget is reset per **drain**, not per macrostep, so one event's legitimate settle starves the next event in the same `send_events()` batch.
- [ ] `<R5-10>` — A guard raising under `guardErrorPolicy: "raise"` cancels the remaining candidates in a transition array, so an unguarded fallback on an `invoke.onDone` is never taken; on an engine-driven transition there is no receipt and no error surface, and the region strands while reporting healthy.
- [ ] `<R5-13>` — `SyncInterpreter.start()`'s restore branch returns before `clock._attach(self.tick)`, so `restart_timers=True` / `from_snapshot(clock=)` re-arm a deadline nothing will ever drain.
- [ ] `<R5-11>` — `Receipt(changed=False, error=None)` cannot distinguish a no-op, a guard-denied event and an unhandled-and-errored event; `onUnhandled: "error"` is terminal and silent at the call site.

**Medium (7)**

- [ ] `<R5-14>` — Any action named `spawn_*` is hijacked by the built-in spawn resolver before user logic is consulted — the one prefix that violates the library's own user-wins rule.
- [ ] `<R5-15>` — `escalate()` reaches the parent's `onError` only when the `invoke` declares an explicit `id` (residual on #130).
- [ ] `<R5-16>` — `send_threadsafe` has no usable backpressure signal on the calling thread; overflow is evaluated after the call returns.
- [ ] `<R5-17>` — #113's non-`str` event-type guard is enforced on `send()` but not on the restore path — the path facing untrusted storage.
- [ ] `<R5-18>` — `SnapshotMidStepError` / `InvalidEventError` / `SnapshotSerializationError` raise correctly but emit to no plugin hook, so they are invisible to an audit log.
- [ ] `<R5-19>` — `get_snapshot()` logs the full unredacted snapshot at DEBUG, bypassing #126; and `DEFAULT_REDACT_KEYS` misses most financial/session PII.
- [ ] `<R5-20>` — `send()` accepts a mapping like `{"type": "GO"}` without routing it through `InvalidEventError` validation.

**Low (1)**

- [ ] `<R5-21>` — A v1 snapshot re-derives provenance from the event **name**, laundering an engine-shaped user event into a system event.

Twenty-two further submissions from the eight tracks collapsed into the canonical findings above as duplicates, and five more were classified as design constraints rather than defects (notably: there is **no public quiescence API** — `SnapshotMidStepError`'s own message advises snapshotting "once the step settles … or from `on_transition`", but nothing public answers "is a macrostep in flight?", and the `on_transition` advice is unsound for any machine with transient states. That is why `<R5-01>` has no caller-side workaround).

## Battle-test scorecard (`3ed3099`)

| Track | Round-4 defects | Now | New defects (post-refutation) | Verdict |
|---|---|---|---|---|
| **Persistence / crash consistency** | 1 B, 3 H, 7 M | all as-filed fixed | **`<R5-01>` (B)**, `<R5-03>` (H), `<R5-17>`, `<R5-21>` | **FAIL** — the legality invariant is still absent |
| **Concurrency & limits** | 1 H, 2 M | fixed | **`<R5-02>` (B)**, `<R5-06>` (H), `<R5-15>`, `<R5-16>` | **FAIL** on the restore path; **PASS** on leaks and loop blocking |
| **Fuzz / property** | 3 M | fixed | **`<R5-04>` (B)**, `<R5-05>` (H) | **FAIL** — livelock reachable from generated configurations |
| **Determinism / replay** | 3 M | fixed | `<R5-13>` (H), `<R5-18>` | **PASS with constraints** — the async engine is deterministic run-to-run |
| **Semantics conformance** | 2 H, 1 M | fixed | `<R5-10>` (H), `<R5-14>` | **PARTIAL** |
| **Observability** | 1 H, 3 M | fixed | `<R5-11>` | **PARTIAL** — `Receipt(changed=False, error=None)` is still ambiguous across three causes |
| **Security / supply chain** | 2 M | fixed (redaction shipped) | `<R5-19>`, `<R5-20>` | **PASS** — no injection surface; redaction has a DEBUG bypass |
| **Soak (12 min, reduced)** | 1 L | — | none | **PASS** — flat memory, 0 leaked tasks, 0 lost events |

Diff review of `5e07ba8..3ed3099` contributed three more: `<R5-07>`, `<R5-08>` and `<R5-09>`.

Twenty contract statecharts were also driven end-to-end on the library. They load and run; the defects that surfaced there were overwhelmingly **ours**, not yours (ten of them), and we have fixed them on our side. One is worth mentioning because it changes how you should read any receipt-based evidence we have given you in earlier rounds: an inline `"*"` handler we had left in our own JSON pre-empts `onUnhandled: "defer"` **and** silently disables `strict: true` machine-wide, because one bare `"*"` puts `"*"` into `known_events` and short-circuits `is_known_event()`. That is coherent behaviour on your side, and our documentation of it was simply backwards — but **a bare `"*"` neutralising `strict` for an entire machine is a sharp edge worth one explicit sentence in the `strict`/`onUnhandled` guide**, because the symptom is a swallowed event with no exception, no `on_event_dropped`, no `on_unhandled_event`, and a receipt indistinguishable from a correct no-op.

## Harness errors on our side

Listed explicitly so you are not asked to account for our mistakes. **None of these is a defect in the library.**

- **`t3_receipts.py::J5`** — our own re-implementation of the settle-budget batch case settled both batched events correctly. The finding `<R5-09>` is counted on the **original** probe chain shape, which does reproduce; our re-implementation was wrong.
- **`t2_engine.py` first pass, receipt fields all `None`** — `SyncInterpreter.send()` returns `None`; only the async `send(..., wait=True)` returns a `Receipt`. Every receipt-shaped claim (`<R5-11>`, `<R5-12>`) was re-run on the async engine before being counted.
- **`t2_engine.py` first pass, guard arity** — guards take `(context, event)` and actions take `(interpreter, context, event, action_def)`. Reusing one callable for both raised a spurious `TypeError` at our call site. Affects no finding.
- **LC-12 (`spawn_blocking`, async engine)** — our gate flagged a PASS→FAIL flip, but the observed values cluster at a ~250 ms threshold (254/252, 256/251, 258/254 ms). That is a race in *our check*, not a demonstrated regression. **Not counted, and we are not asking you to look at it** until we have run it ≥10×.
- **LC-48 (`on_transition_failed` ordering)** — plausible and deterministic-looking, but run once. Our standard is reproduce-before-you-count, so it is **not counted** this round. It is adjacent to `<R5-18>`.
- **`LC-07`, `N-3`, `N-8`** — already failing at the `3c527b0` baseline and annotated "keep open"; carried over unchanged, not new.
- Two runs in the final pass were reduced in scale to fit a time bound (a persistence property run at 500 cases; a soak at 12 minutes rather than 25). Both still reproduce, and no conclusion rests on a number we did not re-measure.

## Release-readiness — what we would fix before tagging 0.8.1

1. **`__version__` still reports `0.8.0` — bump it.** Third review running with two version stories; consider a test tying it to the newest released CHANGELOG heading.
2. **Implement one configuration-legality invariant** — every parallel region has exactly one active leaf, and the ancestors of every active state are active — and enforce it in `get_persisted_snapshot()` **and** `from_snapshot()`. This closes `<R5-01>`, `<R5-02>` and the whole class behind #102/#110 for good. Add a property test that snapshots at every quiescent point of a randomly generated parallel machine. **This is the single most important item in this issue.**
3. **Bound the settle budget per macrostep for real** (`<R5-04>`, `<R5-09>`), and pin the nested-invoke `onDone`-to-ancestor case as a test.
4. **Fix `"fail"` to halt in the target-or-halted state, never revert to source**, and refuse to snapshot a halted interpreter (`<R5-12>`).
5. **#116 follow-up:** run plain-`def` services via `run_in_executor`, or document that they must be trivial (`<R5-07>`).
6. **Route `send_threadsafe` through the same self-send classification as `send`** (`<R5-08>`).
7. **Wrap every `from_snapshot` field access** so that only `SnapshotCorruptError` escapes (`<R5-03>`).
8. Re-run our LC-12 check ≥10× (ours to do, listed so it is not lost).
9. Pin a `--cov-fail-under=88` floor now, while coverage is at its 90 % high-water mark.

A note on the shape of items 2–4 rather than their content: what these three have in common is that each round-4 fix was written against the failing script we supplied. That is a completely reasonable way to work, and it produced 34 clean closes this round. It stops working for invariants, because an invariant has more reproducers than anyone will think to write. For these four, a property test over generated machines will buy more than any number of pinned cases.

## What would change the verdict

- **Close `<R5-01>`, `<R5-02>`, `<R5-04>` and `<R5-12>` with a pinned test each → the Blocker row clears.**
- With `<R5-07>` and `<R5-08>` also closed, the open High count falls to 7 — still over our bar of 5, so **two more** of `<R5-03>`/`<R5-05>`/`<R5-06>`/`<R5-09>`/`<R5-10>`/`<R5-11>`/`<R5-13>` must close for **ADOPT WITH CONSTRAINTS** on the order path.
- Re-verification is cheap: the gate script, the persistence property run (500 cases), the fuzz livelock repro, and three contract machines. **About 40 minutes.**

Every item above is reproduced by a script we can share; nothing in this list is a hunch. Five rounds in, we remain committed to adopting this library — and we want to be clear that the reason this round reads harder than the last is not that the work got worse. It is that the remaining defects are invariants rather than cases, and invariants are the last thing a young engine gets right.

*(Issues #61–#74 and #100–#101 are not part of this tracker's verified set and carry no status change from us.)*
