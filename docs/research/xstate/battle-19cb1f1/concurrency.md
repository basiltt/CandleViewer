# Battle test (round 10) — CONCURRENCY, BACKPRESSURE & RESOURCE LIMITS

Target: `xstate-statemachine` @ `19cb1f1` (merge of #211, round-9 fixes
#203–#210; unreleased 0.8.1, `__version__` still reports `0.8.0` — keyed
on the commit).

Scripts: `battle-19cb1f1/concurrency/`. Every new probe (`t1`–`t10`) is
standalone — stdlib + `xstate_statemachine` only, helpers inlined, proven
from a neutral cwd. Every service/action check runs BOTH `def` and
`async def`.

---

## 0. Bottom line

Round 9's two open concurrency defects are **both STILL-PRESENT**, and
the round-9 fixes introduced **two new defects of their own** — one in
the fix for #203, one in the fix for #204. The remaining round-9
machinery (#206, #208, #204's arming window) verified clean under
attack.

| ID | Sev | One line |
|----|-----|----------|
| **D10-concurrency-1** | **High** | #203's `after` provenance check is type identity against a plain subclass. `_EngineAfter` is constructible **four** ways (import path, `type(held)`, `pickle`, `restore_event({"engine": true})`); each fires a **60-second** timer instantly, on **both engines**, 8/8 cells. The public-class control is correctly refused, so the guard exists — it just does not guard. |
| **D10-concurrency-2** | **High** | #204 records states to invoke at ENTRY only. An `onDone` whose target **is its own source state** never exits, so it is never re-recorded and never re-armed: the service runs **once** and the machine parks in the invoking state with `has_dormant_invocations == True`, **no** `on_invocation_stranded`, **no** `last_error`, `status == "running"`. The semantically identical loop routed through one intermediate state re-invokes 11× and trips the budget correctly. Both kinds, both engines. |
| **D10-concurrency-3** | **High** | D9-concurrency-1 unchanged — `restore_event({"engine": true})` still mints a trusted `_EngineDone` that drives a real `onDone` past `strict` and discards the genuine result. |
| **D10-concurrency-4** | Low | D9-concurrency-2 unchanged — call-site `QueueOverflowError` refusals fire no `on_event_dropped`. 241 414 of 243 225 refusals (**99.3 %**) invisible this run. |

D10-1 and D10-2 are the same shape of mistake in two different fixes:
**a property the engine knows at mint/entry time was re-derived later
from something that does not carry it** — a Python type in one case,
a state-entry event in the other.

Verdict: **ADOPT WITH CONSTRAINTS, constraints tightened** (§7).

---

## 1. Method and reductions

The 20-minute whole-task bound is the binding constraint; every
reduction below is stated with the reason it does not change what the
probe discriminates.

| Item | Brief | Run | Why |
|------|-------|-----|-----|
| Livelock fuzz (`t7`) | ≥500 configs | **510** (3 shards × 170, seeds 10101/10102/10103) | Each shard fits the 120 s script bound; the union is the ≥500 asked for. Both kinds × both engines, unreduced. **0 hangs, 0 unobservable trips, 0 lap-parity gaps** in all three. |
| Fuzz watchdog | 30 s | **3 s** + 0.12 s settle | Unchanged rationale from rounds 8/9: every livelock in this family hangs indefinitely, so 3 s discriminates identically. |
| Property (`t10`) | ≥300 machines | **300**, unreduced | Parallel + nested + `after` + invoked leaves, both kinds. 600 snapshots, **0** violations. |
| Determinism (`t9`) | 50 runs, hash-seed | **50** per cell, 9 cells (450 runs) + 3 `PYTHONHASHSEED` children | Unreduced. |
| Stranded-hook storm (`t3`) | 200 concurrent | **50 per kind** (100 machines) | The exactly-once / correct-ids invariants are **per machine** and scale-free; 100 machines already returned a unanimous result (§4, D10-2). |
| Self-ping-pong (`t5`) | 100 machines | **100 per kind**, unreduced | 200 machines total, lap histogram a single bucket. |
| Receipt matrix (`t8`) | 6-way fuzz | **40 reps × 12 cells** = 480 receipts | Unreduced. |
| Soak | 12 min | **NOT RUN** | The whole-task bound was consumed by reproducing and minimising D10-1/D10-2. Recorded in §6 as the single largest coverage gap; round 9's 150 s soak at `f28719c` is the most recent evidence and it predates these fixes. |
| External sends at 5 k/s under chain | 5 000/s | **NOT RUN separately** | `r5` / `s4` re-ran clean (§2); the rate-independent invariant (0 external shed as `chain_budget`) held. Flagged in §6. |

### 1.1 Scripts whose exit code is not a verdict

`r1`, `r2`, `r2c`, `r4`, `r6b` exit 1 at `19cb1f1`. All five encode the
**documented** D8-concurrency-2 / #193 contract (a plain `def` service
blocks the run loop, and is therefore not pre-emptible). Round 9 already
reclassified this as a stated contract rather than a defect; the exit
codes are unchanged for that reason and are **not** counted here. `t6`'s
`def` lane is the same story (§3).

