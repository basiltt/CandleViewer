# FUZZ — fuzzing & property-based battle test of `xstate-statemachine` @ `19cb1f1`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`19cb1f1`** ("Merge pull request #211 from basiltt/fix/0.8.1-round9").
`CHANGELOG.md` `[Unreleased] — targeting 0.8.1`. **`__version__` still reports
`0.8.0`; this build is identified by commit.**

**Date:** 2026-09-22. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200. **Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python`
with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Track:** FUZZ, re-run of `battle-f28719c/fuzz.md` plus a new attack set aimed
at round 9's fixes (#203–#210). New scripts live under
`docs/research/xstate/battle-19cb1f1/fuzz/`; raw output under `fuzz/out/`.
No library source was modified. No `git` command was run in the adopting
project's repository. GitHub was read-only throughout.

**Standard applied.** This library is being evaluated to run an
order-management system handling real money. Every silent failure,
nondeterminism and ordering ambiguity is treated as a defect and reproduced
before it is counted. **Every service/action check was run with both `def`
and `async def` implementations.**

---

## 0. Bottom line

**Round 9's behavioural work is the strongest single round measured on this
track: #204, #206, #207 and #208 all verify clean under adversarial load, and
two long-standing defects (R9-03 starvation, R9-08 empty-configuration
receipt) are gone. But round 9 shipped its `after` fix (#203) on top of the
same type-identity gate that this track reported as a Blocker at `f28719c` —
so #203 inherits the forgery, and the Blocker is now strictly worse than
before, not merely unfixed.**

- **NEW D10-fuzz-1 (Blocker) — #203's `after` provenance boundary is
  forgeable four ways, and a 60-second timer fires instantly.** #203 stopped
  `after` selection matching the public `AfterEvent` class and made it
  require an engine mint. The mint check is `isinstance(ev, _EngineAfter)` —
  the same `is_system_event` gate #195 used, which round 9 did not change.
  `n1_after_forgery.py`: the one vector the changelog names (a hand-built
  public `AfterEvent`) is correctly refused, and **four others succeed**:
  the public import path `events.engine_after(...)`, `type(held_event)(...)`
  from a class object any plugin/action can reach off a legitimately-received
  event, a `pickle` round-trip, and a hand-written snapshot record with
  `"engine": true`. Each drives the real `after` transition: a **60 000 ms
  timer fires immediately**, `['n1.armed'] -> ['n1.expired']`, under
  `strict: True`. For an OMS this is an order that cancels or expires itself
  on a forged tick.

- **R9-01 (D9-fuzz-1, Blocker) is STILL PRESENT, unchanged.**
  `g7_forgery_repro.py` verbatim: still **3 of 4 completion vectors succeed**
  (`_replace`, `pickle`, `engine:true` record), each landing
  `{'filled': 999999}` via a real `onDone` with the genuine service still
  running. Round 9 did not address it, and #203 extended the same mechanism
  to a second event class. Combined vectors across both event kinds: **7**.

- **NEW D10-fuzz-2 (Medium) — #209's lap-parity claim is false again, in a
  new shape and a worse direction.** #209 pins "all three lanes agree at
  limits 1–25" after fixing the `rollback + onDone` shape. That shape is
  genuinely fixed (`g2_lap_parity.py`: 26 mismatches, **all 26 are the
  documented `SyncInterpreter` + `async def` = `NotSupportedError` cells**;
  `def`-lane mismatches are now **0**, down from 13). But on an
  `always` + zero-delay `raise` cycle — pure engine work, no timers, no
  delayed sends, exactly what the budget is supposed to charge —
  `n6_shrunk_repros.py` finds **24 of 25 limits disagree**, and unlike round
  8 the gap **grows with the limit**: mi=1 sync 4 / async 6; mi=10 sync 23 /
  async 33; mi=25 sync **53** / async **78**. The claim was again
  generalised from the shapes that were fixed.

- **#204 (`statesToInvoke`) verifies clean — the headline fix is real.**
  `n2_states_to_invoke.py`, a 5-case × 2-kind × 2-engine matrix with the
  oracle counting submissions **inside the service body**: roll-forward by
  `always`, `rollback` of the entry action, a parallel sibling reaching
  `final`, and a two-hop `always` chain **all submit 0**, on both engines and
  both kinds; the control case that stays resident submits exactly **1**.
  **0 failing cells / 10.**

- **#206 and #207 verify clean under concurrency.**
  `n4_concurrency_stranded.py`: 100 concurrent `raise(delay=1ms)`
  self-ping-pongs trip **100/100, all at the identical lap (12)** against a
  zero-delay reference of 13 — inside the changelog's own ±1 — on both action
  kinds. 200 concurrent `rollback + onDone` storms fire
  `on_invocation_stranded` **exactly once each (200/200, hist `{1: 200}`)**
  with the correct `('st.starting', 'fill')` ids, `RunawayChainError.stranded`
  agreeing **200/200**, `has_dormant_invocations` / `pending_invocations()`
  both truthful, and a stable hook order (`dropped` → `stranded`) on every
  run and both kinds.

- **R9-03 (D9-fuzz-3, High) is FIXED.** The `always`→`invoke`→`onDone`
  starvation of the `async def` lane is gone. `r18_ext_starvation_repro.py`
  verbatim: **500/500 applied (100 %)** on both kinds and the sync engine;
  was 72/500 (14.4 %). `r19_starvation_drain.py`: both lanes **DRAINED**
  within 1 s at ~8–9 % of one core; was permanently stuck at 66 %.

- **R9-08 (D9-fuzz-4, Medium) is FIXED.** `r3_empty_repro.py` verbatim:
  **0/15** laps resolve over an empty configuration on both kinds; was 11/15.
  Independently confirmed by the 352-config receipt fuzz: **0 success-shaped
  receipts over an illegal configuration, and 0 error receipts over a legal
  settled one** (`n5`, B1/B2 both zero).

- **R9-15 (D9-fuzz-5, Low) is STILL PRESENT.** `r14_observability.py` §C:
  a `SnapshotMidStepError` from an invoked child's entry action still reports
  `child=False`, both kinds. Diagnostic quality only.

- **Everything else verifies clean.** #186/#198's snapshot asymmetry is still
  closed (8/8 `SnapshotCorruptError`, 0 accepted). Determinism is total: 50
  identical runs of the stranded shape yield **1 distinct trace** per
  engine/kind cell — including the stranded ids and hook count — and the
  `PYTHONHASHSEED` sweep is 1 distinct result. The livelock fuzzer's
  termination and observability properties are unanimous over 352 configs
  (**0 non-settling on engine-work-only charts, 0 trips unobservable**). A
  45 s / 60-machine soak applied **915 600 of 915 600** external priority
  sends with **0 lost**, took 76 212 clean chaos snapshots (88 correctly
  refused mid-step), stayed at **99.6 % of one core** (12 % of 8), and left
  **0 machines dormant without a hook**.

- **The pattern, unchanged across three rounds.** The behavioural fixes are
  excellent and they stay fixed. The *claims* are the liability: #203 was
  built on a boundary this track had already reported as broken, and #209's
  parity sentence was again generalised past the shape that was measured.

---

## 1. Method, and the reductions made

Hard bounds: ≤ 120 s per script, ≤ 20 min total wall clock. **Reductions,
stated explicitly:**

| Script | Brief asked | This run | Why |
|---|---|---|---|
| `n5_livelock_receipt_fuzz.py` | ≥ 500 configs × 2 kinds × 2 engines | **352 configs** (1 408 cells) | The script generates 500 and self-truncates at 95 s to stay inside the 120 s bound, printing where it stopped. Every property was decided unanimously well before the cut (P1 and P2 at 0; the P3 and receipt populations both stable by ~config 150). |
| `n7` soak | 12 min, 200 machines | **45 s, 60 machines** | 12 min alone exceeds the whole-task bound. Load shape preserved exactly: `always`→`invoke`, `rollback`+`onDone`, `raise(delay=)` self-sends, an external priority producer and chaos snapshots, all concurrent. 915 600 external sends and 76 300 snapshots in the window. |
| `n4` ping-pong / storm | 100 / 200 concurrent | **100 / 200** (full) | Ran in 0.1 s and 0.5 s respectively. |
| Determinism | 50× both engines both kinds | **50×** (full) | Async engine only for the stranded shape — the sync engine's `NotSupportedError` on coroutine services is documented, and `r12_determinism.py` covers the sync lane separately (also 1 distinct trace). |
| External sends at 5 k/s | 5 000/s | **~20 350/s** achieved in the soak | Exceeded the target; no reduction. |

**Every new script is standalone** — stdlib plus `xstate_statemachine` only,
every helper inlined, and each was proved from the neutral cwd
`C:/Users/basil`.

### 1.1 Adaptation for documented-superseded behaviour

Three adaptations were needed and are recorded rather than silently applied:

1. **`g2_lap_parity.py` / `n5` P3: `SyncInterpreter` + `async def` service**
   raises `NotSupportedError` by documented design. Those cells are
   **excluded**, not scored. At `f28719c` this track excluded 13+13 such
   cells and still counted 13 real `def`-lane mismatches; at `19cb1f1` **all
   26 mismatches are the excluded kind** and the real count is 0 — which is
   how R9-09's `rollback + onDone` half is scored FIXED.

2. **`n5` P1/P3 attribution.** Charts containing `after` or `raise(delay=)`
   are timer-paced. The `SyncInterpreter` does not fire timers without a
   caller `tick()` — which the #206 pin states explicitly — so their lap
   counts are not comparable and their non-settling is a property of the test
   harness's watchdog, not of the engine. They are reported separately
   (97 P1 and 130 P3 cells) and **excluded from the defect count**; only the
   12 engine-work-only P3 cells are counted, and those are what `n6` shrinks.

3. **`n4` convergence sampling.** An early draft broke its wait loop on
   `last_error is not None`, which the rollback's own `RuntimeError` sets long
   before the cut — the exact mistake #210 fixed in the library's own test.
   Corrected to wait for `RunawayChainError` specifically. Both the wrong and
   right samplings are in the session record; only the corrected run is
   reported.

### 1.2 One oracle error, corrected and disclosed

A first draft of `n5`/`n6` scored the receipt legality property with
`getattr(r, "ok", getattr(r, "transitioned", True))`. **`Receipt` has neither
field** — it exposes `state_ids / changed / error / deferred / denied` — so
the fallback returned `True` for every receipt and the fuzzer reported 42
"success-shaped receipts over an illegal configuration". Re-scored against
the real field (`r.error is None`): **0**. The library is correct; the first
number was the harness's. `n6`'s D1 section is retained as the positive
control with the correction documented in its docstring.

---

## 2. Prior-defect table

Each prior-round defect re-run at `19cb1f1`, with the script and verdict.

| Prior ID | Register | Severity | Re-run | Verdict @ `19cb1f1` |
|---|---|---|---|---|
| D9-fuzz-1 | R9-01 | Blocker | `battle-f28719c/fuzz/g7_forgery_repro.py` verbatim | **STILL PRESENT**, unchanged — 3/4 completion vectors forge (`_replace`, `pickle`, `engine:true` record); each lands `{'filled': 999999}` with the genuine service live. **Now CHANGED for the worse**: #203 extends the same gate to `AfterEvent`, adding 4 more vectors (D10-fuzz-1). |
| D9-fuzz-2 | R9-09 | Medium | `battle-f28719c/fuzz/g2_lap_parity.py` verbatim | **FIXED on the shape it named.** 26 mismatches remain, **all 26** the documented `sync + async def` = `NotSupportedError` exclusion; `def`-lane mismatches **13 → 0** on both `nested_invoke` and `rollback_ondone`, odd and even limits 1–25. **CHANGED**: the underlying claim is still false on a different shape — D10-fuzz-2. |
| D9-fuzz-3 | R9-03 | High | `battle-6db65d8/fuzz/r18_ext_starvation_repro.py`, `r19_starvation_drain.py` verbatim | **FIXED.** 500/500 (100 %) applied on `def`, `async def` and the sync engine, plus both ablations; was 72/500 on the `async def` lane. Drain: both lanes empty within 1 s at 8–9 % of one core; was permanently stuck at 66 %. |
| D9-fuzz-4 | R9-08 | Medium | `battle-6db65d8/fuzz/r3_empty_repro.py` verbatim | **FIXED.** `EMPTY config 0/15` on both `async def` and `plain def`, async engine; sync engine clean. Was 11/15. Corroborated by `n5` B1 = 0 over 1 408 fuzzed cells. |
| D9-fuzz-5 | R9-15 | Low | `battle-6db65d8/fuzz/r14_observability.py` §C | **STILL PRESENT.** `REFUSED child=False` from an invoked child's entry action, both kinds. Sections A/B/D of the same script still PASS. |
| D8-fuzz-4 / R8-08 | — | (fixed r8) | `battle-6db65d8/fuzz/r10_186_asymmetry.py` verbatim | **STAYS FIXED.** All 8 mutations `SnapshotCorruptError`; 0 accepted-despite-disagreement. |
| D8-fuzz-2 / R8-01 | — | (fixed r8) | `battle-6db65d8/fuzz/r8_ext_shed_loss.py` verbatim | **STAYS FIXED.** 600 sent / 600 applied / 0 lost on all 4 cells. |
| — | determinism | — | `battle-6db65d8/fuzz/r12_determinism.py` verbatim | **PASS.** 1 distinct trace per cell; `PYTHONHASHSEED` sweep 1 distinct result. |
| — | persistence/provenance | — | `battle-f28719c/fuzz/g1_persist_provenance.py` verbatim | **§A/§C/§D PASS; §B still FAIL** — the `engine:true` record is trusted, which is the record-door half of D9-fuzz-1/D10-fuzz-1. |

**Net:** 2 of 5 prior fuzz defects fixed (1 High, 1 Medium), 2 still present
(1 Blocker, 1 Low), 1 fixed-on-its-shape-but-refiled (Medium). Zero
regressions among the round-7/8 fixes re-run.

---

## 3. New attacks on round 9's machinery

| # | Attack | Script | Result |
|---|---|---|---|
| 1 | SCXML §6.1 `statesToInvoke` matrix: enter+exit in one macrostep via `always`, `rollback`, parallel sibling `final`, 2-hop `always` chain; + resident control | `n2_states_to_invoke.py` | **PASS 10/10 cells.** 0 submissions in all four cut cases, exactly 1 in the control, both engines both kinds. |
| 2 | `after`-provenance matrix: 5 forgery vectors against a 60 s timer under `strict` | `n1_after_forgery.py` | **FAIL — 4/5 forge. D10-fuzz-1 (Blocker).** |
| 3 | Snapshot taken from inside the arming window (plugin hooks during the macrostep that enters the invoking state) | `n3_persist_arming.py` §A | **PASS.** `on_transition` into the invoking state → `SnapshotMidStepError`, both kinds. The one hook that accepts (`on_event_received`) fires *before* the transition and correctly persists the pre-transition configuration `['p.s']` — verified by comparing the snapshot's `state_ids` against live ids, not just by acceptance. |
| 4 | Snapshot at quiescence with the service in flight → static restore → `restart_services=True`: arm exactly once, dormancy reported | `n3_persist_arming.py` §B | **PASS.** Static restore submits 0 and reports `dormant=True` with `pending=[('p.t','job')]`; `restart_services=True` + `start()` submits exactly **1** and clears dormancy. (The `def` lane's service completes before the snapshot by the documented awaited-`def` contract, so it restores at `p.u` with nothing pending — correct, not a miss.) |
| 5 | 100 concurrent `raise(delay=1ms)` self-ping-pongs vs the zero-delay reference | `n4` §A/B | **PASS.** 100/100 trip, all at lap 12 (single-valued histogram), reference 13 — within the ±1 the changelog claims. Both action kinds. |
| 6 | 200 concurrent `rollback`+`onDone` storms: stranded hook exactly-once, ids, payload agreement, ordering vs `on_event_dropped` | `n4` §C/D | **PASS.** `{1: 200}` hook count, correct ids 200/200, `RunawayChainError.stranded` agrees 200/200, order `dropped`→`stranded` on every run, both kinds. |
| 7 | External priority sends at high rate during self-generated chains | `n7` §B | **PASS. 915 600 sent / 915 600 applied / 0 lost** at ~20 350/s (target was 5 000/s). |
| 8 | Livelock fuzzer, 352 random charts × 2 kinds × 2 engines (always + invoke + after + raise0 + raise(delay=) + rollback) | `n5` §A | **P1 PASS** (0 non-settling on engine-work-only charts), **P2 PASS** (0 trips unobservable; 0 dormant-invoke trips without a stranded hook), **P3 FAIL** on 12 engine-work-only cells → D10-fuzz-2. |
| 9 | Illegal-configuration receipt fuzz, both directions | `n5` §B | **PASS both ways.** 0 success-shaped receipts over an illegal configuration; 0 error receipts over a legal settled one. |
| 10 | Determinism ×50 incl. stranded events, both kinds | `n7` §A | **PASS.** 1 distinct trace per cell, stranded ids and hook count included. |
| 11 | Soak: CPU bound, 0 dropped external, no livelock, no stranded without hook | `n7` §B | **PASS.** 99.6 % of one core (12 % of 8), 0 lost, 0 dormant-without-hook, 76 212 clean snapshots / 88 correctly refused. |

---

## 4. Defects

### D10-fuzz-1 — Blocker — #203's `after` provenance is forgeable four ways; a 60-second timer fires instantly

**Repro:** `battle-19cb1f1/fuzz/n1_after_forgery.py` (exit 1).
**Source:** `src/xstate_statemachine/events.py:283` (`is_system_event`),
`events.py:579` (`_EngineAfter`), `events.py:604` (`engine_after`),
`base_interpreter.py:4624` (the `after` selection gate).

#203's fix changed `base_interpreter.py:4624` from matching the public
`AfterEvent` class to `isinstance(event, AfterEvent) and
is_system_event(event)`. That closes exactly one vector — a hand-built
`AfterEvent` — and this repro confirms it: `UnknownEventError` under
`strict`, `fired=0`. The other four all yield `is_system_event=True` and
drive the real transition:

```
  V1 hand-built public AfterEvent
     is_system_event=False  send->REFUSED:UnknownEventError  fired=0  => refused (ok)
  V2 import path engine_after()
     is_system_event=True   send->ACCEPTED  fired=1  ['n1.armed'] -> ['n1.expired']
  V3 type(held_engine_event)(...)
     is_system_event=True   send->ACCEPTED  fired=1  ['n1.armed'] -> ['n1.expired']
  V4 pickle round-trip
     is_system_event=True   send->ACCEPTED  fired=1  ['n1.armed'] -> ['n1.expired']
  V5 hand-written snapshot record engine:true
     is_system_event=True   send->ACCEPTED  fired=1  ['n1.armed'] -> ['n1.expired']
