# Contract machines end-to-end — B6, B7, B8, B9, B10 (round 7, `221ce7c`)

**Library:** `_ref/xstate-statemachine` @ `main` = **221ce7c** ("Merge PR #178 from basiltt/fix/157-loop-side-raise-observable"; unreleased 0.8.1, `__version__` still reports `0.8.0` — keyed on commit).
**Contracts:** the same corrected catalogue JSON carried forward from `battle-cec108b/contracts/<B>.machine.json` (byte-identical; `B8.fixed.machine.json` == `B8.machine.json`). All five CD-01-clean.
**Engine:** async `Interpreter` primary, `SyncInterpreter` for parity. `SimulatedClock`, bounded inbox `OverflowPolicy.RAISE`, stub `MachineLogic(strict=True)`, catalogue policy block.
**Date:** 2026-09-20. Scripts in this directory (`c1`–`c11`, `repro/f*`, `repro/g1`–`g5`).

---

## 0. Headline

| | |
|---|---|
| Builds unmodified from the corrected catalogue JSON | **5 / 5** — zero `InvalidConfigError`, zero `ImplementationMissingError` |
| Policy block honoured as written | **5 / 5** (one read-back gap, OBS-01, unchanged) |
| Invariant / scenario checks (`c2`) | **55 run — 54 PASS, 1 FAIL** (was 53/55) |
| Round-5 cross-contract analogues (`c10`) | **7 / 7 PASS**, JSON byte-identical to `cec108b` |
| Snapshot/restore at every macrostep boundary (`c3`) | **31 / 31 MATCH**; **0** spurious `SnapshotMidStepError` |
| Cross-machine reconnect / divergence / sync parity (`c7`) | **4 / 4 PASS**, byte-identical to `cec108b` |
| **R6-03 class** (rollback + `invoke.onDone`) on B6/B9 | **2 / 2 PASS** — terminates, bounded, no orphan invoke |
| **R6-01 class** (`always` into invoked child) on B6/B9/B8 | **3 / 3 PASS** — terminates, bounded, observable |
| **LIBRARY defects** | **1 carried and now root-caused** (LD-03 → **LD-04**, high) |
| **OUR-CONTRACT defects** | **1** (CD-03, high — B8 `naked`⇄`verifying`, unchanged) |
| **Needs wrapper** | **1** (W-04b) — **W-04a is FIXED**, W-05 unchanged |

### What changed since `cec108b`

- **W-04(a) is FIXED.** #170 landed: a guard that *crashes* under `guardErrorPolicy: "raise"` now reads `denied=False, error=RuntimeError`. `Receipt.denied` alone is once again a correct denial discriminator. Confirmed on both engines (`repro/f5`, `c11`).
- **The `c2` B8 `SL_DEADLINE` FAIL is gone** — 54/55. The pre-emption reads `sl.naked` as the catalogue requires.
- **R6-03 and R6-01 are genuinely fixed on the real contract machines** (§4). These were the two shapes this round was chartered to exercise; both are clean, including the hardest case (B9 `armed → acting` rollback leaving **zero** pending invocations).
- **LD-03 is not fixed, and is worse than filed.** #168 claims the async invoke cycle now trips at the same lap count as sync. It does not on our machines, and §3 shows why: the fix is **timing-dependent**, not structural. This is a new, sharper finding — **LD-04**.

---

## 1. Build + policy read-back (`c1_build.py` → `c1.out`)

All five build and start clean; counts and start configurations match `cec108b` exactly (B6 `twap.armed`, B7 `chase.working`, B8 `sl.flat`+`watchdog.idle`, B9 `rule_instance.draft`, B10 `alert.armed`). `actionErrorPolicy`, `onUnhandled`, `guardErrorPolicy`, `strictTargets`, `logic.strict` all read back verbatim; `"*" in known_events` is **False** on all five.

**OBS-01 unchanged (LOW):** `spawnBlockingTimeout` still reads `<missing>` off `MachineNode` on all five — accepted at `create_machine`, not exposed, so a conformance lint cannot verify the §1.3b block by read-back.

---

## 2. Invariants (`c2_invariants.py` → `c2.out`) — 54 / 55

B6 (10/10), B7 (10/10), B9 (16/16), B10 (7/7) all PASS, matching `cec108b` and `3ed3099`. B8 now carries only one FAIL, and it is the known stale harness assertion:

