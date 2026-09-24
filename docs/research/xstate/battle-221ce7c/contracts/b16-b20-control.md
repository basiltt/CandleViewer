# B16–B20 contract machines end-to-end on `221ce7c`

Date: 2026-09-20. Build under test: library `main` @ **`221ce7c`** (unreleased 0.8.1;
`__version__` still reports `0.8.0` — every claim here keys on the commit).
Round-6 fixes in scope: **#166–#175**, **#157**, **#122-as-designed**, plus the
hot-path PRs **#165/#176**.

Scope: the five control-plane machines — **B16** AuthSession, **B17** LiveEnablement,
**B18** KillSwitch, **B19** Reconciliation, **B20** RiskLockout — driven end-to-end
under the mandatory configuration (`actionErrorPolicy: rollback`, `onUnhandled:
defer` on the order path / `error` on the control path, `guardErrorPolicy: raise`,
`strictTargets`, `strict`, bounded inbox with `OverflowPolicy.RAISE`,
`SimulatedClock`, trace-plugin stub standing in for `CvErrorHooks`).

Source of truth for the machines: the corrected catalogue JSON
(`battle-3ed3099/contracts/B1{6,7,8,9}.catalogue.json`, `B20.catalogue.json`),
copied unchanged into this directory. Scripts and raw results live beside this
file; every number below is reproduced from `results/*.json`.

---

## 0. Headline

**One new LIBRARY Blocker, on the async engine, in the exact shape the round-6
notes claim to have closed.**

- **CV-221-01 (Blocker, LIBRARY).** `actionErrorPolicy: "rollback"` + a
  **coroutine** (`async def`) service's `invoke.onDone` re-arms the invoke
  without bound. B18 `ENGAGE` — one operator kill-switch press — produced
  **3 547 `flatten_all_positions` invocations in 3.0 s** and was still
  accelerating linearly when we stopped watching. `status` stays `"running"`,
  the receipt is `changed=True, error=None`, and the settle budget is **never
  charged**: `maxIterations` of 2, 5, 25, 100 and 1000 all behave identically.
  This is the R6-03 shape, and it is **not fixed** at `221ce7c`.
- **The round-6 fix is real but lands on one service kind only.** The identical
  machine with the identical raise, with services written as plain `def`
  instead of `async def`, is bounded exactly at `maxIterations`: 7 calls at
  `maxIterations=5`, 52 at 50, 1 002 at the 1 000 default, and `last_error` is
  `RunawayChainError`. **Service definition kind — a detail with no semantics in
  the statechart — decides whether a livelock guard exists.** Root cause
  isolated to the delivery lane (§4).
- **Everything the previous round established is unchanged.** All six prior
  contract suites (`k0`–`k6`) reproduce **byte-identically** against
  `battle-cec108b/contracts/results/` — `k0_build`, `k1_b16_b17`, `k2_b18`,
  `k3_b19_b20`, `k4_redo`, `k5_edges`, `k6_failsnap` all `SAME`. No regression,
  and no round-6 improvement, on any behaviour those suites cover.
- **Snapshot/restore at quiescence between every macrostep remains clean** for
  all five machines: zero mid-step refusals, zero state/context diffs against
  the unsnapshotted run, identical transition traces.
- **B16, B17 and B20 carry no `invoke` and no `always` at all** (§1) and are
  therefore untouched by CV-221-01. The defect is confined to **B18 and B19**.

**Verdict by machine.**

| | Machine | Library verdict on `221ce7c` |
|---|---|---|
| **B16** | AuthSession | **GO** — no new library defect; carried OUR-CONTRACT defects C-04 (Blocker), C-05 (Low) |
| **B17** | LiveEnablement | **GO** — no new library defect; carried W-03 |
| **B18** | KillSwitch | **NO-GO — CV-221-01** (plus carried C-07b) |
| **B19** | Reconciliation | **NO-GO — CV-221-01** (plus carried C-06) |
| **B20** | RiskLockout | **GO** — no new library defect |

B18 and B19 are the two machines in this group that invoke services. A kill
switch that calls `flatten_all_positions` ~1 200×/s because an operator pager
action raised is the worst possible place for this shape to land.

---

## 1. Step 0 — build, and the shape census