### 1.2 Commands

```
PY=…/_ref/xstate-statemachine/.venv-main/Scripts/python
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1      # from cwd <home>

# round-9 corpus, copied forward unmodified
$PY battle-19cb1f1/concurrency/s6_restore_event_forgery_minimal.py
$PY battle-19cb1f1/concurrency/s1_engine_marker_persistence.py
$PY battle-19cb1f1/concurrency/s5_snapshot_engine_forgery.py
$PY battle-19cb1f1/concurrency/r7_engine_marker_forgery.py
$PY battle-19cb1f1/concurrency/r9_observability_matrix.py --only=qf
$PY battle-19cb1f1/concurrency/s3_eventless_selection_matrix.py
$PY battle-19cb1f1/concurrency/s4_priority_provenance_roundtrip.py
#  … r1 r2 r2c r3b r4 r5 r6b r8b r8c s2 s7 c1 e1 e2 g1 h1 h2 r11

# new attacks (standalone, both service kinds throughout)
$PY …/t1_after_provenance_forgery.py
$PY …/t2_states_to_invoke_matrix.py
$PY …/t3_stranded_hook_storm.py   ;  $PY …/t3b_stranded_minimal.py
$PY …/t4_self_target_ondone_never_rearms.py
$PY …/t5_delayed_self_send_debt.py
$PY …/t6_arming_window_snapshot.py
$PY …/t7_livelock_fuzz_round10.py --n=170 --seed=10101 --tag=s10101   # ×3
$PY …/t8_receipt_matrix.py --reps=40
$PY …/t9_determinism_hashseed.py --runs=50
$PY …/t10_property_parallel_children.py --n=300
```

---

## 2. Prior defects — FIXED / STILL-PRESENT / CHANGED

| Prior ID | Sev (r9) | Probe re-run | Verdict @ `19cb1f1` |
|----------|----------|--------------|---------------------|
| **D9-concurrency-1** — `restore_event` mints a trusted engine completion from any dict carrying `"engine": true` | **High** | `s6`, `s1`, `s5`, `r7` | **STILL-PRESENT**, unchanged in mechanism → re-filed **D10-concurrency-3** |
| **D9-concurrency-2** — call-site `QueueOverflowError` refusals fire no hook | Low | `r9 --only=qf` | **STILL-PRESENT**, unchanged → re-filed **D10-concurrency-4** |
| **D8-concurrency-2** — a plain `def` service blocks the run loop | (documented) | `r1`, `r2`, `r2c`, `r5` | **UNCHANGED, still the stated contract** — not a defect (§1.1) |
| **D8-concurrency-3** — `children_timeout` | (fixed r9) | `r6b`, `s2` | **HOLDS** (bound + WARNING); `def` non-pre-emptibility remains documented |
| **D8-concurrency-4** — torn blob from `on_interpreter_start` | (fixed r9) | `r3b` | **HOLDS** — PASS |
| **D8-concurrency-1** — action-issued priority never charged | (fixed r9) | `r8b`, `r5`, `s4` | **HOLDS** — all three PASS |

`s6` at `19cb1f1` is byte-for-byte the round-9 failure: the forged
`engine: true` completion is `is_system_event: true`, `send()` returns
ACCEPTED, the machine moves `s6.work → s6.done`, `onDone` runs with
`{"v": "FORGED"}` and the genuine `{"v": "GENUINE"}` result is
discarded — while the unflagged control in the same cell is
`refused:UnknownEventError`. `r7` still reports
`F5_forged_with_real_marker_is_system: true` on **both** kinds.