```

The state declares `after: {60000: ...}`. Every forged event fires it
**immediately**, under `strict: True`.

Why each works, and why none needs a private name:

- **V2** — `engine_after` is defined at module scope in `events.py` with no
  underscore and is reachable as `xstate_statemachine.events.engine_after`.
  The docstring calls it "the ONLY sanctioned way" to mint; nothing enforces
  who may call it. This is the cheapest vector and it did not exist as a
  distinct finding at `f28719c`.
- **V3** — any plugin hook or action that receives a genuine engine event can
  read `type(ev)` and call it. The class object is the capability; the name
  being private is irrelevant.
- **V4** — `_EngineAfter` is importable from `xstate_statemachine.events`, so
  `pickle` round-trips it as itself. Same mechanism as the completion case.
- **V5** — `restore_event` (`events.py:367`) honours `"engine": true` in a
  hand-written record by explicit design.

This is the same defect class as D9-fuzz-1/R9-01 and the same root cause.
Round 9's response to that Blocker was to build a second guarantee on the
broken primitive. The blast radius for an OMS is now wider than a forged
fill: any `after`-driven timeout — order expiry, cancel-on-timeout, retry
back-off, circuit-breaker reset — can be triggered at an attacker-chosen
instant.

**Fix direction** (unchanged from round 8's report): provenance must be
carried by something the engine mints *and holds* — a per-interpreter
nonce compared by identity against the timer registration that is actually
outstanding — not by a type that Python reconstructs and that a public
factory function will mint on request.

### D10-fuzz-2 — Medium — #209's lap-parity claim is false on engine-work-only charts, and the gap grows with the limit

**Repro:** `battle-19cb1f1/fuzz/n6_shrunk_repros.py` §D2 (exit 1); found by
`n5_livelock_receipt_fuzz.py` P3 (12 engine-work-only cells / 352 configs).

#209 states: "all three lanes agree at limits 1–25, odd and even, on both
shapes." On the two shapes it names that is now true — `g2_lap_parity.py`
confirms `def`-lane mismatches 13 → 0. On an `always` + zero-delay `raise`
cycle it is not:

```
   mi=1   sync=4    async=6     DIFFER
   mi=2   sync=8    async=9     SAME
   mi=3   sync=10   async=12    DIFFER
   mi=5   sync=14   async=18    DIFFER
   mi=10  sync=23   async=33    DIFFER
   mi=15  sync=35   async=48    DIFFER
   mi=20  sync=44   async=63    DIFFER
   mi=25  sync=53   async=78    DIFFER
   parity mismatches over limits 1-25 = 24/25