All five machines build on `221ce7c` with the full stub logic **and** with a
bare `MachineLogic()`; no `InvalidConfigError`. Policy fields round-trip onto
the `MachineNode` as declared (`results/k0_build.json`).

| | `id` | actions | guards | services | events | `invoke` | `always` | `onDone` |
|---|---|---|---|---|---|---|---|---|
| B16 | `session` | 18 | 1 | 0 | 11 | **0** | **0** | **0** |
| B17 | `live_gate` | 10 | 3 | 0 | 5 | **0** | **0** | **0** |
| B18 | `kill_switch` | 9 | 5 | **2** | 3 | **2** | **1** | **2** |
| B19 | `reconciliation` | 20 | 3 | **3** | 7 | **3** | **1** | **3** |
| B20 | `risk_lockout` | 16 | 5 | 0 | 5 | **0** | **0** | **0** |

This census is the whole exposure story for this group. The round-5/6 blocker
classes are defined on `invoke` and `always`; **only B18 and B19 have either**.

Both carry **both** hazardous shapes:

- **R6-03 class — `rollback` + `invoke.onDone` → entry/transition actions.**
  B18 `flattening.onDone → engaged_incomplete`, whose `entry` is
  `["page_owner", "emit_incomplete_metric"]`. B19 `diffing.onDone → remediating`
  with transition action `store_divergences`, and `remediating.onDone →
  reporting` whose `entry` is four actions including `persist_report`.
- **R6-01 class — `always` reachable into an invoking sibling.** B18
  `engaging.always → cancelling` (which invokes `cancel_all_working_orders`);
  B19 `reporting.always → {divergent, idle}` re-entered from `remediating`.

`build_full_stub` and `build_bare_logic` are both `OK` for all five: missing
implementations are still not a build error (carried **C-01**), and the
catalogue's promised `halted` states still do not exist (carried **C-07**).

---

## 2. What reproduced unchanged from the previous round

The six prior suites were re-run verbatim against `221ce7c`. Results compared
byte-for-byte with `battle-cec108b/contracts/results/`:

```
SAME k0_build.json   SAME k1_b16_b17.json  SAME k2_b18.json
SAME k3_b19_b20.json SAME k4_redo.json     SAME k5_edges.json
SAME k6_failsnap.json
```

So, carried forward without re-litigation and **still accurate on `221ce7c`**:

| Invariant group | Status |
|---|---|
| **B16** INV-b (revocation reason + broadcast, six paths) | **PASS** |
| **B16** INV-a / INV-d at session level | **FAIL — C-04** (OUR-CONTRACT, Blocker): only `REVOKE` clears elevation; `LOGOUT` / `IDLE_DEADLINE` / `ABSOLUTE_DEADLINE` leave it standing, and elevation can be acquired *after* revocation |
| **B16** INV-c (every step-up audited) | **PARTIAL FAIL — C-05** (Low): `STEP_UP_OK` while already elevated writes no audit |
| **B17** INV-a…INV-e | **PASS**; `rollback` replaces the withdrawn `"fail"` cleanly |
| **B17** authorisation events replayable | **W-03** (needs-wrapper), carried |
| **B18** INV-b (block precedes outward effects), INV-c, INV-e | **PASS** |
| **B18** INV-d (release requires owner + elevation) | **FAIL — C-07b** (OUR-CONTRACT, Blocker): `onUnhandled: "error"` turns two ordinary operator mistakes into a dead kill switch |
| **B19** INV-a; deferral of the trigger (C-02) | **PASS / closed** |
| **B19** INV-b (operator resolution clears lockout) | **FAIL — C-06** (OUR-CONTRACT, High): `stale_lockout` only listens for `RECONNECTED` |
| **B20** all invariants | **PASS** |
| **CV-C32** (`service_executor`, #149) does not retire the async-only rule | carried, unchanged |

Nothing in #166–#175 moved any of these. That is expected — they are contract
defects and unrelated engine paths — but it is worth stating that the round-6
work introduced **no regression** anywhere these suites reach.

---

## 3. CV-221-01 — the new Blocker

### 3.1 In the contract machine

`q1_r6class.py`, `q4_window.py` (`results/q1_r6class.json`,
`results/q4_window.json`). B18, `guard_vals = {cancel_working_requested: True,
flatten_requested: True, all_accounts_flat: False}` — i.e. the operator asked
for cancel **and** flatten, and not every account went flat, which is precisely
the incident-day configuration. The single failing action is `page_owner`,
the entry action of `engaged_incomplete` — a pager call, the most plausible
thing in the machine to raise.

One `send("ENGAGE", wait=True)`:

| Observation window | `flatten_all_positions` + `cancel_all_working_orders` calls |
|---|---|
| 0.2 s | 174 |
| 1.0 s | 1 190 |
| 3.0 s | 3 547 |

Sampled trail at the 3 s window: `(0.50, 541) (1.00, 1136) (1.50, 1731)
(2.00, 2330) (2.50, 2940) (3.00, 3547)` — **dead linear at ~1 190 service
invocations per second, no plateau**. The receipt for `ENGAGE` returned
`changed=True, error=None` in 0.0 s. Throughout: `status="running"`,
configuration pinned at `['kill_switch.flattening']`, `last_error` is the
action's own `RuntimeError` — **not** `RunawayChainError`.

B19 reproduces the same shape twice over (`results/q1_r6class.json`):
`store_divergences` raising on `diffing.onDone` → 120 service calls in the
first 90 ms; `persist_report` raising on `reporting`'s entry (the R6-01
`always`-side variant) → 121 service calls and 241 actions.