### 2.1 Round-9 fixes independently re-verified

| Fix | Probe | Result |
|-----|-------|--------|
| **#203** `after` matches only engine-minted `AfterEvent` | `t1` | **DEFEATED** — 8/8 forged cells fire a 60 s timer instantly → **D10-concurrency-1** |
| **#204** SCXML §6.1 `statesToInvoke` | `t2`, `t6` | **HOLDS for the four-way matrix** — roll-forward 0 submits, rollback 0 submits, stay 1, parallel-sibling-final 1, in **12/12** supported cells, 0 engine-parity gaps. The arming window is sound: 40/40 snapshot restores arm **exactly once**. **But** the entry-only recording has a hole → **D10-concurrency-2** |
| **#206** delayed self-send is engine work | `t5` | **HOLDS, strongly** — zero-delay cycle trips at lap 13, the 1 ms delayed cycle at lap 12 (within the stated ±1), both kinds; **100/100** concurrent ping-pong machines per kind trip, lap histogram a **single bucket (12)** for all 200 |
| **#207** stranded invocation observable | `t3`, `t3b` | **HOLDS on the shape it pins; does not generalise** — the pinned `rollback + onDone` chart fires the hook, but the self-target chart wedges silently (D10-2). `RunawayChainError.stranded` payload and message are correct. |
| **#208** receipt never ok over illegal/empty | `t8` | **HOLDS** — **480 receipts, 0 violations**; every receipt's `state_ids` equalled the live configuration |
| **#209** lap parity | `t7` (510 configs), `t9` | **HOLDS** — **0** async/sync lap-parity gaps across 510 fuzz configs |
| **#210** convergence, not fixed sampling | `t9` | **HOLDS** — 1 distinct trace per cell over 50 runs × 9 cells |
| **#198 / #185** snapshot guards, hash drift | `r4`, `s5`, `t6` | **HOLDS** — `t6` reproduced `SnapshotDriftError` on a structure change, and `s5` is 10/10 |
| **#196** `always` only in the settle pass | `s3` | **HOLDS** — 18/18 depth-matrix cells, 0 parity gaps |
| **#190** wildcard vs strict | `r11` | **HOLDS** — PASS |

---

## 3. New attacks (`t1`–`t10`) — what each one found

| # | Attack | Result |
|---|--------|--------|
| **t1** | #203 provenance: forge `_EngineAfter` by import path / `type(held)` / `pickle` / `restore_event` `"engine": true`, × both engines, against a **60 000 ms** timer | **FAIL 8/8.** Every vector yields `is_system_event: true`, `send()` ACCEPTED, machine in `t1.late`, the timer action ran — in 0.2 s. Control (`AfterEvent`, the public class) `refused:UnknownEventError` in every cell. → **D10-concurrency-1** |
| **t2** | #204 `statesToInvoke` 4-way matrix (roll-forward / stay / parallel-sibling-final / rollback) × 2 kinds × 2 engines | **PASS 12/12** supported cells, **0 engine-parity gaps**. The 2 unsupported cells are `SyncInterpreter` + `async def` → documented `NotSupportedError`. #204 does what it says on this matrix. |
| **t3** | #207 exactly-once stranded hook under 100 concurrent `rollback + onDone` storm machines | **FAIL 100/100** — but the mechanism was **not** the one hypothesised; minimised in `t3b`/`t4` and filed as D10-2 rather than as a hook-counting bug. `RunawayChainError.stranded` and its message are correct. |
| **t3b** | Minimal: one machine, both kinds, both engines | **FAIL 3/3** supported cells — `dormant == True`, `pending_invocations()` correctly names `('t3b.work', 'spin')`, and yet `on_invocation_stranded` is silent, 0 `on_event_dropped`, 0 ERROR logs, `last_error` `None`. |
| **t4** | The discriminating experiment: SELF (`onDone → work`, its own source) vs HOP (`onDone → hop --always--> work`) vs a CLEAN control | **FAIL, and it isolates the cause.** HOP: 11 entries, 11 submits, `RunawayChainError`, `dormant False`. SELF: **1** entry, **1** submit, `dormant True`, no error, no hook. CLEAN control: `dormant False` as required. → **D10-concurrency-2** |
| **t5** | #206: zero-delay vs 1 ms delayed `raise` ping-pong; then 100 concurrent 1 ms machines per kind | **PASS.** Laps 13 vs 12 (±1 as stated); 200/200 machines tripped with a **single** lap value. |
| **t6** | #204's new arming window: snapshot a machine whose invoke is entered-but-not-yet-armed, restore, count submits; ×40 | **PASS on the async lane** — static restore reports `dormant True` and names the pending invoke, 0 submits; `restart_services=True` + `start()` submits **exactly 1**, 40/40. The `def` lane's snapshot lands after completion because the service blocks the loop (§1.1) — coverage note, §6. |
| **t7** | Livelock fuzz, 510 configs × 2 kinds × 2 engines, 6 shapes incl. always+invoke+after in one chart and delayed raises | **PASS ×3 shards.** 0 hangs, 0 unobservable chain trips, **0 lap-parity gaps**. |
| **t8** | Receipt 6-way matrix, 40 reps × 12 cells | **PASS 480/480.** Never `ok` over an illegal step or empty configuration, never error-shaped over a legal one, and `receipt.state_ids` always equalled the live configuration. |
| **t9** | Determinism: 50 identical runs × 9 cells (both engines, both kinds, incl. the stranding shape), re-exec under 3 `PYTHONHASHSEED`s | **PASS.** 450 runs, **1** distinct trace per cell, identical digests across seeds 0 / 1 / 12345. |
| **t10** | Property: 300 random machines (parallel 111 / nested 94 / flat 95) × 2 kinds — no hang, no empty config while running, `dormant` ⇔ `pending_invocations()`, snapshot round-trip | **PASS 600/600.** 0 violations, 600 snapshots all accepted, every static restore reproduced the configuration with 0 submits. |