- `INV-B8-b raising guard surfaces` — **HD-01, harness-stale.** The check asserts the `send(wait=True)` call site raises; it does not. The signal is the receipt. On `221ce7c` that receipt is now *better* than it was: `denied=False, error=RuntimeError` (#170), plus `last_transition_ok=False`. The contract obligation ("a crashed guard is not a denial") is now met **by `denied` alone**. Assertion should be retired, not re-scored.

The B8 `SL_DEADLINE during attaching pre-empts into naked` check, which failed on `cec108b`, now **PASSES**: `mid=[sl.attaching]`, `after=[sl.naked]`. Combined with `INV-B8-d` (`naked_unrecoverable` pages the owner) and `INV-3` (naked entry alerts + metricises), B8's *safety* invariants are all green. It is only liveness that still fails, and for our own reason (CD-03).

---

## 3. LD-04 (LIBRARY, HIGH) — the #168 chain budget for invoke cycles is timing-dependent, so it never fires in production shape

**Reproduced:** `repro/g4_budget_timing_dependent.py` (minimal, decisive), `repro/g2_b8_cycle_budget.py` (on B8), `repro/g3_cycle_bisect.py` (structural features ruled out). Supersedes LD-03.

CHANGELOG for #168 states: *"The invoke cycle now trips at the same lap count on both engines."* On the real B8 contract it does not trip at all — `repro/f2` still measures:

```
laps (attach_fallback_sl invocations): 4027     (500 / s)
raise_critical_alert fired:            4027     <-- P1 pager, 500 times a second
status: running   last_transition_ok: True   last_error: None   dropped: []
```

Identical to `cec108b`. `repro/g2` instruments the interpreter directly and finds the reason: **`_raise_depth` never leaves 0** on this machine (`max_depth_seen: 0`).

`repro/g3` rules out every structural explanation — parallel root, `SimulatedClock`, entry actions, the catalogue policy block, and the exact `parallel + SimulatedClock` B8 shape *all* run 21k–26k laps with `max_raise_depth: 0` and no trip. The difference is **not** in the machine.

`repro/g4` isolates it to one variable — the **kind of the service**, via loop timing:

| service kind | idle before entering the cycle | laps in 2 s | tripped | `last_error` |
|---|---|---|---|---|
| plain `def` | 0 ms | **52** | **yes** | `RunawayChainError` |
| plain `def` | 50 ms | **52** | **yes** | `RunawayChainError` |
| `async def` | 0 ms | **20 729** | no | `None` |
| `async def` | 50 ms | **21 506** | no | `None` |

**Root cause,** `interpreter.py:_enqueue_priority`:

```python
if self._processing:
    self._raise_depth += 1
```

A plain-`def` service resolves *inside* the entering macrostep, so `_processing` is `True` and its completion is charged. An `async def` service is awaited as a task; its `done.invoke` lands when the loop is **idle**, `_processing` is `False`, and the completion is **free**. The chain budget is therefore only reachable for plain-`def` services.

The library's own `#168` regression test (`tests/test_round6_findings.py::TestAsyncInvokeCycleTrips`) uses a **plain `def`** service. It passes, and it asserts `laps["a"] == laps["s"]` — parity between engines — while the `async def` path it was written to protect is untested and unbounded. **The test does not cover the fix's stated scope.**

**Why this matters more than LD-03 did.** Our catalogue mandates `async def` for every service (CV-C32, and §6 confirms CV-C32 must stay). So **100% of our contract invoke cycles are on the uncharged path.** The #168 fix, as shipped, cannot fire for us on any machine. A steady-state production interpreter is idle between laps by definition — the uncharged path is the *normal* one, not an edge case.

**Severity HIGH** (up from LD-03's MEDIUM) — not because the behaviour changed (it did not) but because a fix was landed, documented as closing this hole, and covered by a test that misses it. A reader of the CHANGELOG would reasonably retire their own spin detector. That is the harm.

**Suggested upstream fix:** charge the completion when it *originates* from a state the machine entered during a chain, rather than keying on `_processing` at delivery time; or track a per-invoke re-arm count. Minimum viable: extend `TestAsyncInvokeCycleTrips` to run the `async def` variant and the assertion will fail immediately.

**Status: NEEDS-WRAPPER, unchanged.** `cv.statechart` must supply its own spin detector, watching a **progress variable**, not a transition counter. W-03 stands as upgraded last round.

---

## 4. R6-03 and R6-01 on the real contract machines (`repro/g5_r603_r601_shapes.py`) — 5 / 5 PASS

This round's explicit charter. Each check asserts **terminates** (wall bound 4 s), **bounded** (lap ceiling) and **observable** (a health signal reads true if it does not terminate).

### R6-03 class — `actionErrorPolicy: "rollback"` on an entry action of an *invoking* state

| Machine | Shape | Result |
|---|---|---|
| **B6** | `armed --SLICE_DUE--> submitting_slice`, entry `bump_slices_done` raises | **PASS** |
| **B9** | `armed --TRIGGER--> evaluating --> acting`, entry `assert_safety_limits` raises | **PASS** |

B6: configuration rolled back to `twap.armed`, **`service_invocations: []`** — the aborted entry never armed `submit_child` — **`pending_invocations: []`**, no orphan, no re-arm loop, settled in 0.41 s. Receipt `changed=False, denied=True, error=RuntimeError`; `last_transition_ok=False`. The failure is fully observable.

B9 is the harder case and the one R6-03 was filed about: the machine *did* reach `evaluating` and run `S:evaluate_condition_dag` before the `acting` entry raised. The rollback returned it to `rule_instance.armed` with **`pending_invocations: []`** — the invoke the aborted entry would have armed did not survive, and the completed `evaluating` invoke did not resurrect the abandoned `acting`. No spin.

### R6-01 class — `always` landing on a state with an `invoke`

| Machine | Shape | Result |
|---|---|---|
| **B6** | `submitting_slice` has **both** entry actions and `always[slice_qty_below_min_roll_forward] -> armed`, over `invoke: submit_child` | **PASS** — `hung_send_wait: False`, settles to `twap.armed` in 0.32 s, **0** service invocations (the `always` wins, correctly) |
| **B9** | `armed --TRIGGER--> evaluating` invoke chain | **PASS** — settles, `last_transition_ok: True` |
| **B8** | `POSITION_OPENED` → `attaching` → `verifying` → `protected` ladder | **PASS** — settles into `sl.protected` in 0.31 s with exactly **2** service invocations (`attach_native_sl`, `read_position_sl`) |

B6's `submitting_slice` is the sharpest instance in the catalogue — it is simultaneously an R6-03 and an R6-01 shape — and it is clean in both polarities. **`send(wait=True)` never hung in any of the five checks**, which is the specific #166 failure. The per-macrostep settle budget behaves correctly for `always`-driven re-entry.

**Verdict: the #166/#167 half of round 6 is genuinely fixed and holds on our contracts.** It is only the `async def` completion-cycle half (#168 → LD-04) that does not.

---

## 5. W-04 — (a) FIXED by #170; (b) OPEN, unchanged

**(a) `denied` no longer conflates a crashed guard.** `repro/f5`, and `c11` for sync parity:

| case | `changed` | `deferred` | `denied` | `error` |
|---|---|---|---|---|
| guard returned `False` (true denial) | False | True | **True** | `None` |
| guard **raised** (not a denial) | False | False | **False** ← was `True` | `RuntimeError` |
| no handler declared | True/False | False | False | `None` |

`Receipt.denied` alone is now correct. The `(denied, error)` pair remains the more explicit discriminator and the wrapper should still use it, but the library-side defect is closed on **both** engines.

**(b) A denial is still stored and replayed later.** `repro/f6`, unchanged from `cec108b`:

```
3x TIGHTEN_SL denied by tightens_only=False   -> deferred_count = 3
flip tightens_only -> True; send WATCHDOG_MISS (forces a config change)
set_trading_stop invocations: 0 before -> 3 after
```

Three amendments a risk guard **refused** were replayed and executed later against a changed world. Under the mandated `onUnhandled: "defer"` the `guard_denied` disposition is still shadowed by `"deferred"` (`repro/f7`: `defer`→`deferred`, `ignore`→`guard_denied`, `error`→`errored`).

**Wrapper requirement CV-C25 stands, narrowed:** the library's precedence is defensible; it is the wrong default for an order path. A refused amend is not a queued amend. Preferred fix remains (i) — `@cv_guard` distinguishes "refuse and discard" from "not applicable here", and the wrapper drains denied events from the defer buffer at end of macrostep.

---

## 6. W-05 — CV-C32 stays, and LD-04 makes it load-bearing

Unchanged from `cec108b` (`c9_cvc32_executor.json` carried forward): a plain-`def` service still blocks the machine's own inbox for its full duration (441 ms vs 1 ms for `async def`), a custom `service_executor` does not help, completion ordering differs by service kind, and `SyncInterpreter` raises `NotSupportedError` for `async def`. #173's `service_pool_size` is a real improvement to *throughput* but does not touch the macrostep block, so it does not retire CV-C32 either.

**New interaction, and it is uncomfortable:** §3 shows the chain budget only protects **plain-`def`** services. So the two constraints pull against each other — CV-C32 (which we need, for inbox latency) puts us permanently on the unprotected side of LD-04. This is not a reason to relax CV-C32; a 440 ms inbox stall is a missed cancel and that is worse. It *is* a reason the wrapper's spin detector is mandatory rather than defence-in-depth.

---

## 7. Snapshot / restore, cross-machine, analogues — all green, all stable

- **`c3`** — snapshot at quiescence between every macrostep, restore into a fresh interpreter, resume, compare states *and* accumulated action trace: `B6 7, B7 7, B8 6, B9 7, B10 4` = **31/31 MATCH**, `SnapshotMidStepError at a quiescent point: NONE`. Identical to `cec108b` and `3ed3099`. The #169 entry/exit-action snapshot refusal did **not** produce a false positive at any quiescent boundary — the tightening is correctly scoped.
- **`c7`** — reconnect/freeze/divergence + sync parity: 4/4 PASS, **byte-identical** to the `cec108b` baseline.
- **`c10`** — B11/B16/B19 cross-contract analogues: **7/7 PASS**, JSON **byte-identical** to `cec108b`.
- **`c11`** — sync parity: #170 confirmed on the sync engine; the LD-03/LD-04 asymmetry persists (sync trips `RunawayChainError` at 500 laps with `dropped=[("done.invoke.ver","chain_budget")]`; async does not trip at all).

**No regression anywhere in this group against `cec108b` or `3ed3099`.** The round-6 fixes and the #165/#176 hot-path perf work (`__slots__`, shared sentinels, log gating, lazy deadline-heap lock, single-pass parser) introduced no behavioural change detectable by any of the 97 checks in this battery.

---

## 8. CD-03 (OUR-CONTRACT, HIGH) — unchanged, still blocking for B8

`repro/f2` reproduces identically on `221ce7c` (4027 laps / 8 s, 4027 P1 alerts, every health signal clean). The catalogue action from last round is unchanged and unblocked by anything in this commit:

1. Bounded fallback-attempt counter on `naked.invoke.onDone` (mirroring `attaching.onError`'s `attach_attempts_left`).
2. On exhaustion route to **`naked_unrecoverable`** — currently reachable only when `attach_fallback_sl` *errors*, so a successful-but-useless attach can never reach it. That is the hole.
3. Make `raise_critical_alert` edge-triggered (dedupe on `naked_since`).
4. Add **`CV-LINT-XS16`** — no two invoking states may target each other on their success paths without a bounded counter on at least one edge. Statically detectable in the catalogue JSON.

The escape hatch still works (`repro/f3`: both `send()` and `send_priority()` reach `sl.flat`), so the machine stays responsive while spinning — which is exactly what makes it invisible.

---

## 9. Findings register

| ID | Class | Sev | Summary | Status |
|---|---|---|---|---|
| **LD-04** | LIBRARY | **HIGH** | #168's async invoke-cycle budget is **timing-dependent**: `_enqueue_priority` charges a completion only `if self._processing`, so an `async def` service's `done.invoke` (delivered on an idle loop) is never counted. 20k+ laps, `_raise_depth` stuck at 0, no trip. The library's own #168 test uses a plain `def` service and so passes. Every CV-C32-compliant contract is on the uncharged path | **OPEN** — supersedes LD-03; needs wrapper; upstream: extend the #168 test to `async def` |
| **CD-03** | OUR-CONTRACT | HIGH | B8 `naked` ⇄ `verifying` unbounded cycle when fallback attach succeeds but the exchange reports no SL: 500 laps/s, 500 P1 alerts/s, every health signal clean | **OPEN, blocking for B8** — bound the counter → `naked_unrecoverable`; dedupe the alert; add `CV-LINT-XS16` |
| **W-04b** | NEEDS-WRAPPER | HIGH | under mandated `onUnhandled: "defer"` a guard denial is buffered and **replayed later** — 3 refused amends executed after the guard flipped | **OPEN** — CV-C25 |
| **W-05** | NEEDS-WRAPPER | MED | `service_executor` / `service_pool_size` do not retire CV-C32 (441 ms inbox stall, different completion ordering, sync engine cannot run `async def`) | **CV-C32 STAYS** — and §6: it is what puts us on LD-04's unprotected side |
| **OBS-01** | LIBRARY | LOW | `spawnBlockingTimeout` accepted by `create_machine`, not exposed on `MachineNode`; §1.3b unverifiable by read-back | OPEN, informational |
| **LD-03** | LIBRARY | was MED | chain budget exempts system events on async, charges on sync | **SUPERSEDED by LD-04** — partially addressed by #168; the real mechanism is the `_processing` gate, not `is_system_event` |
| **W-04a** | NEEDS-WRAPPER | was HIGH | `denied=True` also set for a crashed guard | **FIXED on `221ce7c`** by #170, both engines |
| **R6-03 / R6-01** | — | — | rollback+`invoke.onDone` and `always`-into-invoked-child on B6/B8/B9 | **FIXED and confirmed on the real contracts** — 5/5, `send(wait=True)` never hung |
| **HD-01** | HARNESS | — | `c2`'s `INV-B8-b` asserts a call-site raise; the signal is the receipt (now `denied=False, error=RuntimeError`) | Retire the assertion |

---

## 10. Verdict for this group

**B6, B7, B9 and B10 remain fit on `221ce7c` as written**, with more margin than last round: 54/55 invariants, 31/31 snapshot MATCH, 7/7 analogues, 4/4 cross-machine — all byte-stable against two prior commits — and the two round-6 shapes this round was chartered to test (R6-03 rollback+invoke, R6-01 always-into-invoke) are **genuinely fixed on the real contract machines**, including B6's `submitting_slice`, which is both shapes at once. `send(wait=True)` did not hang once. #170 closes W-04a outright.

**B8 remains the only ship-blocker, and the cause is still ours (CD-03), not the library's.** Safety is intact — `protected` is unreachable without a confirmed SL, `naked` alerts and metricises, `naked_unrecoverable` pages — and this round the `SL_DEADLINE` pre-emption check went green. Liveness still fails as a spin.

**The round's most important result is LD-04, and it is a warning about reading changelogs.** #168 was landed, documented as bounding async invoke cycles at parity with sync, and pinned by a regression test — and it does not fire on any machine we own, because the test's service is a plain `def` and ours are all `async def` by mandate. The behaviour did not regress; the *belief about the behaviour* did. Anyone who retired a spin detector on the strength of that CHANGELOG entry now has an unbounded, silent, fully-responsive alert storm with no detector.

**Ship gate for B8, unchanged:** CD-03 fixed in the catalogue, W-04b wrapper in place, and a progress-variable spin detector — which LD-04 now makes mandatory rather than belt-and-braces. LD-04 should be raised upstream; the one-line reproduction is to add an `async def` variant to `TestAsyncInvokeCycleTrips`.

---

## 11. Scripts

| File | Purpose |
|---|---|
| `c1_build.py` | build + policy read-back + start smoke (→ `c1.out`) |
| `c2_invariants.py` | 55 invariant/scenario checks (→ `c2.out`) — 54 PASS |
| `c3_snapshot.py` | snapshot/restore at every macrostep boundary (→ `c3.out`) — 31/31 |
| `c7_crossmachine_and_sync.py` | reconnect/resync, divergence, sync parity (→ `c7.out`) |
| `c10_analogues.py` | B11/B16/B19 cross-contract analogues (→ `c10.out`) — 7/7 |
| `c11_sync_parity.py` | sync parity for this round's findings (→ `c11.out`) |
| **`repro/g5_r603_r601_shapes.py`** | **R6-03 + R6-01 on B6/B8/B9 — 5/5 PASS** (→ `.json`) |
| **`repro/g4_budget_timing_dependent.py`** | **LD-04 — decisive: plain `def` trips at 52 laps, `async def` runs 20k+** (→ `.json`) |
| `repro/g3_cycle_bisect.py` | LD-04 — rules out parallel/SimulatedClock/entry/policies as the cause (→ `.json`) |
| `repro/g2_b8_cycle_budget.py` | LD-04 on B8 — `_raise_depth` instrumented, never leaves 0 (→ `.json`) |
| `repro/g1_asyncdef_cycle_unbounded.py` | **superseded by g4** (harness bug: both rows ran plain `def`); kept for audit |
| `repro/f2_naked_verify_livelock.py` | CD-03 — 4027 laps / 8 s, all signals clean |
| `repro/f3_escape_hatch.py` | CD-03 — `POSITION_FLAT` / `send_priority` do break the cycle |
| `repro/f5_denied_conflation.py` | **W-04a re-test — FIXED**, crashed guard now `denied=False` |
| `repro/f6_denied_defer_buffer.py` | W-04b — 3 refused amends still replayed |
| `repro/f7_disposition_precedence.py` | W-04b — `defer` still shadows `guard_denied` |
| `repro/f9_sync_budget_signal.py` | LD-04 parity — sync trips `RunawayChainError` at 500 laps |

Library source untouched; no git run in the project repo; all scripts inside the 120 s bound.