Controls in the same script terminate correctly: `b18_control` 2 service calls
→ `kill_switch.engaged`; `b19_control` 3 → `reconciliation.idle`.
`b18_rollback_engaging_entry` (raise *before* any invoke is armed) rolls back
cleanly to `kill_switch.clear` with `changed=False, error=RuntimeError` and
**0** service calls — so the rollback machinery itself is sound; it is the
re-arming of a completed invoke that does not terminate.

### 3.2 `maxIterations` does not bound it

`q3_budget.py`, 5 repetitions per cell, B18, same configuration
(`results/q3_budget.json`). `declared_max_iterations` was asserted to be
honoured on the `MachineNode` in each case:

| `maxIterations` | service calls across 5 reps (≈0.2 s each) |
|---|---|
| unset (1000) | 134, 175, 188, 176, 187 |
| **2** | 193, 165, 187, 194, 176 |
| **5** | 183, 178, 188, 153, 184 |
| **25** | 187, 189, 161, 187, 192 |
| **100** | 181, 169, 156, 138, 167 |

No trend, and the spread is pure scheduler noise — the count is a function of
**how long you watch**, not of the budget. `last_error` is `RuntimeError` in
every cell. `service_pool_size=1` (the new #173 knob) does not change this
either (`results/q2_trip.json`: `b18_pool1`, 142 calls).

### 3.3 Not recoverable, not observable

`q2_trip.py` (`results/q2_trip.json`). After the chain is running, an external
event **does not end it**. In the minimal repro (`q5_repro.py`) an external
`send` before the chain (664 calls) and after (633 more in the next 0.5 s)
shows the rate completely unaffected; the event itself is rejected with
`UnknownEventError` under `onUnhandled: "error"`, so the control-path policy
this group mandates removes even the accidental escape hatch.

For a wrapper, the damning row is the observability one: `status="running"`,
`changed=True`, `error=None`, `last_error=RuntimeError` (indistinguishable from
a single ordinary action failure the operator already fixed),
`on_event_dropped` never fires, and `last_transition_ok=False` is also what an
ordinary rolled-back transition reports. **There is no signal a supervisor can
poll that separates "one action raised once" from "this machine is calling
`flatten_all_positions` 1 200 times a second".**

### 3.4 Minimal repro and necessity ablations

`q5_repro.py` (`results/q5_repro.json`). Four states, one service, one action:

```json
{"id": "m", "initial": "idle", "actionErrorPolicy": "rollback",
 "states": {
   "idle": {"on": {"GO": "a"}},
   "a":  {"invoke": {"id": "s", "src": "svc",
                     "onDone": {"target": "#m.c"},
                     "onError": {"target": "#m.c"}}},
   "c":  {"entry": ["boom"]}}}
```
with `async def svc` returning `{"ok": True}` and `boom` raising `RuntimeError`.

| Cell | svc @1 s | svc @2 s | outcome |
|---|---|---|---|
| **repro (async svc, rollback)** | 1 324 | 2 623 | **unbounded**, `m.a`, `running` |
| `actionErrorPolicy: "fail"` | 1 | 1 | machine `stopped`, config cleared — correct (#145) |
| `actionErrorPolicy: "continue"` | 1 | 1 | rests in `m.c` — correct |
| guarded vs unguarded `onDone` | 1 269 → 2 436 | | **not necessary** — the guard is irrelevant |
| no raise in the entry action | 1 | 1 | rests in `m.c` — correct |

So the necessary and sufficient ingredients are exactly three: **`rollback`** +
**an action that raises at the `onDone` target** + **a coroutine service**.
`rollback` is CV-C31, mandatory for us and not negotiable.

---

## 4. Root cause — the delivery lane, not the policy

This is the part that matters for the upstream fix, and it is sharp.

`q7_kind.py` (`results/q7_kind.json`) holds the machine, the policy, the raise
and the watch window constant and varies **only whether `svc` is `def` or
`async def`**:

| | `maxIterations` | svc @1 s | svc @2 s | still growing | `last_error` |
|---|---|---|---|---|---|
| `def svc` | 5 | **7** | **7** | **no** | **`RunawayChainError`** |
| `def svc` | 50 | **52** | **52** | **no** | **`RunawayChainError`** |
| `async def svc` | 5 | 1 462 | 2 900 | **yes** | `RuntimeError` |
| `async def svc` | 50 | 1 469 | 2 908 | **yes** | `RuntimeError` |

The plain-`def` path is *exactly* `maxIterations + 2` and trips the documented
guard. The coroutine path has no guard at all.

`q9_lane.py` (`results/q9_lane.json`) instruments both the priority lane and the
public `send()` and counts where each `done.invoke.s` is published:

| service kind | completions via `_deliver_priority` | via public `send()` | `_raise_depth` at end |
|---|---|---|---|
| `def` | **7 (all)** | 0 | 0, tripped `RunawayChainError` |
| `async def` | **0** | **60 (all, sampling cap)** | **0** |

`q8_rootcause.py` (`results/q8_rootcause.json`) closes it: for the `def` service
every completion arrives at `_deliver_priority` with `_processing == True` and
is **charged** (`raise_depth_before` climbing 0,1,2,3,4,5,6 → trip); for the
coroutine service `_deliver_priority` sees **zero** completions.

The mechanism, read against `interpreter.py` on `221ce7c`:

- `_deliver_priority` (line 2277) implements the #166–#168 rule — *"if
  `self._processing`, charge `_raise_depth`"*. A plain-`def` service runs on the
  executor inside the entering macrostep, so its completion lands here while
  `_processing` is `True` and is charged. **This is the round-6 fix, and it
  works.**
- A coroutine service's completion is published by `_run_service_task` with
  `await self.send(done_event)` (line 2414) — the **public inbox** API.
- In `_run_event_loop` (line 1647) the budget reset is
  `if not is_system_event(event) or from_inbox: self._settle_iterations = 0;
  self._chain_tripped = False`. A `done.invoke.*` **is** a system event, but it
  arrived `from_inbox`, so the `or` fires and **the budget is reset on every
  single lap of the chain**.

The round-6 work moved the accounting onto the instance and charged
self-generated completions — but it charged them *at the priority lane*, and the
coroutine completion path never goes through the priority lane. The
`from_inbox` disjunct, added so a caller-queued event starts a fresh budget,
then actively **clears** the budget the chain was accumulating.

**One-line characterisation for upstream:** a coroutine service's `done.invoke`
re-enters through `send()`, so `from_inbox` is `True`, so the per-macrostep
settle budget is reset on every lap and the self-generated invoke chain is
never charged — the plain-`def` path, which publishes through
`_deliver_priority`, is charged correctly and trips as documented. The fix is to
publish engine-generated completions on the lane the fix already guards (or to
exclude system events from the `from_inbox` reset), not to add a third patch.

---

## 5. Is it wrappable?

`q10_wrapper.py` (`results/q10_wrapper.json`) tests the only candidate
mitigation on the **real B18**, by rewriting the stub's services as plain `def`
while holding everything else identical:

| B18 cell | svc @1 s | svc @2 s | growing | `last_error` |
|---|---|---|---|---|
| async services, default budget | 1 260 | 2 548 | **yes** | `RuntimeError` |
| **plain-`def` services, default budget** | **1 002** | **1 002** | **no** | **`RunawayChainError`** |
| **plain-`def` services, `maxIterations: 5`** | **7** | **7** | **no** | **`RunawayChainError`** |
| async services, `maxIterations: 5` | 1 228 | 2 536 | **yes** | `RuntimeError` |

So there **is** a mitigation, and it is a real one: write every B18/B19 service
as a plain `def` and set `maxIterations` low. But it is a bad trade and we
should not treat it as a GO:

1. It contradicts the library's own guidance recorded this round under **#174** —
   a plain-`def` service **blocks its own machine's `after` timers for its whole
   duration**, and the CHANGELOG tells you to *make the service a coroutine if a
   timer must interrupt it*. B19's `backing_off` retry ladder is exactly that
   case. The two defects push in opposite directions.
2. `cancel_all_working_orders` and `flatten_all_positions` are network calls.
   Forcing them onto the 4-wide (now configurable, #173) executor pool and
   blocking the entering macrostep for their whole duration is a throughput and
   liveness regression on the path where latency matters most.
3. It is a global, invisible coupling: any future maintainer who converts a
   service to `async def` — the obvious modernisation — silently re-arms an
   unbounded order-side livelock, with no test, type or lint signal.
4. Even when bounded, the machine still burns `maxIterations` real service calls
   before tripping, and still rests in `kill_switch.flattening` — not a safe
   resting state for a kill switch.

**Classification: LIBRARY, Blocker, not wrappable in any form we would sign
off.** The wrapper knob is worth recording as a break-glass measure, not as a
mitigation that unblocks.

---

## 6. Snapshot / restore discipline

Snapshot at quiescence between **every** macrostep, restore into a fresh
interpreter with `restart_services=True, restart_timers=True`, resume, then
compare states, context, status and the full transition trace against an
unsnapshotted run of the same sequence (`cdrv.run_snapshotted`, exercised by
`k1`–`k3`).

All five machines, all sequences: **zero mid-step refusals, zero diffs,
identical traces** — byte-identical to the previous round's results. #169's
entry/exit-action snapshot refusal at the root does not fire here because we
only ever snapshot at quiescence, which is CV-C23 and already mandatory for us.
No new constraint.

`k6_failsnap` (the `actionErrorPolicy: "fail"` snapshot path) is likewise
unchanged: the machine reaches `status="stopped"` with the configuration
cleared, and the `"error"`-without-a-recorded-error snapshot is refused.

---

## 7. Sync parity

B18 and B19 **cannot be driven on `SyncInterpreter` at all** with coroutine
services: `NotSupportedError: Service 'cancel_all_working_orders' is async and
not supported.` (`results/k2_b18.err`, `results/k3_b19_b20.err`) — carried,
by design, and consistent with CV-C32.

With plain-`def` services the shape runs on both engines and the parity result
is the cleanest statement of the defect (`q6_parity.py`,
`results/q6_parity.json`):

| engine | `maxIterations` | service calls | wall | outcome |
|---|---|---|---|---|
| **sync** | 1000 | **2** | 0.005 s | rests in `m.a`, `running` |
| **async** | 1000 | **1 002 / s** | — | `RunawayChainError`, still in `m.a` |
| **sync** | 5 | **2** | 0.001 s | rests in `m.a`, `running` |
| **async** | 5 | **7** | — | `RunawayChainError` |

The sync engine does not merely bound the chain — it **does not loop at all**
(2 calls, sub-millisecond). The async engine loops to its budget even in the
fixed path. That residual asymmetry is not a blocker, but it means "the invoke
cycle now trips at the same lap count on both engines" holds for the trip
count, not for the underlying behaviour: sync never needs the trip.

B16, B17 and B20 have no services and reach full sync parity
(`k1`/`k3` `*_sync` cells, unchanged).

---

## 8. Defect register delta for this group

| # | Class | Machine | Severity | Statement |
|---|---|---|---|---|
| **CV-221-01** | **LIBRARY** | B18, B19 | **Blocker** | `rollback` + a **coroutine** service's `invoke.onDone` + a raising action at the target re-arms the invoke **without bound**: 3 547 service calls in 3.0 s for one `ENGAGE`, `status="running"`, `error=None`, budget never charged at any `maxIterations`. Plain-`def` services are correctly bounded — the guard added in #166–#168 is charged at `_deliver_priority`, which the coroutine completion path bypasses via `send()` (`from_inbox` then resets the budget every lap). |
| CV-221-02 | LIBRARY | — | Low | Sync/async asymmetry *within* the fixed path: on the plain-`def` repro the sync engine terminates in 2 service calls, async loops to `maxIterations` (7 at 5, 1 002 at the default) before tripping. Bounded and observable, so not a blocker — but the engines agree on the trip, not on the behaviour. |
| CV-221-03 | NEEDS-WRAPPER | B18, B19 | Medium | The break-glass mitigation for CV-221-01 (plain-`def` services + low `maxIterations`) directly contradicts #174's documented guidance (a plain-`def` service blocks its own `after` timers), which B19's `backing_off` ladder depends on. Whichever way we go, one of the two is violated; needs an explicit decision recorded against B19. |
| C-01 | OUR-CONTRACT | all | Low | carried — missing implementations are not a build error |
| C-04 | OUR-CONTRACT | B16 | Blocker | carried, unchanged — elevation outlives `LOGOUT`/`IDLE_DEADLINE`/`ABSOLUTE_DEADLINE`; acquirable after revocation |
| C-05 | OUR-CONTRACT | B16 | Low | carried — `STEP_UP_OK` while elevated is unaudited |
| C-06 | OUR-CONTRACT | B19 | High | carried — `stale_lockout` only listens for `RECONNECTED`; INV-B19-b has no escape hatch |
| C-07 | OUR-CONTRACT | all | Low | carried — catalogue promises `halted` states that do not exist |
| C-07b | OUR-CONTRACT | B18 | Blocker | carried — `onUnhandled: "error"` turns two operator mistakes into a dead kill switch |
| W-02 / W-03 | NEEDS-WRAPPER | B16 / B17 | — | carried, unchanged |

**New library defects this round: 1 Blocker, 1 Low, plus 1 wrapper obligation.**
No regressions.

---

## 9. What we recommend

1. **Do not ship B18 or B19 on `221ce7c`.** CV-221-01 is sufficient on its own,
   independent of the carried contract defects, and it lands on the two machines
   whose side effects are order cancellation and position flattening.
2. **B16, B17, B20: the library is not what blocks them.** Their remaining
   defects are ours (C-04, C-05, W-02, W-03) and are already ticketed. Proceed
   under the existing constraints.
3. **Upstream, this is one change, not three.** Publish engine-generated
   completions on the lane the #166–#168 fix already guards, or exclude system
   events from the `from_inbox` budget reset at `interpreter.py:1647`. The
   plain-`def` evidence proves the accounting itself is correct; only the
   coroutine completion's route into the loop is wrong. The four-cell
   `q7_kind.py` table is the smallest useful regression pin — it differs in one
   keyword and separates bounded from unbounded.
4. **Add the service-kind dimension to every future livelock probe.** This round
   would have concluded "fixed" on any probe that happened to use a plain `def`
   service. Both kinds, always.

---

## 10. Reproduction

Run from this directory with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/Scripts/python <script>`; every
script writes `results/<name>.json` and is self-bounded well inside 120 s.

| Script | Question it answers |
|---|---|
| `k0_build.py` | do all five build under the mandatory config? |
| `k1_b16_b17.py`, `k2_b18.py`, `k3_b19_b20.py` | invariants + snapshot/trace parity, per machine |
| `k4_redo.py`, `k5_edges.py`, `k6_failsnap.py` | carried edge cases, `fail`-policy snapshot path |
| `q1_r6class.py` | the R6-01/R6-03 shapes as they occur in B18/B19 |
| `q2_trip.py` | trip observability, post-trip liveness, `service_pool_size` |
| `q3_budget.py` | does `maxIterations` bound the blast radius? (5 reps/cell) |
| `q4_window.py` | terminates, or linear in the observation window? |
| `q5_repro.py` | 4-state minimal repro + 4 necessity ablations + recovery |
| `q6_parity.py` | sync/async parity on the repro |
| `q7_kind.py` | **the discriminator**: `def` vs `async def` service |
| `q8_rootcause.py`, `q9_lane.py` | which lane each completion is published on |
| `q10_wrapper.py` | is the mitigation real on the actual B18? |