---

## 4. Defect register — `D10-concurrency-n`

### D10-concurrency-1 — #203's `after` provenance guard is type identity against a plain subclass; four independent vectors fire a 60-second timer instantly, on both engines

**Severity: High.** Repro: `t1_after_provenance_forgery.py` (exit 1),
artefact `t1_after_provenance_forgery.json`.

#203 fixed #195's gap for `after` by requiring that only an
engine-minted `AfterEvent` may drive an `after` transition. The check is
`isinstance(ev, _ENGINE_MINTED_TYPES)` — **type identity** — and
`_EngineAfter` is a bare subclass with no unforgeable state:

```
events.py:579   class _EngineAfter(AfterEvent):  __slots__ = ()
events.py:588   _ENGINE_MINTED_TYPES = (_EngineDone, _EngineError, _EngineAfter)
events.py:610   return _EngineAfter(type, scheduled_for, fired_at)   # engine_after()
events.py:414   trusted = record.get("engine") is True               # restore_event()
```

A type is not a capability. All four routes produce an object that
satisfies the check:

| Vector | How | `is_system_event` | Result |
|--------|-----|-------------------|--------|
| V1 import path | `events._EngineAfter("after.60000.t1.wait")` | `true` | fires |
| V2 `type(held)` | `type(events.engine_after(t))(t)` | `true` | fires |
| V3 pickle | `pickle.loads(pickle.dumps(engine_after(t)))` | `true` | fires |
| V4 snapshot record | `restore_event({"kind":"after","type":t,"engine":True})` | `true` | fires |
| **CONTROL** | the public `AfterEvent(t)` | `false` | **`refused:UnknownEventError`** |

The machine declares `after: {60000: {target: "late", actions:["boom"]}}`.
In every one of the **8** forged cells (4 vectors × `Interpreter` and
`SyncInterpreter`) `send()` returns ACCEPTED, `boom` runs, and the
configuration is `["t1.late"]` — within the 0.2 s the probe waits, i.e.
a sixty-second business timeout fired **instantly**. The control proves
the guard is live and correctly refuses the public class; it simply does
not distinguish "the engine minted this in this process" from "someone
constructed this type".

Why it matters for an OMS: `after` is where order-expiry, quote-staleness
and reconnect-backoff timers live. Any code path that can hand the
interpreter an event — a snapshot loaded from storage (V4), a replay
harness, a plugin, a test double kept in production code — can retire a
timer that has not elapsed.

Note V4 is reachable **without importing a private name**:
`restore_event` is on the public `xstate_statemachine.events` module and
the payload is a plain dict. V1/V2/V3 need `_EngineAfter` only as a
type, which `type()` and `pickle` hand over for free from any genuine
event the process has already seen.