```

Both lanes trip with `RunawayChainError` at every limit — the budget *works*;
it is the amount of work it permits that differs. The chart contains no
timers and no delayed sends, so the #206 "timer-paced self-sends are
caller-driven on the sync engine" carve-out does not apply: every step here
is engine work the budget is defined to charge. The divergence is roughly
linear — async ≈ 3·mi + 3, sync ≈ 2·mi + 3 — i.e. the sync engine charges
the `always` settle step where the async engine charges `raise` + `always`
separately, or the reverse. At mi=25 the same chart is allowed **47 % more
work** on one engine than the other.

Severity is Medium for the same reason as round 8's version: low blast
radius, but the runaway budget is a *safety control* and this is a
*documented guarantee* about it. An OMS that sizes `maxIterations` against
the sync engine and deploys on the async one gets a materially different
cut point.

### D9-fuzz-5 / R9-15 — Low — `SnapshotMidStepError` from an invoked child reports `child=False`

Carried forward unchanged; see the prior-defect table. Diagnostic quality
only.

---

## 5. Not covered

Stated plainly so the gaps are not mistaken for passes.

- **The livelock fuzzer at full scale.** 352 of 500 configs (1 408 cells).
  P1 and P2 were unanimous throughout, and the P3/receipt populations were
  stable by roughly config 150, but a rare shape first appearing past
  config 352 would not have been seen.
- **The 12-minute / 200-machine soak.** Run at 45 s / 60 machines. A leak
  with a time constant above ~45 s, or a contention effect that only appears
  past 60 concurrent interpreters, is out of scope of this run. CPU was
  measured as process time over wall time, not per-thread.
- **`SyncInterpreter` + `async def` service** is `NotSupportedError` by
  design; every such cell is excluded rather than scored, so the sync engine
  is measured only on `def` services throughout.
- **`after`-provenance under load.** D10-fuzz-1 is an in-process
  single-machine repro. A forged `after` injected into the soak's priority
  lane at 20 k/s was not attempted; the type boundary is decided, but the
  interaction with timer cancellation and the chain budget is not.
- **Parallel regions and invoked children in the livelock fuzzer.** The
  generator emits flat charts (2–4 states) plus the round-9 shapes. Parallel
  and child-machine cases are covered by the targeted `n2` matrix (case C)
  but not by the random corpus; the brief asked for both.
- **`raise(delay=)` debt across snapshot/restore.** `n3` §C was designed but
  not run — no public `raise(delay=)`-from-an-action API path was confirmed
  within budget that would let the debt be observed mid-flight from a
  restored interpreter. The debt is measured *within* a process (`n4` §A)
  and the arming window is measured across snapshot/restore (`n3` §A/§B),
  but the intersection of the two is unmeasured.
- **Redaction of event payloads in logs** was not measured — logging is
  disabled in every script for throughput. Not a pass, simply unmeasured.
- **Multi-process / cross-host snapshot exchange** beyond
  `persist_event`/`restore_event` and the `engine:true` record door.

---

## 6. Verdict

**Round 9 is the best behavioural round this track has measured, and it
does not clear the bar for adoption.**

What it got right is substantial and is confirmed here rather than taken on
trust. **#204 is exactly right**: the `statesToInvoke` rule holds across
roll-forward, rollback, a parallel sibling reaching `final` and a multi-hop
`always` chain, on both engines and both service kinds, with the control
case still arming — measured at the service body, which is the only oracle
that cannot be fooled by an arm that is later cancelled. **#206 holds under
100-way concurrency** with a single-valued trip lap, which is the property
that actually matters: a budget whose cut point moves with load is not a
budget. **#207 is exactly-once across 200 concurrent storms** with correct
ids, an agreeing exception payload, a stable hook ordering and truthful
`has_dormant_invocations` — this is the kind of observability an OMS needs
and it was absent two rounds ago. **#208 holds in both directions** over
1 408 fuzzed cells. And two defects this track had carried — the `async def`
starvation (High) and the empty-configuration receipt (Medium) — are gone,
with the starvation fix confirmed by the reporter's own script at 100 % on
every cell and both ablations. Determinism is total. Zero regressions.

What blocks adoption is that **round 9 built a new guarantee on a primitive
this track had already reported as broken.**

**#203 is not a fix; it is a second customer of the same defect**
(D10-fuzz-1, Blocker). The round-8 report said, in terms, that a type check
cannot be a trust boundary when Python reconstructs the type — and named
`_replace`, `pickle` and the snapshot record as the vectors. Round 9 left
all three open (`g7` re-run: still 3/4) and routed `after` selection through
the identical `is_system_event` gate, adding four vectors including one that
needs nothing more than `from xstate_statemachine.events import
engine_after`. The result is a 60-second timer that fires on demand under
`strict: True`. For an order-management system, "an attacker who can call a
public function in your process can expire your orders and confirm your
fills" is not a hardening gap; it is the absence of the boundary the
changelog claims to have built.

**#209's parity sentence is false again** (D10-fuzz-2, Medium), and this is
the third consecutive round in which a changelog claim was generalised past
the shapes that were measured. Round 8 said "every limit tested" and was
wrong at odd limits; round 9 fixed those shapes, re-asserted the general
claim over limits 1–25, and is wrong on 24 of 25 limits for a chart made of
nothing but the engine work the budget exists to charge — with the error
growing to 47 % at mi=25.

**Recommendation for this track: do not adopt at `19cb1f1`.**

Required before re-evaluation:

1. **A provenance mechanism that is not a Python type check**
   (D10-fuzz-1 + R9-01, Blocker). The engine must mint a value it holds and
   compare by identity against the invocation or timer registration actually
   outstanding. Until then, `engine_after` / `engine_done` / `engine_error`
   should not be module-scope public names, and the `"engine": true` record
   door should be closed or gated on the same held token — #198 already
   established that the snapshot writer does *not* control the
   configuration, so the "they already control everything" rationale does
   not hold.
2. **Either fix the budget's engine/sync accounting or narrow the parity
   claim to the two shapes actually swept** (D10-fuzz-2, Medium). Given the
   history, the honest narrowing is the better outcome: state which shapes
   are pinned, and say that the accounting is not engine-identical in
   general.

R9-15 remains acceptable as a documented known issue.

**Trajectory.** The behavioural engineering is genuinely good and improving:
four of round 9's six behavioural findings verify clean under attacks
considerably harsher than the pins that cover them, and nothing that was
fixed in rounds 7 or 8 has regressed. The failure mode is now precisely
diagnosable and it is not a coding problem — it is that the changelog is
written as a statement of intent rather than of measurement, and that a
Blocker reported against a primitive was answered by shipping a second
feature on that primitive. Fixing the provenance mechanism properly would
close both this round's Blocker and the last round's in one change.

---

## 7. Artefacts

New, all standalone (stdlib + `xstate_statemachine`), under
`docs/research/xstate/battle-19cb1f1/fuzz/`; raw output in `fuzz/out/`.

| File | Covers | Exit |
|---|---|---|
| `n1_after_forgery.py` | **D10-fuzz-1 minimal repro** — #203 `after` provenance, 5 vectors, 4 forge a 60 s timer under `strict` | 1 |
| `n2_states_to_invoke.py` | #204 SCXML §6.1 matrix: `always` / `rollback` / parallel sibling `final` / `always` chain / resident control, ×2 kinds ×2 engines | 0 |
| `n3_persist_arming.py` | snapshot inside the arming window (hook-by-hook, checked against live ids); quiescent snapshot → static restore dormancy → `restart_services` arms exactly once | 0 |
| `n4_concurrency_stranded.py` | #206 100-way delayed self-ping-pong vs zero-delay reference; #207 stranded hook under 200 concurrent storms, ids + payload + ordering | 0 |
| `n5_livelock_receipt_fuzz.py` | livelock fuzzer, 352 configs × 2 kinds × 2 engines (P1/P2/P3) + #208 receipt legality fuzz, both directions | 1 (P3 only) |
| `n6_shrunk_repros.py` | **D10-fuzz-2 shrunk repro** — parity sweep 1–25 on an engine-work-only cycle; plus the corrected D1 receipt positive control | 1 |
| `n7_determinism_soak.py` | 50× determinism incl. stranded ids/hook count; 45 s / 60-machine soak with external priority producer + chaos snapshots | 0 |

Re-run verbatim from prior rounds: `battle-f28719c/fuzz/g7_forgery_repro.py`,
`g2_lap_parity.py`, `g1_persist_provenance.py`;
`battle-6db65d8/fuzz/r3_empty_repro.py`, `r8_ext_shed_loss.py`,
`r10_186_asymmetry.py`, `r12_determinism.py`, `r14_observability.py`,
`r18_ext_starvation_repro.py`, `r19_starvation_drain.py`.
