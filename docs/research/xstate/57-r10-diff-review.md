# 57 — Round-10 diff review: `f28719c..19cb1f1` (unreleased 0.8.1)

**Scope.** 15 files, ~1.5k lines; merge `19cb1f1` (PR #211, commit `4dbf86e`,
round-9 fixes #203–#210). `__version__` still reads 0.8.0 — key on the commit.
Reviewed: all of `src/` and `tests/` changes, plus `CHANGELOG.md` `[Unreleased]`.

**Verification standard.** Every finding below is reproduced from a neutral cwd
(`C:/Users/basil`) with a STANDALONE probe (stdlib + `xstate_statemachine` only)
under `probes/main-19cb1f1/`. Each probe takes the library `src` as `argv[1]`,
so every result is a **differential** reading of `19cb1f1` against a `f28719c`
worktree — the before/after is measured, not asserted. Every service/action
question runs both `def` and `async def`.

**Headline.** The round-9 work is real: #203, #204, #207 and #209 all reproduce
as *fixed*, with engine parity and with the exact payloads the changelog claims.
Two findings need a constraint before adoption: **O-1** (a behaviour break for
self re-arming timers that the changelog does not name as a break) and **O-2**
(a silent migration cliff for pre-#195 persisted `after` records). One claim in
the changelog (**O-5**) is not supported by the code as written.

---

## Findings

### O-1 — `#206` silently converts every self re-arming timer into a chart that dies at `maxIterations` — CONFIRMED, behaviour break, async engine only

`Interpreter._schedule_send` (interpreter.py:2206–2247) now treats a delayed
send to self issued from an action as a debt of the arming step
(`_chain_owed_sends`, `_armed_this_step += 1`) and charges its firing as engine
work (`_deliver_priority(..., engine_completion=self_armed)`), which increments
`_raise_depth`. Nothing in that path is time-aware: **wall-clock time between
beats never ends the chain.** The chain is only cleared by the run loop's
"raised nothing, armed nothing, owes nothing" test — and a heartbeat re-arms in
its own entry action, so that test is false on every lap.

The consequence is not limited to the 1 ms ping-pong the changelog describes. A
`raise(delay=)` self-paced heartbeat / poller — the standard way to write a
periodic process in a chart — now stops after `maxIterations` beats and parks
with `RunawayChainError`.

`probes/main-19cb1f1/p2_delayed_selfsend_heartbeat.py`, a two-state 30 ms
heartbeat at `maxIterations: 8`, ~1.2 s of sampling:

| lane | f28719c | 19cb1f1 |
|---|---|---|
| async, `def` action | 47 beats, no drops, `last_error=None` | **9 beats, `chain_budget`, `RunawayChainError`** |
| async, `async def` action | 48 beats, no drops | **9 beats, `chain_budget`, `RunawayChainError`** |
| sync, `tick()`-driven | 30 beats, clean | 30 beats, clean (unchanged) |
| async + external traffic every 4th sample | 47 beats, clean | 45 beats, clean (**rescued**) |

`probes/main-19cb1f1/p3_delayed_selfsend_scope.py` pins the scope at
`maxIterations: 4`, 3 s budget:

| beat period | f28719c beats | 19cb1f1 beats |
|---|---|---|
| 30 ms | 114, no cut | **5, cut** |
| 100 ms | 34, no cut | **5, cut** |
| 250 ms | 15, no cut | **5, cut** |

The lap count is **identical at every period** — confirming the charge is purely
structural. A 250 ms poller and a 1 ms ping-pong are indistinguishable to the
budget; only the *number of laps* matters, never elapsed time. A stable `send`
id (supersede path) does not change it (Q2: 5 laps, cut).

Two mitigations exist and both are load-bearing rather than documented:
external traffic resets the depth (Q3 above), and a **single** delayed self-hop
that does not cycle settles cleanly and leaves later external traffic
unaffected (p3 Q3: 10/10 events processed, zero drops on both trees) — so the
debt does **not** leak.

**Engine divergence.** The `SyncInterpreter` is untouched: a timer-paced
self-send there arrives via the caller's `tick()` drain and keeps user standing.
The changelog states this ("has user standing by construction — stated in the
pin") but presents it as a *pin*, not as what it is: the two engines now give
**opposite answers** on the same chart. `tests/test_round9_findings.py::
TestDelayedSelfSendIsCharged::test_sync_engine_timer_paced_cycle_is_a_periodic_process`
asserts `>= 20` beats and `last_error is None` on sync, while
`test_delayed_selfsend_cycle_trips` asserts the async engine trips — the suite
pins the divergence rather than flagging it.

**Assessment.** The fix is correct for the reported shape (an unbounded
self-feeding cycle must be bounded). But "`maxIterations` bounds a runaway" and
"`maxIterations` caps the lifetime of every self-paced periodic process" are
different contracts, and only the first is documented. For an OMS this is the
dangerous half: a heartbeat/reconcile loop that silently stops after N beats,
leaving `status == "running"`, is exactly the failure mode that does not page
anyone.

**Constraint (proposed CV-C47).** Do not implement self-paced periodic work with
`raise(delay=)` on the async engine. Use an `after` transition (whose firing is
engine-minted and not charged this way), or drive the beat externally. Where a
`raise(delay=)` loop is unavoidable, treat `RunawayChainError` +
`last_transition_ok == False` as a liveness alarm on the heartbeat path.

**Upstream ask.** Either exempt a delayed self-send whose delay exceeds some
threshold (or whose firing lands on an *idle* loop — the same rule
`_deliver_priority` already applies to a completion: "a completion that lands on
an idle loop is free"), or document this as a breaking change with the sync/async
divergence named in the changelog, not only in a test docstring.

---

### O-2 — `#203` + `#195` together silently stop pre-0.8.1 persisted `after` records from firing — CONFIRMED, migration cliff

Selection now requires engine provenance for `after`
(base_interpreter.py:4623: `isinstance(event, AfterEvent) and
is_system_event(event)`). `restore_event` mints `_EngineAfter` only when the
record carries `"engine": true` (events.py:414, 448). That flag was introduced
by #195 (round 8). A record written by **0.8.0** has `kind: "after"` — v2 shape,
so it is *not* caught by the v1 `kind is None` name-based fallback — but no
`engine` flag, so it restores as the public `AfterEvent` and now matches
nothing.

`probes/main-19cb1f1/p1_after_provenance_migration.py`:

| case | f28719c | 19cb1f1 |
|---|---|---|
| Q1 pre-#195 v2 record (`kind:"after"`, no `engine`) | `AfterEvent` → **`t.late`** (fires) | `AfterEvent` → **`t.wait`** (silently ignored) |
| Q2 genuine round-trip (this library) | `_EngineAfter` → `t.late` | `_EngineAfter` → `t.late` ✔ |
| Q3 `SimulatedClock` + `increment()` | `t.wait` | `t.wait` (unchanged; see O-6) |

Q1 is the intended security fix — a forged record must not fire a 60-second
timer instantly — and I do not dispute the direction. The problem is the
**failure mode**: the restored deadline does not fire, does not raise, does not
warn, and is not visible in `last_error`. `has_dormant_timers` does not cover it
either, because the event was already in the persisted inbox rather than being a
timer awaiting re-arm. A machine restored from a 0.8.0 snapshot simply misses
that deadline.

The changelog's #195 entry does describe the flag's semantics, and the #203
entry describes the selection change, but neither states the **combined**
consequence for snapshots written by the *immediately preceding released
version*. There is a "0.8.1 changelog migration note" referenced in
`restore_event`'s v1 comment; it covers v1 records, not this v2-without-flag
shape.

**Constraint (proposed CV-C48).** Treat 0.8.0-era snapshots as non-restorable
for any chart whose persisted inbox can contain an `after` event. Drain
in-flight `after` events before upgrading, or re-persist under 0.8.1 before the
deadline matters. Combine with `from_snapshot(minimum_version=1)` (#205) so a
version-stripped payload cannot take the unchecked path.

---

### O-3 — `#204` changes the observable outcome of a settle-budget trip over an invoking state, and it is an improvement — CONFIRMED (no action)

This was the sharpest risk in the brief: `_arm_pending_invokes()` sits *after*
the settle loop (interpreter.py:2075, sync_interpreter.py:1065), and the loop
can `break` on `RunawayChainError`. The worry was that the trip leaves a state
active whose invoke was never armed — the #207 wedge reached by a different
road. It does not: the arming call is placed after the `break`, and the
changelog comment says so explicitly ("Also reached when the settle budget
trips").

`probes/main-19cb1f1/p4_states_to_invoke_seams.py` Q2, `always`-spin
`a ⇄ b` with an invoke on `b`, `maxIterations: 3`:

| lane | f28719c | 19cb1f1 |
|---|---|---|
| async `def` | 1 call, rests in **`spin.b`**, `has_dormant_invocations=True`, pending `[('spin.b','k')]` | 1 call, rests in **`spin.a`**, dormant **False**, pending `[]` |
| async `async def` | same as above | same as above |
| sync `def` | **2** calls, rests in `spin.a`, dormant False | **1** call, rests in `spin.a`, dormant False |

Three things improve at once. The async engine no longer parks in the invoking
state with nothing running (that was the pre-fix wedge, and `pending_invocations()`
named it correctly even then). The `def`/`async def` lanes agree. And the
sync/async **service-call counts now match** (1 and 1; they were 2 vs 1). This
is the #209 parity claim visible from a second direction.

Ordering contracts hold. **#171** is intact (Q1): `await start()` returns with
the child registered as `p:kid` and a `POKE` sent immediately after reaches it
(`['kid.hit']`) on both trees. **Initial-descent invoke** (Q3) arms exactly once
on both engines, both trees (1, 1). Note for probe authors: the actor registry
key is namespaced (`"p:kid"`), so a lookup by bare `id` returns `None` — that is
pre-existing, not a round-10 change.

---

### O-4 — `#207` `stranded` / `on_invocation_stranded` is exactly-once with correct payload on both engines — CONFIRMED (no action)

`probes/main-19cb1f1/p7_send_provenance_and_stranded.py` Q3/Q4, `rollback +
onDone` storm at `maxIterations: 3`:

| lane | f28719c | 19cb1f1 |
|---|---|---|
| async `def` | 0 hook calls, dormant True (silent wedge) | **1** call, `('spin.a','k','RunawayChainError',('k',))`, dormant True |
| async `async def` | 0 calls, dormant True | **1** call, identical payload |
| sync `def` | 0 calls, dormant True | **1** call, identical payload |
| Q4 clean completion (control) | 0 calls, `ok.b`, dormant False | 0 calls, `ok.b`, dormant False |

Exactly one hook call per cut (not per victim event), `state_id` and `invoke_id`
correct, `error.stranded == ('k',)` agreeing with the hook arguments, identical
across both engines and both service kinds, and **zero false positives** on a
chart that completes normally. `_stranded_by_cut` (base_interpreter.py:1921)
computes from the ids the cut events actually carry and intersects with the
active configuration, so it cannot over-report from the configuration alone.

The hook is additive on `PluginBase` with a `pass` body, so existing plugins are
unaffected. `RunawayChainError.__init__` gains a 4th **positional-or-keyword**
parameter with a default, so existing constructions still work — but note any
caller that subclasses it and overrides `__init__` with a 3-arg signature will
break; the library's own two call sites both pass 4 args.

---

### O-5 — the `#208` "refuses ok over an illegal configuration" path is unreachable on a live machine; the changelog overstates it — PLAUSIBLE

interpreter.py:1869–1884 adds, at receipt resolution, an
`if step_error is None and self.status == "running" and not
self._configuration_is_legal()` branch. The good news first: I could not
manufacture a **false** error receipt, which was the stated risk.
`probes/main-19cb1f1/p5_receipt_illegal_configuration.py`, identical on both
trees:

- Q1 parallel, one-region transitions ×6 → **6/6 `ok`**, no false errors.
- Q2 parallel with both regions reaching `final` → **2/2 `ok`**.
- Q3 guarded `always` + parallel, 40 events → 39 error receipts, but all
  `RunawayChainError` and **identical at f28719c** — a genuine settle trip on a
  deliberately spinning chart, not a #208 regression.
- Q4 control, real `maxIterations` cut on a `raise`-storm → receipt reports
  `error is None` i.e. **`ok`**, on *both* trees.

Q4 is the finding. The new guard only fires when `_configuration_is_legal()` is
false, and `_repair_configuration()` runs on every settle trip
(interpreter.py:2064, sync_interpreter.py:1038) precisely so the live
configuration is re-derived from its leaves — i.e. legal. Every cut path I could
reach therefore repairs before the receipt resolves, and the branch is dead on a
live machine. The changelog is honest that the reported coincidence "cannot
occur on this tree (the repro's own run shows 0 hits)" and calls the branch
"belt and braces", but `tests/test_round9_findings.py::
TestReceiptNeverOkOverEmptyConfiguration::test_receipt_reports_illegal_configuration`
still needs to force the state artificially to exercise it.

**Assessment.** Harmless, correctly conservative, but it is an *unexercised*
branch on the receipt hot path guarded by a recursive tree walk
(`_configuration_is_legal` is O(states) and runs on **every** `wait=True`
receipt where `step_error is None`). For a high-throughput OMS lane that is a
per-receipt cost paid for a branch that never fires. Worth measuring against the
existing `bench/` harness before adopting `wait=True` broadly.

---

### O-6 — `after` does not fire under `SimulatedClock.increment()` on either tree — PRE-EXISTING, not a round-10 regression

p1 Q3: a `SimulatedClock` advanced 61 000 ms past a 60 000 ms `after` leaves the
machine in `t.wait` on **both** `f28719c` and `19cb1f1` (I also awaited the
awaitable `increment()` returns). Since it is identical on both trees this is
**not** caused by #203 — provenance is not the reason; the engine's own `_fire`
mints `_EngineAfter` correctly (Q2 proves the mint path works). I am flagging it
because the brief asked specifically whether `SimulatedClock` was a legitimate
path broken by #203: **it was not broken by #203**, but the deterministic-replay
path it exists to serve does not appear to work for `after` in this harness
shape either way. Given the 20-minute bound I did not isolate whether this is a
probe-harness artefact (async settler attachment under a freshly created loop)
or a library defect — it needs its own investigation.

---

### O-7 — `#209` seed settle standing is *not* more permissive in any shape I could reach — CONFIRMED (no action)

The regression risk was real on inspection: interpreter.py:1668–1670 adds
`self._settle_iterations = 0; self._settle_tripped = False` to the seed-standing
block, which is literally "hand the settle budget a fresh start" — the #103/#151
hang class. `probes/main-19cb1f1/p6_seed_settle_standing.py` at
`maxIterations: 6`, converging to a plateau (6 consecutive stable reads) rather
than sampling at a fixed time:

| shape | f28719c | 19cb1f1 |
|---|---|---|
| `always`→invoking state, async `def` | 3 calls, `RunawayChainError`, `s.a` | 4 calls, `RunawayChainError`, `s.a` |
| `always`→invoking state, async `async def` (late completion) | 3 calls | 4 calls |
| `always`→invoking state, sync `def` | **4** calls | **4** calls |
| pure `always` spin, async | 0, trips | 0, trips |
| pure `always` spin, sync | 0, trips | 0, trips |

The async engine gains exactly **one** lap and lands on the sync engine's
pre-existing count — that is the parity the fix claims, achieved by making async
*match sync*, not by loosening both. Every case converged (`stable >= 6`), still
trips `RunawayChainError`, and still comes to rest `running` with a legal
configuration. The extra budget is consumed once, by the seed only, and the pure
spin (which has no seed completion) is byte-identical. No #103/#151 regression.

---

### O-8 — test changes weaken nothing; one test is materially stronger — no action

- `test_round6_findings.py::TestAsyncRollbackRearmCycleBounded` (#210) replaces
  two fixed sleeps (0.6 s / 0.9 s) with convergence detection (5 stable reads,
  20 s deadline) and **tightens** the assertion from `assertLessEqual(first,
  1003)` + "first == later" to an exact `assertEqual(plateau, 1003)`. Strictly
  stronger, and it removes a real flake source on a loaded host.
- `test_round8_findings.py::test_rollback_ondone_async_lanes_identical_sync_stops_early`
  is **renamed and rewritten** as `test_rollback_ondone_all_three_lanes_identical`.
  The old test asserted the sync engine stopped early with a `RuntimeError` and
  `calls <= 2`; the new one asserts all three lanes hit the *same* count at
  limits 3, 4, 19, 20 with `RunawayChainError`. This looks like a weakening
  (an assertion was deleted) but is not: the old assertion encoded the bug #204
  fixed — the sync engine failing to re-arm a rolled-back invoke. My O-3 sync
  column independently reproduces the count moving 2 → 1 and matching async, so
  the rewrite tracks a real behaviour change rather than accommodating a
  failure. It also now sweeps odd *and* even limits, which is where #209 hid.
- No `xfail`, no `skipTest`, no `@unittest.skip`, no `pytest.skip` anywhere in
  the round-6/8/9 suites (grepped).
- `tests/test_round9_findings.py`: 19 tests, **19 passed in 19.5 s** on the
  round-10 tree.
- Full suite on `19cb1f1`: **3505 passed, 13 skipped, 15 warnings in 502 s**.
  The 13 skips are pre-existing environment/CLI skips, not new xfails; the
  warnings are the pre-existing `--style` and leading-dot-target deprecations.

---

### O-9 — undocumented / under-documented behaviour worth recording

1. **`_schedule_send`'s provenance rule is positional, not intentional.**
   `self_armed = actor is self and self._processing` (interpreter.py:2238) is
   captured at **arm** time and closed over by `_fire`. It therefore classifies
   by "was a macrostep open when the action ran", which is correct for #206's
   target shape but is the same *timing*-based criterion that `_deliver_priority`'s
   own docstring warns against at length ("Chain-budget accounting is decided by
   PROVENANCE, never by timing (#180)"). The two sites now use different rules.
   I found no shape where this misclassifies — `p7` Q1 confirms 30 delayed
   self-sends issued from an **idle** loop are all processed with zero drops on
   both trees — but the asymmetry is worth naming.
2. **The `#206` debt cannot leak, verified.** `p7` Q2: arming a 5 s delayed
   self-send and then calling `stop()` returns `('stopped', 0)` within the 5 s
   `wait_for` on both trees — `_settle_debt()` on the cancel path holds.
3. **`from_snapshot(minimum_version=, expected_machine_hash=)` (#205)** is a
   genuine improvement to the trust boundary and the docstrings are unusually
   honest ("`machine_hash` is a fingerprint, not a MAC"). `check_identity`'s new
   `expected_hash` branch correctly returns **before** the payload-self-validation
   path, so the payload cannot select its own checking level. No finding.
4. **Version string.** `__version__` is still `0.8.0` on a tree whose CHANGELOG
   is `[Unreleased] — targeting 0.8.1` and whose behaviour differs from released
   0.8.0 in the ways above. Any adoption must pin the **commit**, never the
   version. (Carried forward; not new in round 10.)

---

## Adoption impact

The round-9 verdict (`54-r9-final-readiness-verdict.md`: ADOPT WITH CONSTRAINTS)
is **unchanged in direction**. #204, #207 and #209 close real defects with
measured engine parity, and the #208 risk I was asked to hunt did not
materialise. Two new constraints attach:

- **CV-C47** (from O-1): no `raise(delay=)` self-paced periodic work on the async
  engine; use `after`, or drive beats externally. Audit
  `docs/plan/28-statechart-catalogue.md` for any chart using a delayed self-send
  as a heartbeat — those charts change behaviour on upgrade.
- **CV-C48** (from O-2): 0.8.0-era snapshots with `after` events in the persisted
  inbox must be drained or re-persisted before upgrade; adopt
  `from_snapshot(minimum_version=1, expected_machine_hash=...)` at the same time.

O-5 is a performance note rather than a constraint: measure
`_configuration_is_legal()` on the `wait=True` receipt path before widening its
use. O-6 needs a follow-up investigation of `SimulatedClock` + `after`,
independent of this diff.

---

## Probes

All under `docs/research/xstate/probes/main-19cb1f1/`. Each is STANDALONE
(stdlib + `xstate_statemachine`), runs from any cwd, and takes the library
`src` directory as optional `argv[1]` for differential runs:

```
<venv>/Scripts/python <probe>.py                      # 19cb1f1
<venv>/Scripts/python <probe>.py /tmp/xsm-f28719c/src # f28719c
```

| probe | covers | finding |
|---|---|---|
| `p1_after_provenance_migration.py` | #203 provenance; legacy v2 record; round-trip; SimulatedClock | O-2, O-6 |
| `p2_delayed_selfsend_heartbeat.py` | #206 heartbeat vs `maxIterations`, both engines, both kinds | O-1 |
| `p3_delayed_selfsend_scope.py` | #206 scope: delay magnitude, send id, non-cyclic hop | O-1 |
| `p4_states_to_invoke_seams.py` | #204 start()/#171, settle-trip-before-arm, initial descent | O-3 |
| `p5_receipt_illegal_configuration.py` | #208 false-error hunt + reachability control | O-5 |
| `p6_seed_settle_standing.py` | #209 permissiveness regression hunt (#103/#151 class) | O-7 |
| `p7_send_provenance_and_stranded.py` | #206 external classification + debt leak; #207 exactly-once | O-4, O-9 |

A `f28719c` worktree was created at `/tmp/xsm-f28719c` (`git worktree add`) for
differential runs; the library tree itself was never modified.