A type-identity check cannot be repaired by hiding the name. The mark has
to be process-scoped and unguessable — the same conclusion round 9 drew
for `_EngineDone` (D9-1 / D10-3), which is still open. **D10-1 and D10-3
are one fix.**

### D10-concurrency-2 — `onDone` targeting its own source state never re-arms the invoke; the machine parks silently with a dormant invocation, no hook and no error

**Severity: High.** Repro: `t4_self_target_ondone_never_rearms.py`
(exit 1), storm `t3_stranded_hook_storm.py`, minimal
`t3b_stranded_minimal.py`.

#204 moved invoke arming to the end of the eventless settle pass, and
records the states to arm at **entry**:

```
base_interpreter.py:4952   self._states_to_invoke.append(state)     # from ENTRY only
base_interpreter.py:4958   _arm_pending_invokes(): pending, self._states_to_invoke = …, []
base_interpreter.py:3898   removed from _states_to_invoke on EXIT
```

Under SCXML §3.12 a transition **with a target** exits and re-enters its
source even when source and target are the same state, so `onDone:
{target: "work"}` from inside `work` is an exit + re-entry and must
re-record and re-arm. It does not. The state never exits, so it is never
re-appended, and `_arm_pending_invokes` has nothing to arm.

`t4` runs the two semantically identical loops side by side at
`maxIterations: 20`:

| shape | engine | kind | entries | submits | `dormant` | `last_error` |
|-------|--------|------|---------|---------|-----------|--------------|
| **SELF** `onDone → work` | async | `def` | **1** | **1** | **true** | `None` |
| **SELF** | sync | `def` | **1** | **1** | **true** | `None` |
| **SELF** | async | `async def` | **1** | **1** | **true** | `None` |
| HOP `onDone → hop --always--> work` | async | `def` | 11 | 11 | false | `RunawayChainError` |
| HOP | sync | `def` | 11 | 11 | false | `RunawayChainError` |
| HOP | async | `async def` | 11 | 11 | false | `RunawayChainError` |
| CLEAN control `onDone → rest` | all | both | 1 | 1 | **false** | `None` |

Adding one pass-through state turns a machine that runs its service once
and freezes into one that cycles 11 times and trips the budget correctly.
That is the whole difference.

The resulting state is exactly the one #207 was opened to make
observable, and #207 does **not** see it:

* `has_dormant_invocations == True`
* `pending_invocations() == [PendingInvocation(state_id='…work', invoke_id='spin', src='svc')]`
* `on_invocation_stranded` — **never fires**
* `on_event_dropped` — **0 calls**
* ERROR log — **none**
* `last_error` — **`None`**
* `status` — **`"running"`**

`t3b` confirms this on all 3 supported engine×kind cells; `t3` confirms
it on 100 concurrent machines (histogram: `n_stranded == 0` for 100/100,
`dormant == True` for 100/100). `_stranded_by_cut`
(`base_interpreter.py:1921`) only inspects events that were **cut by the
chain budget**; here nothing is cut, because nothing is generated. The
detection is attached to the wrong event.

An OMS health check that follows the documented advice — "`status` is not
a liveness signal after a restore; check `has_dormant_invocations`" —
*would* catch this, because that flag is correct. But a machine that
never restores and never trips has no reason to be polled, and the two
push signals (`last_error`, `on_invocation_stranded`) both stay silent.
A fill-handling state whose `onDone` loops back on itself to poll the
exchange stops after the first poll, with no error anywhere.

Two things are wrong and either fix alone is incomplete:
1. **Semantics** — a self-targeting transition with a target must exit
   and re-enter, so `_states_to_invoke` is re-recorded (the real fix).
2. **Observability** — `has_dormant_invocations` becoming true on a
   *running, never-restored* machine should push, not only answer when
   asked.

### D10-concurrency-3 — `restore_event` still mints a trusted engine completion from any dict carrying `"engine": true`

**Severity: High.** Unchanged from **D9-concurrency-1**; re-verified by
`s6` (FAIL), `s1` (FAIL), `r7` (FAIL, both kinds). Mechanism, evidence
and impact are as filed in `53-r9-findings-register.md` (R9-01) — the
forged completion is `is_system_event: true`, `send()` returns ACCEPTED,
`onDone` runs with the forged payload past `strict`, and the genuine
in-flight result is discarded. `s5` remains PASS: the snapshot **file**
is not the exploitable route, the in-process one is.

Same root cause as D10-1. One fix closes both.

### D10-concurrency-4 — call-site `QueueOverflowError` refusals still fire no `on_event_dropped`

**Severity: Low.** Unchanged from **D9-concurrency-2** /
D8-concurrency-5 / D7-concurrency-3. `r9_observability_matrix.py
--only=qf` at `19cb1f1`: **241 414** call-site refusals vs **1 811**
loop-side refusals; `queue_full_hooks == 1811`,
`loopside_hooked_exactly_once: true`, `callsite_hooked: false`. So
**99.3 %** of shed events were invisible to the hook this run. Load-shed
dashboards built on `on_event_dropped` under-report by two orders of
magnitude.

---

## 5. Contract notes — observed, deliberately NOT counted as defects

1. **A plain `def` service blocks the run loop.** Re-confirmed by `r1`,
   `r2`, `r2c`, `r6b`, `r4` (all exit 1) and by `t2`/`t6`'s `def` lane.
   Documented at #193 / Production Characteristics §2 since round 8. It
   *is* the reason `t6`'s `def` lane could not sample the arming window
   (the service completes before the caller can snapshot), and the reason
   `t3b`'s sync + `async def` cell raises `NotSupportedError`.
2. **`SyncInterpreter` refuses `async def` services** —
   `NotSupportedError: Service 'svc' is async and not supported.` Seen in
   `t2` (2 cells), `t3b` (1 cell), `t4` (3 cells). Correct and explicit;
   it is why lap parity in `t7` is measured on the `def` lane.
3. **An `after`-timer loop is not bounded by `maxIterations`.** In `t7`,
   `after_loop` charts run past `limit + 3` laps with no
   `RunawayChainError` and no `chain_budget` drop. This is *right*: an
   `after` loop is paced by real wall-clock time, so it is not
   self-generated work and the chain budget is not the bound that applies.
   `t7` excludes the three timer-paced shapes from invariant I2 for this
   reason, and states so in its docstring. Worth a documentation sentence:
   the only bound on an `after` cycle is the delay itself.
4. **A receipt is not a liveness signal.** `t8`'s R6 cell sends the event
   that enters a runaway chain; the receipt resolves `error is None` over
   `["r.spin"]`, which is the legal configuration at the instant **that
   event's** macrostep ended. The chain trips several laps later and
   surfaces on `last_error`, not on a receipt already handed back. This is
   consistent with the #208 contract as written ("the receipt tells the
   CALLER its request did not run cleanly"), and `t8` scores the cell on
   that evidence rather than on the assumption. Callers must not read
   receipt success as "the machine is healthy".
5. **`restart_services=True` is consumed by `start()`**, not by
   `from_snapshot()` (`base_interpreter.py:1867` → `interpreter.py:560`).
   A restored interpreter that is never started re-arms nothing and
   reports `dormant True` forever. Correct and documented, but it is a
   sharp edge: `t6` initially measured 0 submits for exactly this reason.
6. **`Interpreter.from_snapshot` is synchronous** and takes the JSON
   **string** form; `get_persisted_snapshot()` returns a dict on this
   build. Probes must bridge the two. Not a defect, but the asymmetry cost
   two probe iterations.

---

## 6. Coverage — what was NOT covered this run

Stated plainly, because these are the places a defect could still be
hiding.

| Gap | Why | Risk carried |
|-----|-----|--------------|
| **The 12-minute soak** (200 machines, mixed shapes, chaos snapshot at quiescence, CPU bound, 0 dropped external) | **NOT RUN.** The whole-task bound went on reproducing and minimising D10-1/D10-2. | **Highest single gap.** The most recent soak evidence is round 9's 150 s run at `f28719c`, which **predates** #203–#210 entirely. Leak, CPU-growth and long-run drift behaviour of the new arming path is **unmeasured**. |
| **External delayed sends at 5 000/s during a self-generated chain** | Not run as a dedicated probe. `r5` and `s4` re-ran **PASS** (0 external events shed as `chain_budget`, incl. after a snapshot round-trip), and that invariant is rate-independent. | Low–medium. Round 9 measured the achievable rate as host-limited to ~450–1 000/s from one producer thread, so 5 k/s was not reachable there either. |
| **`on_invocation_stranded` ordering vs `on_event_dropped`** | `t3` records the interleaving, but D10-2 means the stranded hook never fired in the shape under test, so the ordering was never exercised. | Medium — untested on the one shape where both hooks fire (`t3`'s pinned `rollback + onDone` chart does fire both in the library's own test). |
| **History states in the `statesToInvoke` matrix** | `t2` covers roll-forward, rollback, stay and parallel-sibling-final; `history` was cut for time. | Medium. Given D10-2 is an entry/exit-recording bug, `history` re-entry is a plausible second instance of the same fault and should be probed first next round. |
| **Redaction / secret-leak surface** | Not re-run this round beyond `r7`'s existing checks (`secret_in_interpreter_repr: false`, `str: false`, **`secret_in_snapshot: true`**). | Low for concurrency; the snapshot leak is a persistence-track finding. |
| **`def`-lane arming window** (`t6` W1/W3) | Unsampleable: the blocking `def` service completes before the caller can snapshot (§5.1). | Low — the async lane is 40/40 exactly-once, and the arming code is shared. |
| **Free-threading build** | `h1`/`h2` re-ran PASS on the GIL build only. | Low, unchanged from round 9. |

---

## 7. Verdict

**ADOPT WITH CONSTRAINTS — constraints tightened.**

The engine's *core* concurrency behaviour at `19cb1f1` is, on the
evidence gathered here, good and getting better: 510 fuzz configs with
zero hangs, zero unobservable chain trips and zero lap-parity gaps; 300
random parallel/nested/timer machines with zero property violations; 450
determinism runs collapsing to one trace per cell across three hash
seeds; 480 receipts with zero contract violations; and #206's delayed
self-send accounting holding across 200 concurrent machines with a
single-bucket lap histogram. #209's parity claim and #210's convergence
claim both verified independently. That is a materially stronger result
than round 9 produced.

What blocks unconstrained adoption is that **two of the four round-9
fixes examined here re-derive, at use time, a property the engine already
knew at mint/entry time** — and get it wrong:

* #203 knew the engine minted the `after` event, then re-derived it from
  the event's Python *type*, which anyone can reproduce (D10-1).
* #204 knew which states to arm at entry, then relied on state entry
  recurring — which a self-targeting transition never triggers (D10-2).

Both are High. D10-1 is a trust-boundary failure on the same footing as
the still-open D10-3, and the two share a single fix: replace type
identity with a process-scoped, unguessable mark. D10-2 is a correctness
failure with a silence problem attached — the machine wedges, and all
three push-based signals (`last_error`, `on_invocation_stranded`, the
ERROR log) stay quiet while `has_dormant_invocations` correctly says
otherwise to anyone who thinks to ask.

Constraints to carry forward (extending CV-C01..C46):

* **CV-C47** — Do not rely on `after` provenance as a security boundary.
  Treat any event-accepting surface (snapshot restore, replay, plugins)
  as able to fire any `after` transition. Supersedes nothing; extends the
  existing `_EngineDone` constraint to `_EngineAfter`.
* **CV-C48** — **Ban self-targeting `onDone`/`onError` in project
  charts.** Route every service-retry loop through an explicit
  intermediate state. Add a lint over `docs/plan/28-statechart-catalogue.md`
  to enforce it; the failure mode is silent.
* **CV-C49** — Health checks must poll `has_dormant_invocations` on
  **running, never-restored** machines too, not only after a restore.
  The documented guidance currently frames it as a post-restore signal.
* **CV-C50** — Load-shed metrics must be taken from `send()` call-site
  return values / exceptions, **not** from `on_event_dropped`, which
  under-counts by ~99 % (D10-4). Unchanged from round 9, re-confirmed.

The shim-retirement schedule in `54-r9-final-readiness-verdict.md` should
**not** advance for the `after`-provenance or invoke-arming shims until
D10-1 and D10-2 are fixed and re-verified with `t1` and `t4`. The
remaining phases are unaffected by this round's findings.

The single most valuable thing next round is the **12-minute soak** (§6),
which has not been run against this commit at all, followed by a
`history`-state extension of the `t2` matrix — D10-2's shape makes
`history` re-entry the most likely place for a second instance of the
same fault.
