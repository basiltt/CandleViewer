# 43 — Round-7 findings register (triaged, deduped, canonical)

**Library under test:** `xstate-statemachine` @ `221ce7c` (unreleased 0.8.1;
`__version__` still reports `0.8.0` — key on the commit, not the version).
**Method:** every input finding was re-triaged by (a) re-running its repro
fresh against `221ce7c` under a 120 s cap, or (b) reading the cited source
lines where the repro is a carried contract-level artefact, then classified
and merged by root cause.

**Classification key**

| Class | Meaning |
|---|---|
| `LIBRARY-DEFECT` | Defect in library source; library must change. |
| `DESIGN-CONSTRAINT` | Library behaves as designed/documented; a wrapper must absorb it. |
| `OUR-CONTRACT-DEFECT` | Defect in our catalogue JSON; engine is faithful. |
| `HARNESS-ERROR` | Defect in our probe/gate harness. |
| `DUPLICATE` | Same root cause as a canonical `R7-nn`. |

## Verdict summary

| ID | Severity (OMS) | Class | Title |
|---|---|---|---|
| **R7-01** | **Blocker** | LIBRARY-DEFECT | `async def` service completions bypass the charged lane: every self-generated invoke/rollback cycle is unbounded, and one variant settles into an **empty configuration** reported as success |
| **R7-02** | **Blocker** | LIBRARY-DEFECT | External `send(priority=True)` is charged to the chain budget: 61% of legitimate external sends silently dropped as `chain_budget` |
| **R7-03** | **Blocker** | LIBRARY-DEFECT | `await start()` hangs unboundedly on a slow invoked child (#171), `status` reads `running` throughout |
| **R7-04** | High | LIBRARY-DEFECT | External traffic renews the per-macrostep settle budget mid-chain; an invoke cycle under sustained traffic never drains its inbox |
| **R7-05** | High | LIBRARY-DEFECT | Async `start()` never sets the in-flight flag, so #169's entry-window snapshot refusal is inert during initial entry |
| **R7-06** | High | LIBRARY-DEFECT | `machine_hash` set to `None` or removed silently disables `from_snapshot()` drift verification |
| **R7-07** | High | LIBRARY-DEFECT | A root snapshot harvests a child actor's half-applied context (torn blob one level down) |
| **R7-08** | High | LIBRARY-DEFECT | `_await_settled_for_snapshot` spins `time.sleep` on the event-loop thread, so the child it waits for cannot progress |
| **R7-09** | Medium | LIBRARY-DEFECT | A contradictory `configuration` key outranks `state_ids` on restore |
| **R7-10** | Medium | LIBRARY-DEFECT | `get_persisted_snapshot()` from `on_action_execute` returns a torn blob on async; sync refuses |
| **R7-11** | Medium | LIBRARY-DEFECT | Sync `_deferred_this_step` never cleared on `wait=False` — unbounded growth |
| **R7-12** | Medium | LIBRARY-DEFECT | `onUnhandled:"error"` fatal kill is invisible to the sender (success-shaped `Receipt`) |
| **R7-13** | Medium | LIBRARY-DEFECT | Config-level `strict:true` does not gate event names; a `"*"` handler makes `is_known_event()` true for anything |
| **R7-14** | Low | LIBRARY-DEFECT | Call-site `QueueOverflowError` refusals fire no `on_event_dropped` hook (~50% under-count) |
| **R7-15** | Low | LIBRARY-DEFECT | `last_error` is set *after* the drop hooks and cleared by the next success |
| **R7-16** | Low | LIBRARY-DEFECT | `DEFAULT_SERVICE_POOL_SIZE` documented but absent from `__all__` |
| **R7-17** | Low | LIBRARY-DEFECT | `spawnBlockingTimeout` validated then dropped; no attribute on the built machine |
| **R7-18** | Low | LIBRARY-DEFECT | Unknown top-level config keys accepted silently (typo = silent downgrade to default) |
| **R7-19** | Low | LIBRARY-DEFECT | `get_persisted_snapshot()` returns a dict; `from_snapshot()` refuses a dict |
| **R7-20** | Low | LIBRARY-DEFECT | Sync/async lap-count asymmetry inside the *fixed* plain-`def` path |

Non-library outcomes are in §3 (`DESIGN-CONSTRAINT`), §4 (`OUR-CONTRACT-DEFECT`),
§5 (`HARNESS-ERROR`), §6 (confirmed-fixed / passes).

**Adoption impact:** three Blockers, all on the async engine, all silent
(`status == "running"`, `last_error is None`). R7-01 and R7-02 are
silent-data-loss classes on the order path. The adoption gate must stay down.

---

## 1. Canonical LIBRARY-DEFECTs

### R7-01 — `async def` service completions are never charged; self-generated cycles are unbounded, and one variant settles EMPTY — **Blocker**

**Merges:** `D7-fuzz-1`, `D7-fuzz-2`, `C221-01`, `LD-04`, `CV-221-01`,
`LIB-R6-01`, and the async half of `attack-K`. Six independently-filed
findings, one line of source.

**Root cause (verified this round by direct lane instrumentation).** Two
different publication paths exist for a service completion:

| Service kind | Path | Charged? |
|---|---|---|
| plain `def` | `_finish_plain_service` → `self._deliver_priority(done_event)` (`interpreter.py:2690`) | **yes** — `_deliver_priority` (`interpreter.py:2287-2288`) does `if self._processing: self._raise_depth += 1` |
| `async def` | `_invoke_service_task` → `await self.send(done_event)` (`interpreter.py:2414`); child-actor `onDone` likewise at `:2882` | **no** — never reaches `_deliver_priority` at all |

Fresh probe (`/tmp/lane.py`, counts `done.invoke*` per lane, ping-pong
`a↔b`, `maxIterations: 20`, 2 s):

```
{"kind": "plain", "lanes": {"priority": 23, "inbox": 0},    "raise_depth": 0, "last_error": "RunawayChainError"}
{"kind": "async", "lanes": {"priority": 0,  "inbox": 27948}, "raise_depth": 0, "last_error": null}
```

This **refutes the two competing explanations on file** and supersedes both:
it is not the `is_system_event` exemption (`LD-03`, already withdrawn), and it
is not merely that `self._processing` is `False` when the task resolves
(`D7-fuzz-1`, `LD-04`, `CV-221-01`). The coroutine completion is published on
the **public inbox lane** and so never passes the charging site under any
value of `_processing`. `CV-221-01`'s secondary observation is also confirmed
correct and compounding: arriving from the inbox, the completion additionally
satisfies the `from_inbox` disjunct at `interpreter.py:1647`
(`if not is_system_event(event) or from_inbox:`) and **resets**
`_settle_iterations` / `_settle_tripped` on every lap of the chain. So the
coroutine path is both uncharged and actively budget-clearing.

**Reproduced fresh (all 120 s cap):**

- `fuzz/q1_async_invoke_runaway.py` — `maxIterations=20`, invoke ping-pong:
  `sync plain svc laps=22 last_error=RunawayChainError`;
  `async engine plain def svc laps=22 → bounded`;
  `async engine async def svc laps=70159 in 5s, last_error=None, ok=True → RUNAWAY`.
- `fuzz/q14_torn_repro.py` — the silent-loss variant. With an `async def`
  service, **10/10**: a resolved `await send("GO", wait=True)` returns
  `ok=True, err=None, status=running` with `current_state_ids == []`, still
  empty 500 ms later. With a `plain def` service, **0/10** (trips
  `RunawayChainError` correctly). Sync engine keeps a legal config on the
  identical chart. A snapshot at the torn instant is refused
  `SnapshotMidStepError` — the interpreter knows it is mid-step while
  `send(wait=True)` reports the step finished successfully.
- `contracts/repro/g4_budget_timing_dependent.py` — same machine,
  `maxIterations=50`: plain `def` trips at 52 laps; `async def` runs
  ~21k laps in 2 s, `tripped=false`, `max_raise_depth=0`.
- **New ablation this round** (`/tmp/rb.py`) proves `LIB-R6-01` /
  `CV-221-01` (rollback + raising entry behind `invoke.onDone`) is the
  *same* defect, not a separate uncovered family:
  ```
  {"kind": "plain", "svc_calls": 23,   "last_error": "RunawayChainError"}
  {"kind": "async", "svc_calls": 2783, "last_error": "RuntimeError"}
  ```
  One word changed. The plain path is bounded by the round-6 fix; the
  coroutine path is unbounded. `LIB-R6-01` is therefore **merged, not
  separate**.

**Why the library's suite misses it.** All three pinned regression tests in
`tests/test_round6_findings.py` (`TestAsyncRollbackRearmCycleBounded`,
`TestAsyncInvokeCycleTrips`, and the #166 case) declare `def svc(...)`. The
fix is tested on the one path that was already working, while #174's own
guidance tells users to prefer `async def` for services that must not block
timers — so the documented-correct choice is the unprotected one. This
directly contradicts the CHANGELOG claims that "every self-generated cycle is
bounded on `Interpreter`" and "the invoke cycle now trips at the same lap
count on both engines".

**OMS severity: Blocker.** Unbounded hot-spin at ~500–14,000 laps/s with
`status == "running"` and `last_error is None` is undetectable by any
liveness check we would ship; and the `q14` variant is silent order loss —
the machine acknowledges an event, drops its configuration, and silently
discards every subsequent event.

**Fix direction.** Publish engine-generated completions on the guarded lane
(`_deliver_priority`) from `_invoke_service_task` and the child-actor
`onDone` path, **and** exclude system events from the `from_inbox` reset at
`interpreter.py:1647`. Both halves are required: the first restores charging,
the second stops the reset. Add a regression test matrix that runs every
round-6 cycle test with *both* a `def` and an `async def` service.

---

### R7-02 — external `send(priority=True)` is charged to the chain budget — **Blocker**

**Source:** `L-1`. `interpreter.py:2287-2288`, reached from the public
`send(..., priority=True)` at `interpreter.py:811-812`.

**Root cause.** `_deliver_priority` decides provenance by **when** the event
lands (`if self._processing`), not by **who** issued it. `send(priority=True)`
is public external API and routes straight into that method. Any producer
faster than the loop — the only regime where backpressure matters — has its
legitimate external events counted as machine-self-generated and cut at
`max_iterations`.

**Reproduced fresh** (`probes/main-221ce7c/p1_priority_lane_charged.py`):
3,000 external `send("PING", priority=True)` from a producer coroutine
against a single-state machine with one counting action, no `raise`, no
self-send, no cycle:

```
sent=3000 processed=1162
dropped=1838 reasons={'chain_budget'}
_raise_depth=0 tripped=False
last_error=NoneType
VERDICT: EXTERNAL PRIORITY SENDS DROPPED AS SELF-GENERATED
```

**61% silent loss.** The drop path's recovery clause then resets
`_raise_depth = 0` and `_chain_tripped = False` once the lanes empty, so a
caller polling `last_error` afterwards sees `None`: the loss is observable
*only* via `on_event_dropped`.

This is precisely the failure the run loop's own architecture note says the
design exists to prevent ("cannot tell a runaway `raise` from a merely busy
producer — 5,000 legitimate concurrent `send()` calls lost 3,999 of them").

**OMS severity: Blocker.** Priority send is the natural expression of "this
order-path event jumps the queue"; dropping 61% of them, silently, under
exactly the load where it matters, is unshippable.

**Fix direction.** Decide provenance the way `send()` already does —
`_issued_from_own_action()`, or an explicit `internal=` flag carried by the
caller — not by `_processing`. Priority deliveries from `_after_timer._fire`,
`_finish_plain_service` and `_deliver` are engine work; `send(priority=True)`
from user code is not.

---

### R7-03 — `await start()` hangs unboundedly on a slow invoked child — **Blocker**

**Source:** `L-2`. `interpreter.py:561` and `_await_actor_bringups`
(`interpreter.py:~2586`).

**Root cause.** #171 made `start()` await invoked-child bring-up via
`await asyncio.gather(*pending, return_exceptions=True)` with **no timeout**.
The bring-up coroutine awaits `child.start()`, which runs the child's entry
actions. The CHANGELOG calls bring-up "transient (microseconds)" — true of
the engine's own work, not of a user entry action the child's initial state
declares. Before #171 `start()` returned regardless. The `while` loop
compounds it: a bring-up that itself enters an invoking state appends more
tasks, so the wait spans the transitive closure of children.

**Reproduced fresh** (`probes/main-221ce7c/p2_start_awaits_child_bringup.py`):

```
start() still not returned after 8s (child entry sleeps 30s)
status=running
VERDICT: START() HANGS ON A SLOW INVOKED CHILD (no timeout)
```

`status` reads `"running"` throughout, so a health check sees a live machine
while `start()` has not returned and no event has ever been read. The
`except Exception` recovery in `start()` never runs — nothing raised.

**OMS severity: Blocker.** A slow dependency at startup (a lock, a socket, a
connection pool) becomes an indefinite hang that reports healthy. This is a
**round-7 regression**, not a pre-existing limitation.

**Fix direction.** Bound the wait with `asyncio.wait_for` on a documented
startup timeout and surface the timeout, or await only registration in
`_actors` rather than the child's full `start()`.

---

### R7-04 — external traffic renews the settle budget mid-chain; an invoke cycle never drains its inbox — High

**Merges:** `L-4` and `D7-concurrency-1` (same line, two symptoms).

**Root cause.** `interpreter.py:1646-1652`:
`if not is_system_event(event) or from_inbox: self._settle_iterations = 0`.
An external (caller-queued) event beginning its step hands the machine a
**fresh** settle budget. Intended as "a user event starts a fresh chain"
(the sync engine's #103/#151 rule), but it means a self-generated cycle is
re-armed by unrelated inbound traffic.

**Reproduced fresh, two ways:**

`probes/main-221ce7c/p4_external_event_renews_budget.py` — same machine,
`maxIterations=20`, with and without a concurrent noise producer:
```
[noise=False] laps=10   settle_tripped=True  VERDICT=BOUNDED at ~20
[noise=True]  laps=1010 settle_tripped=True  VERDICT=BUDGET RENEWED BY EXTERNAL TRAFFIC
```

`concurrency/q7b_minimal_invoke_cycle_unresponsive.py` — the liveness
consequence, deterministic **10/10 machines every run**:
```
"final_inbox_backlog": 19834, "machines_not_answering_in_5s": 10,
"statuses": ["running"], "laps_burned": 70400,
"shapes_that_wedged": [["invoke_pingpong", 10, 19834]], "result": "FAIL"
```
Each lap of an invoke cycle costs a service round-trip, so burning a full
`maxIterations` laps per inbox event is far more expensive than one inbound
`send_threadsafe`. Arrival rate permanently exceeds drain rate and the queue
diverges monotonically (200, 400, 597, 780, 970, … per 50 ms). Controls:
`plain` (no cycle) and `always_cycle` (pure in-loop laps, trip
short-circuits) wedge 0/10 with backlog 0.

**Interaction with R7-01.** These are distinct lines but compound: for an
`async def` service the completion *also* arrives `from_inbox`, so it trips
this reset itself on every lap without any external traffic at all.

**OMS severity: High.** A permanently unresponsive machine reporting
`status == "running"` with a growing backlog. Not a Blocker only because it
requires a cycle shape that R7-01's fix plus a contract-level bounded
counter (CD-03) would also remove.

**Fix direction.** Reset the settle budget only for genuinely external,
non-system events, and never on the `from_inbox` disjunct alone.

---

### R7-05 — async `start()` never sets the in-flight flag; #169's entry-window refusal is inert — High

**Merges:** `D7-persistence-1` and `D7-semantics-1` (identical root cause,
two probes).

**Root cause (source confirmed).** `base_interpreter.py:1389` gates the #169
root-level refusal on `_step_in_flight()`, which reads `_processing` /
`_is_processing` (`base_interpreter.py:1290-1295`). `SyncInterpreter`
deliberately wraps its initial descent in the guard —
`sync_interpreter.py:370-374` sets `self._is_processing = True` around
`self._drive(self._enter_states([self.machine]))`. `Interpreter.start()`
(`interpreter.py:536-556`) calls `await self._enter_states([self.machine],
init_event)` followed by `_settle_transient_transitions()` **without ever
setting `self._processing`**; that flag is only assigned inside the run loop
at `interpreter.py:1654`, which does not perform the initial descent. #171
widened the window by moving child registration and initial settling into
`start()`.

**Reproduced fresh:**

`persistence/q1b_start_entry_window_min.py` (2 parallel regions, both engines):
```
--- ASYNC  ACCEPTED-write -> read side SnapshotCorruptError
      cfg=['pp','pp.r0','pp.r0.a']  (r1 has no leaf)
--- SYNC   REFUSED-write / REFUSED-write
write-accepted / read-refused blobs: async=1 sync=0   <- must be 0
VERDICT: FAIL
```

`semantics/repro/d7s1_start_entry_window_torn.py` — the context-tearing form,
which the read side does **not** catch:
```
--- sync   snapshot in entry: REFUSED / REFUSED
--- async  snapshot in entry: ACCEPTED ctx={'filled_qty':0,'avg_px':0}
                              ACCEPTED ctx={'filled_qty':100,'avg_px':0}  >>> TORN
           restored: ['oms.filled'] ctx={'filled_qty':100,'avg_px':0} last_error=None
```
Property backing: `q1_hook_snapshot_property.py 320 7` → 7,622 attempts,
720 torn, all attributed `{"entry@start": 720}`, 0 raw and 0 round-trip
mismatches.

**OMS severity: High.** A `filled` order persisting with `filled_qty=100,
avg_px=0` restores clean and `last_error is None` — the read-side legality
check cannot see a torn *context*. Engine-parity defect on the persistence
path.

**Fix direction.** Mirror the sync engine: set `self._processing = True`
around the initial-entry + settle block in `Interpreter.start()`.

---

### R7-06 — `machine_hash` `None` or absent silently disables drift verification — High

**Merges:** `D7-persistence-2` and `D6-security-1-R6-07` (carried from round 6,
**STILL-PRESENT**, byte-identical source).

**Root cause.** `persistence.py:276-277`:
```python
snap_hash = snapshot.get("machine_hash")
if verify_hash and snap_hash is not None:
```
The `None` branch exists for genuinely unversioned v0 payloads, but it is
keyed on **the field** rather than on the snapshot's declared `version`. So
deleting or nulling one key downgrades a v2 snapshot to unchecked, even with
`verify_machine_hash=True`.

**Reproduced fresh** (`persistence/q2_readside_gaps.py`), machine A's snapshot
restored into a structurally different machine B:
```
honest hash vs machine B               SnapshotDriftError   <- correct control
machine_hash=None vs machine B         ACCEPTED  states=['m','m.a']
machine_hash key REMOVED vs machine B  ACCEPTED  states=['m','m.a']
```
Corroborated by `security/attack_snapshot_corrupt_fuzz.py`:
`accepted_bad = 196/300`, unchanged from `cec108b`.

Not in the #166–#175 fix set; the line is byte-identical to the round-6
reading.

**OMS severity: High.** A one-key edit defeats the only defence against
restoring an order-state snapshot into a machine whose shape has changed.

**Fix direction.** When `version >= 1` and `verify_hash`, a missing or `None`
`machine_hash` is `SnapshotCorruptError`, not a bypass.

---

### R7-07 — a root snapshot harvests a child actor's half-applied context — High

**Source:** `D7-semantics-3`. `base_interpreter.py:1389-1394`.

**Root cause.** #169 removed the `in flight AND illegal` conjunction **at the
root** but deliberately left it in place for the **child** branch: "legality
remains the test for the bounded wait on a child caught mid-step by its
parent." When the root is quiescent and only a child actor is mid-entry, the
root passes its own `_step_in_flight()` check, then recurses into the child
with `_seen is not None`, taking the lenient branch that only waits
`if not self._configuration_is_legal()`. Inside a child's entry action the
child's configuration **is** legal (one leaf active) while its context is
half-applied — exactly the conjunction #169 removed at the root. The torn
blob simply moved one level down the hierarchy.

**Reproduced fresh**
(`semantics/repro/d7s3_child_midentry_torn_actor_blob.py`):
```
root in flight during child entry : False
live child after settle           : ['kid.y'] ctx={'q':100,'p':101}
root snapshot during child entry  : ACCEPTED child=['kid.y'] ctx={'q':0,'p':0}
root snapshot during child entry  : ACCEPTED child=['kid.y'] ctx={'q':100,'p':0}   >>> TORN
```
The blob nests under `actors['par:kid'].snapshot` and restores clean.

**OMS severity: High.** Same class as R7-05 and with the same read-side blind
spot (a torn *context* is legal-looking), but reached through the documented,
supported parent-snapshot API.

**Fix direction.** Wait on `_step_in_flight()` in the child branch too,
escalating to `SnapshotMidStepError` if the child has not settled within the
bounded wait. See R7-08 — the wait itself must also stop spinning on the loop.

---

### R7-08 — `_await_settled_for_snapshot` spins `time.sleep` on the event-loop thread — High

**Source:** `L-5`. `base_interpreter.py:1280-1289`.

**Root cause.** The bounded wait is
```python
while self._step_in_flight() and not self._configuration_is_legal() and time.monotonic() < deadline:
    time.sleep(0.0005)
```
`time.sleep` — not `await asyncio.sleep`. On the async engine this blocks the
event loop, so the very child the wait exists to let settle **cannot make
progress**. The wait is therefore guaranteed to burn its full timeout and
then return the unsettled blob.

**Reproduced fresh**
(`probes/main-221ce7c/p10_snapshot_refusal_and_child_wait.py`):
```
(a) sync  entry-action snapshot: refused (SnapshotMidStepError)
(a) async entry-action snapshot: refused (SnapshotMidStepError)
(b) parent snapshot over a mid-step ASYNC child: snapshot returned after 502 ms of loop-blocking spin
(b) VERDICT: BOUNDED WAIT SPINS ON THE LOOP THREAD (child cannot progress)
```
Part (a) confirms #169's root refusal genuinely works on both engines
(see §6); part (b) is the defect.

**OMS severity: High.** A routine snapshot stalls the whole loop — every
timer, every inbox read, every other machine on that loop — for the full
wait, and achieves nothing. Compounds R7-07: the mechanism meant to fix the
child case is itself inoperative on the async engine.

**Fix direction.** Make the child wait awaitable (`await asyncio.sleep`) on
the async engine, or perform the wait by scheduling on the loop rather than
blocking it.

---

### R7-09 — a contradictory `configuration` key outranks `state_ids` on restore — Medium

**Source:** `D7-persistence-3` (carried `R6-16`, **changed for the worse** in
assessment). `base_interpreter.py:1689`:
```python
restore_ids = snapshot.get("configuration") or snapshot["state_ids"]
```

**Root cause.** The reader *prefers* `configuration` rather than
cross-validating it against `state_ids`. The two keys are never compared. The
#143 read-side legality check runs **after** this selection, so a
legal-but-forged configuration passes it cleanly.

**Reproduced fresh** (`persistence/q2_readside_gaps.py`), snapshot has
`state_ids=['m.a']`, `configuration=['m','m.a']`:
```
configuration=[] (state_ids intact)       ACCEPTED  states=['m','m.a']   (silent fallback)
configuration=['m','m.b'] vs state_ids a  ACCEPTED  states=['m','m.b']   (relocated)
```

Filed at round 6 as Low ("never cross-validated"); re-rated **Medium** here
because the contradictory key is *authoritative*, not merely unvalidated —
editing one field relocates the machine to any state the attacker names, and
the honest field that contradicts it is discarded without a word.

**Fix direction.** Cross-validate: `configuration` must be the ancestor
closure of `state_ids`; a mismatch is `SnapshotCorruptError`.

---

### R7-10 — `get_persisted_snapshot()` from `on_action_execute` returns a torn blob on async — Medium

**Source:** `D7-concurrency-2`. Refusal site `base_interpreter.py:1393` vs
the `_execute_transition` exit→actions→enter transaction.

**Root cause.** #169 armed the root refusal on "in flight" alone for
entry/exit actions, but `on_action_execute` also fires for **transition**
actions; for at least one of those the async engine is not flagged in flight
while `_active_state_nodes` has already been emptied by `_exit_states`.

**Reproduced fresh** (`concurrency/q2b_minimal_action_hook_torn.py`,
deterministic, 1 torn blob per run):
```
async: 5 on_action_execute calls -> 1 torn, 1 legal, 3 refused:SnapshotMidStepError
sync : 5/5 refused
"async_torn_blobs": 1, "sync_torn_blobs": 0,
"restored_from_torn_blob": {"restore": "REFUSED", "exc": "SnapshotCorruptError"}
"result": "FAIL"
```
Property evidence: `q2_hook_snapshot_property.py --n=300` → 81 torn blobs of
750 restored, **100% from `async:on_action_execute`**, 0 from any sync hook
and 0 from any other async hook.

**OMS severity: Medium, not High.** Blast radius is bounded by #143:
restoring the torn blob raises `SnapshotCorruptError`, so this is an
observability/engine-parity defect rather than silent corruption. Contrast
R7-05 and R7-07, where the tearing is in the *context* and the read side
cannot see it.

**Fix direction.** Extend the in-flight flag to cover the whole
exit→actions→enter transaction, so transition actions are inside the window
that entry/exit actions already are.

---

### R7-11 — sync `_deferred_this_step` never cleared on `wait=False` — Medium

**Source:** `L-6`.

**Root cause.** The per-step list is cleared at the top of a `wait=True`
step, but the `wait=False` path never reaches that reset, so the list — whose
scope is meant to be one step — accumulates for the life of the interpreter.

**Reproduced fresh** (`probes/main-221ce7c/p7_sync_per_step_list_leak.py`):
```
sends=5000
_deferred_this_step (per-STEP scope) = 5000
_deferred_events    (the real buffer) = 1000
VERDICT: PER-STEP LIST NEVER CLEARED ON wait=False -- 5000 entries retained
after one wait=True send: _deferred_this_step = 1
```
The real defer buffer is correctly bounded at 1,000; only the per-step
bookkeeping list grows without limit. A single `wait=True` send flushes it.

**OMS severity: Medium.** Unbounded memory growth on a long-lived
fire-and-forget sync interpreter, and any `Receipt.deferred` computed from
that list is wrong after the first step. Its sibling `_guard_denied_this_step`
is correctly reset (see §6, `L-9`).

**Fix direction.** Clear `_deferred_this_step` at the start of every step,
not only the `wait=True` one.

---

### R7-12 — `onUnhandled:"error"` fatal kill is invisible to the sender — Medium

**Source:** `LIB-01` (carried, unchanged on `221ce7c`).

**Root cause.** The unhandled-event kill path does not populate the `Receipt`
or `last_error`; only the `on_unhandled_event` plugin hook fires (disposition
`errored`). #153's `denied` flag does not cover this case.

**Evidence** (`g3_b13.py` B13-unh, `g3_b13_unh.py` B13-unh-2,
`g3_b14_b15.py` B14-unh, `g3_confirm.py` CONF-4): B13 `CONNECT` in
`ws_conn.live` and B14 `UNSUBSCRIBE` in `book.snapshot_pending` both return
`Receipt(changed=False, error=None, deferred=False, denied=False)` — fully
success-shaped nulls — while `status` flips to `'error'`, `running` goes
`False`, and `last_error` stays `None`.

**OMS severity: Medium.** The sender that *caused* a fatal machine kill is
told nothing went wrong. Severity is capped below High only because the kill
itself is loud in `status`, so a supervisor polling `status` catches it even
though the caller does not. Interacts badly with `C-07b`: on B18 two ordinary
operator mistakes become a dead kill switch the operator cannot see.

**Fix direction.** Populate `Receipt.error` and `last_error` on the
unhandled-kill path.

---

### R7-13 — config-level `strict:true` does not gate event names; `"*"` defeats `is_known_event()` — Medium

**Source:** `LIB-R6-strict` (carried).

**Root cause.** Only `Interpreter(strict=...)` gates event names; the
**machine-config** `strict` flag does not. Additionally, a state-level `"*"`
handler makes `is_known_event()` return true for arbitrary event names.

**Evidence** (`g3_b13.py` B13-strict, `g3_b13_unh.py` B13-strict-2,
`g3_wildcard.py` STAR-2/STAR-3): `NOT_A_REAL_EVENT`, `after.party`,
`done.invoke.bogus` and `xstate.bogus` are all ACCEPTED on B13 with
`last_error=None`. Removing the A3 wildcard from B13 restores strict gating
(STAR-3 PASS), isolating the wildcard as the second, independent axis.

**OMS severity: Medium.** We set `strict` in the catalogue JSON and believed
it was in force; a typo'd order event is accepted silently. Compounds R7-18
(unknown keys accepted silently) — two independent ways to believe a safety
setting is on when it is not.

**Fix direction.** Honour config-level `strict`, and exclude `"*"` from
`is_known_event()`'s answer (a wildcard handler means "I will catch it", not
"this name is known").

---

### R7-14 — call-site `QueueOverflowError` refusals fire no `on_event_dropped` hook — Low

**Source:** `D7-concurrency-3`. `interpreter.py:1136-1137`.

**Root cause.** #157's fix added the `on_event_dropped(queue_full)` hook only
to the **loop-side** refusal path. The optimistic call-site `qsize()` guard in
`send_threadsafe` raises `QueueOverflowError` before anything is queued and
never reaches that path, so it fires no hook.

**Reproduced fresh** (`concurrency/q3_pool_counter_hooks.py` part C, 16
threads, 2 s, depth-4 inbox, `OverflowPolicy.RAISE`):
```
callsite_refusals 5053, loopside_refusals 8878, total_refusals 13931,
queue_full_hooks 8878, other_drop_reasons [], exactly_once false
```
Exactly the loop-side half is observable; a plugin aggregating the hook
under-counts the shed rate by ~36–50% under the very 16-producer conditions
the hook was added for. (Lap counts vary run to run; the
`queue_full_hooks == loopside_refusals`, `callsite → 0 hooks` relationship is
invariant.)

**OMS severity: Low.** Pure observability; the refusal itself is correct and
reaches the caller as an exception. Noted because §6 records #157's loop-side
half as genuinely fixed and exactly-once — this is the remaining half.

**Fix direction.** Fire `on_event_dropped(queue_full)` from the call-site
guard too, or drop the optimistic guard and let every refusal take the
loop-side path.

---

### R7-15 — `last_error` is set after the drop hooks and cleared by the next success — Low

**Source:** `D7-semantics-2`. `interpreter.py:1565-1576`.

**Root cause.** Two compounding facts, both visible in the source read above:
(1) `self._last_action_error = RunawayChainError(...)` is assigned **after**
the `for plugin in self._plugins: plugin.on_event_dropped(...)` loop, so a
plugin reading `interpreter.last_error` from inside its own drop hook sees
`None`; (2) `last_error` is then cleared by the next successful transition.

**Reproduced** (`s2_concurrency_obs.py::S2-01`, run with and without a
16-thread flood):
```
flood=False  drops=1  at_first_drop=('chain_budget', None)  last_error_now=RunawayChainError  ticks=1001
flood=True   drops=1  at_first_drop=('chain_budget', None)  last_error_now=None               ticks=1001
```

**Important negative result carried with this finding:** the chain budget
*itself* is correct here. The chain trips at lap 1001 in both runs and
external senders do not refill it, so #166's headline claim holds on this
shape — the defect is confined to the reporting channel the CHANGELOG names
as the signal. (This is the `always`-family shape; contrast R7-04, where a
*service* round-trip per lap does let traffic outpace the drain.)

**OMS severity: Low.** Observability only, and the `on_event_dropped` reason
string is correct and timely.

**Fix direction.** Set `_last_action_error` **before** firing the drop hooks,
and document `last_error` as latch-until-next-success — or add a monotonic
`chain_trips` counter, which is what a supervisor actually wants.

---

### R7-16 — `DEFAULT_SERVICE_POOL_SIZE` documented but not exported — Low

**Source:** `D7-semantics-4`. Confirmed fresh this round:
```
'DEFAULT_SERVICE_POOL_SIZE' in xstate_statemachine.__all__   -> False
from xstate_statemachine import DEFAULT_SERVICE_POOL_SIZE    -> ImportError
from xstate_statemachine.interpreter import DEFAULT_SERVICE_POOL_SIZE -> 4
xstate_statemachine.__version__                              -> '0.8.0'
```

CHANGELOG line 73 lists the name under **Added** and `docs/api/index.md:695`
cites it in the public parameter table, but `__init__.py.__all__` (line 205)
omits it; the value is reachable only via the private submodule path.

Everything else about #173 is correct and verified: `service_pool_size=0`
raises `ValueError`, and `pool_size=8` beats `pool_size=1` by **7.8×** on 8
concurrent plain services (0.154 s vs 1.208 s).

**Fix direction.** One line in `__init__.py.__all__`.

---

### R7-17 — `spawnBlockingTimeout` validated then dropped — Low

**Merges:** `OBS-01` and `WRAP-spawnBlockingTimeout` (same fact, filed twice
— once as a library observation, once as a wrapper obligation; the underlying
defect is the library's).

**Root cause.** The key passes config validation but is never surfaced as an
attribute on the built `MachineNode`, so a value we believe we set has no
readable effect.

**Evidence** (`contracts/c1_build.py` → `c1.out`; `g3_build.py`):
`spawnBlockingTimeout` reads `"<missing>"` / `ABSENT` on all five machines
while every other policy key — `actionErrorPolicy`, `onUnhandled`,
`guardErrorPolicy`, `strictTargets`, `strict` — reads back verbatim.
Unchanged from `cec108b`.

**OMS severity: Low.** No contract in this group spawns, so there is no
behavioural impact today; but it defeats a conformance lint that wants to
assert the catalogue policy block post-build, and it is indistinguishable
from R7-18's silent-typo failure mode from the outside.

**Fix direction.** Surface the attribute on `MachineNode`. Wrapper obligation
in the meantime: assert the attribute exists at build time rather than
trusting the JSON.

---

### R7-18 — unknown top-level config keys accepted silently — Low

**Source:** `WRAP-unknown-keys`. Re-classified from `NEEDS-WRAPPER` to
`LIBRARY-DEFECT`: a validator that rejects bad *values* but accepts unknown
*keys* is an incomplete validator, not a design choice.

**Evidence** (`g3_policy.py`): `P2_typo_keys` → `ACCEPTED SILENTLY
on_unhandled=error`, i.e. a misspelled policy key leaves the default silently
in place with no diagnostic. By contrast `P3`/`P3b`/`P3c` correctly raise
`InvalidConfigError` for bad values `'deferr'`, `'rolback'`, `'riase'`.

**OMS severity: Low** in isolation, but it is the delivery mechanism for a
High-severity mistake: a typo in `actionErrorPolicy` silently downgrades an
order machine to default error handling. Same class as R7-13 and R7-17 —
three separate ways to believe a safety setting is on when it is not.

**Fix direction.** Reject unrecognised top-level config keys.

---

### R7-19 — `get_persisted_snapshot()` returns a dict, `from_snapshot()` refuses a dict — Low

**Source:** `C221-03`.

**Root cause.** `get_persisted_snapshot()` is typed `-> Dict[str, Any]` while
`from_snapshot(snapshot_str, ...)` requires a JSON **string**. The natural
persist→restore call pair does not compose.

**Evidence:** `Interpreter.from_snapshot(that_dict, m)` →
`SnapshotCorruptError('Snapshot payload must be a JSON string, got dict.')`.
Observed on every snapshot round-trip in the first B2 run (t0..t4 all
restore-raised); fixed in the harness by threading `json.dumps` between the
two calls in `cv221.snap_roundtrip`.

**OMS severity: Low.** Discovered immediately and worked around in one line.
Noted because the failure surfaces as a **corruption**-flavoured
`SnapshotCorruptError` rather than a `TypeError`, which sends the reader
hunting for data damage that is not there.

**Fix direction.** Accept a `dict` in `from_snapshot`, or return a string
from `get_persisted_snapshot` — either way make the pair compose.

---

### R7-20 — sync/async lap-count asymmetry inside the *fixed* plain-`def` path — Low

**Source:** `CV-221-02`.

**Root cause.** Even on the path round 6 genuinely fixed, the two engines do
not agree on *how much* work a cycle does before it is cut: the sync engine
detects the cycle structurally and stops in 2 service calls; the async engine
runs the full `maxIterations` ladder first.

**Evidence** (`contracts/q6_parity.py`):
```
sync  mi=1000 -> 2 calls in 0.005s, rests in m.a
async mi=1000 -> 1002 calls, then RunawayChainError
sync  mi=5    -> 2 calls
async mi=5    -> 7 calls
```
Corroborated fresh by this round's ping-pong probe: `sync laps=22` vs
`async plain def laps=22` agree at `mi=20` on *that* shape, so the asymmetry
is shape-dependent rather than universal.

**OMS severity: Low.** Both engines terminate and both are observable
(`RunawayChainError`); only the wasted work differs. It does, however,
qualify the CHANGELOG's "trips at the same lap count on both engines" — true
for the pinned shape, not in general.

**Fix direction.** Documentation, or align the async engine's cycle detection
with the sync engine's structural check.

---

## 2. Duplicates folded into the canonical set

| Filed as | Folded into | Basis |
|---|---|---|
| `D7-fuzz-1` | R7-01 | Same defect; its stated root cause (`_processing` gate) is **superseded** by the lane probe. |
| `D7-fuzz-2` | R7-01 | Same line, the silent-loss symptom. |
| `C221-01` | R7-01 | Independent filing, same one-word ablation. |
| `LD-04` | R7-01 | Explicitly supersedes `LD-03`; itself superseded on mechanism by the lane probe. |
| `CV-221-01` | R7-01 | Correctly identified the inbox lane **and** the `from_inbox` reset; both confirmed. |
| `LIB-R6-01` | R7-01 | `/tmp/rb.py` ablation: rollback+re-invoke is bounded with `def`, unbounded with `async def`. Not a separate family. |
| `L-3` | R7-01 | Same finding from the diff-review track. |
| `D7-concurrency-1` | R7-04 | Liveness symptom of the `from_inbox` budget reset. |
| `L-4` | R7-04 | Mechanism form of the same line. |
| `D7-semantics-1` | R7-05 | Identical to `D7-persistence-1`; two probes, one missing `_processing = True`. |
| `D6-security-1-R6-07` | R7-06 | Carried round-6 item, re-verified still present. |
| `WRAP-spawnBlockingTimeout` | R7-17 | Wrapper-facing restatement of `OBS-01`. |
| `LD-03` | — | **Withdrawn** by its own author (`is_female_system_event` exemption theory); refuted again here by the lane probe. |
| `attack-K` (async half) | R7-01 | Its PASS verdict holds only for `def` services (see §6). |

---

## 3. DESIGN-CONSTRAINT — library behaves as designed; the wrapper absorbs it

### DC-1 (`C221-02`) — `SyncInterpreter` accepts neither `max_queue_size` nor `overflow_policy` — Medium
`SyncInterpreter(m, max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)`
→ `TypeError`. The signature on `221ce7c` is
`__init__(machine, input=None, clock=None, strict=None)`. The sync engine
drains inline and has no inbox bound in the same sense, so the bounded-RAISE
inbox mandated for the order path **cannot be expressed on it**. Not a
defect, but it means every sync-parity run in this track is an
unbounded-inbox comparison — valid for ordering and effects, **not for
backpressure**. Wrapper obligation: refuse a bounded-inbox config on the sync
path, or enforce the bound at the call site.

### DC-2 (`W-05`) — `service_executor` / `service_pool_size` do not retire CV-C32 — Medium
`c9_cvc32_executor.json`: `send(PING, wait=True)` latency **0.001 s** with an
`async def` service vs **0.441 s** with a plain `def` (0.437 s with a custom
`ThreadPoolExecutor`). #149 moves plain-`def` services off the loop —
heartbeat gaps are identical at 0.033 s — but the entering macrostep still
awaits the result, so the block is **in the macrostep, not the pool**; a
custom executor and a larger pool change nothing. CV-C32 stays, scoped
async-engine-only. Note the uncomfortable interaction with R7-01: CV-C32
compliance is exactly what puts every contract on the unprotected side of the
chain budget.

### DC-3 (`W-04b`) — `onUnhandled:"defer"` outranks the `guard_denied` disposition — High (wrapper)
`contracts/repro/f6_denied_defer_buffer.py`: 3× `TIGHTEN_SL` denied by
`tightens_only=False` → `deferred_count=3`; flip `tightens_only=True`, send
`WATCHDOG_MISS` → `set_trading_stop` invocations go 0 → **3**. A refused
amend is replayed later against a changed world.
`f7_disposition_precedence.py` confirms the precedence
(`defer → "deferred"` shadows `guard_denied`; `ignore → guard_denied`,
`error → errored`). Library precedence is defensible; it is the wrong default
for an order path. Wrapper obligation **CV-C25**: `@cv_guard` must
distinguish "refuse and discard" from "not applicable here", and the wrapper
drains denied events from the defer buffer at end of macrostep.

### DC-4 (`CV-221-03`) — the break-glass mitigation for R7-01 contradicts #174 — Medium
`contracts/q10_wrapper.py` on real B18: `async def` svc unbounded
(1260 → 2548, growing); plain-`def` svc bounded (1002 flat,
`RunawayChainError`); plain-`def` + `maxIterations=5` → 7 calls. So the only
available mitigation for R7-01 is "use plain `def` services", which #174
documents as blocking the machine's own `after` timers — and B19's
`backing_off` retry ladder depends on `after` timers firing during a service.
**There is no configuration that satisfies both.** This is the strongest
single argument for holding the adoption gate: the Blocker has no wrapper-level
workaround.

### DC-5 (`D6-security-2`) — `send_threadsafe(internal=True)` is an honesty-based trust boundary — Low/Informational
`security/attack_threadsafe_forgery.py`: any caller may pass `internal=True`
and have its event treated as engine-generated. In-process only, so within
our trust boundary; recorded so the wrapper never exposes that parameter to
anything but wrapper code. Note this parameter is also part of the *fix
direction* for R7-02 — if provenance moves onto an explicit flag, this
boundary carries more weight and should be reconsidered.

---

## 4. OUR-CONTRACT-DEFECTs — our catalogue JSON; the engine is faithful

| ID | Sev | Title | Evidence |
|---|---|---|---|
| `C-04` | **Blocker** | B16 elevation outlives `LOGOUT` / `IDLE_DEADLINE` / `ABSOLUTE_DEADLINE` and can be acquired after revocation (INV-B16-a, INV-B16-d) | `contracts/k1_b16_b17.py`, `results/k1_b16_b17.json` — byte-identical to the `cec108b` baseline |
| `C-07b` | **Blocker** | B18 `onUnhandled:"error"` turns two ordinary operator mistakes into a dead kill switch (INV-B18-d) | `contracts/k2_b18.py`, `results/k2_b18.json` (carried, byte-identical) |
| `CD-03` | High | B8 `naked` ↔ `verifying` is an unbounded invoke-driven livelock when the fallback attach succeeds but the exchange still reports no SL | `contracts/repro/f2_naked_verify_livelock.py` — 4,027 laps / 8.05 s (500/s), 4,027 `raise_critical_alert` firings, `status=running`, `last_error=None`. Escape hatch intact (`f3_escape_hatch.py`) |
| `C-06` | High | B19 `stale_lockout` only listens for `RECONNECTED`; the INV-B19-b operator escape hatch does not exist | `contracts/k3_b19_b20.py` (carried) |
| `OUR-B14-02` / `OUR-B15-01` | High | Fallible telemetry inside the atomic entry set of a safety transition, under `rollback`, cancels the desync / cancels the liquidation | `g3_r6.py` R6-B14-03 / R6-B15-03 |
| `OUR-B11-01` | High | `recording.degraded` has no `STREAM_UNHEALTHY` handler: a second failing stream is deferred indefinitely and the health map goes stale | `g3_b11_hazard.py`, `g3_confirm.py` CONF-2 |
| `OUR-B14-01` | High | INV-B14-d "bounded buffer" is prose-only; deltas buffer 1:1 with input | `g3_b14_b15.py` B14-d: 1000 DELTA → `buffered_len 1000`, `dropped_by_engine []` |
| `C-05` | Low | B16 `STEP_UP_OK` while already elevated writes no audit record (INV-B16-c) | `contracts/k1_b16_b17.py` |
| `C-07` | Low | Catalogue promises halted states that exist in none of B16–B20 | `contracts/k0_build.py`: `halted == False` for all five |
| `C-01` | Low | Missing action/guard/service implementations are not a build error | `contracts/k0_build.py`: `build_bare_logic == OK` for all five |

**Notes.**

- `CD-03` is ours, not the library's, but it is the *shape* R7-01 makes
  unbounded and silent. Fix: a bounded fallback-attempt counter on
  `naked.invoke.onDone` routing to `naked_unrecoverable` on exhaustion,
  edge-trigger `raise_critical_alert` on `naked_since`, and a new lint
  **CV-LINT-XS16** — no two invoking states may target each other on success
  paths without a bounded counter.
- `OUR-B14-02` / `OUR-B15-01`: `rollback` is behaving as documented; the
  defect is that we put non-essential fallible side effects
  (`emit_resync_metric`, `emit_book_desynced`, `write_liquidation_journal`)
  in the same all-or-nothing entry set as a safety transition. Note also that
  `denied` is asymmetric for the same class of outcome (B15 `True`, B14
  `False`), so **`error is not None` is the only usable "did my transition
  land?" test**. A snapshot taken after the rollback persists the rolled-back
  state, so a restart does not clear it.
- `C-01` is arguably a library ergonomics gap too, but building with bare
  logic is a legitimate supported mode (`create_machine` without
  `logic_modules`), so it stays here as a lint obligation on our side.

---

## 5. HARNESS-ERRORs — our probes/gate, not the library

### H-1 — `VERIFYM3_BASELINE_FAILURES` is missing two rows
`gate/run_gate.py`'s allow-list records only `["157"]`, but the
`verify-main-cec108b/` script directory has since gained
`150_send_threadsafe_budgeted.py` and `probe_144_async*.py`. Both appear as
`verifyM3` FAILs with no prior JSON baseline entry. Direct check-by-check diff
against `result-main-cec108b.json` confirms **neither row appears at all** in
the `cec108b` JSON — they are newly added rows, not PASS→FAIL transitions.
Both were re-run 5× fresh: **5/5 deterministic FAIL**, and both are named in
`39-r6-final-readiness-verdict.md` §2 as pre-existing `cec108b` FAILs
(`150` = the CHANGELOG's own documented residual on default-argument
`send_threadsafe()` from a plain `threading.Thread`; `probe_144_async` =
`AssertionError: no RunawayChainError recorded`).
**Fix:** add `150` and `probe` to `VERIFYM3_BASELINE_FAILURES`.

### H-2 — the gate's baseline table does not enumerate `verify`-set FAILs
`LC-01`, `LC-12`, `LC-26`, `LC-48`, `LC-57` flag every run. All five were
already FAIL at `cec108b`; `LC-48` FAILs under `verify` at `cec108b` too (its
companion `repro` row is the PASS one). The script tracks only
`verifyM`/`verifyM2`/`verifyM3` as separate allow-lists.
**Fix:** give the `verify` set its own baseline-failure allow-list.

**Net gate result for round 7: zero true PASS→FAIL regressions**
(`40-r7-regression.md`). Totals `FAIL=36, PASS=80`; every flagged delta traces
to H-1, H-2, an unchanged pre-existing FAIL confirmed by direct JSON diff, or
a script already named as an expected/superseded FAIL. Flaky-check ×5: all
deterministic. The 21 informational `repro` FAILs match the
fixed-but-opt-in / stale-repro characterisation with no new LC ids vs
`cec108b`.

---

## 6. Confirmed-fixed and negative results

These were re-run and **hold**. Recording them matters as much as the
defects: they bound how far R7-01 and R7-02 reach.

| ID | Claim | Status |
|---|---|---|
| `W-04a` (#170) | `Receipt.denied` is no longer `True` for a guard that **crashed** | **FIXED.** `f5_denied_conflation.py`: `changed=False, deferred=False, denied=False, error=RuntimeError` (was `denied=True` on `cec108b`). Sync parity confirmed. Makes c2's INV-B8-b assertion (`HD-01`) stale. |
| `R6-03` / `R6-01` (#166/#167) | rollback+`invoke.onDone` and `always`-into-invoked-child terminate, bounded and observable, on the **real contract machines** | **FIXED, 5/5 PASS.** `g5_r603_r601_shapes.py`. B6 `submitting_slice` rolled back to `twap.armed`, no orphan invoke; B9 rolled back with `pending_invocations=[]`, no resurrection of the abandoned target; B6 `always` ladder settles in 0.32 s with 0 service invocations; B8 attach ladder settles into `sl.protected` with exactly 2. `send(wait=True)` never hung. **All with plain `def` services** — this is the path R7-01 leaves protected. |
| `attack-I` / `confirm-157` (#157) | loop-side `RAISE` refusal fires `on_event_dropped(queue_full)` exactly once per refusal | **FIXED.** `attack_raise_refusal_exactly_once.py`: `refused=199, hook_fires=199`; `q3` part C: `queue_full_hooks == loopside_refusals` exactly, `other_drop_reasons []`. The call-site half is R7-14. |
| `attack-J` / `L-10` (#169) | `get_persisted_snapshot()` refused from inside an entry action at the root, both engines | **FIXED.** `p10` part (a): sync and async both `refused (SnapshotMidStepError)`. The residual windows are R7-05 (initial entry), R7-07 (child), R7-10 (transition actions). |
| `attack-K` (#166/#168) | `RunawayChainError` trips at an identical lap count on both engines (n=25) | **Holds for `def` services only.** Confirmed fresh at `mi=20`: sync 22 laps, async plain-`def` 22 laps. With `async def`: 70,159 laps and no trip → R7-01. Shape-dependent, cf. R7-20. |
| `attack-L` / `confirm-chain-budget` | a self-generated chain still trips under sustained concurrent external `send_threadsafe` traffic | **Holds on the `always` shape.** `S2-01` flood=True still trips at lap 1001. Does **not** generalise to invoke cycles → R7-04. |
| `attack-M` (#173) | `service_pool_size=1` with 50 services survives `stop()` mid-flight, no hang or crash | **PASS.** Plus `pool_size=8` 7.8× faster than `pool_size=1` (0.154 s vs 1.208 s); `service_pool_size=0` raises `ValueError`. Only the export is wrong (R7-16). |
| `attack-O` (#172) | `send_threadsafe` in-flight counter settles to 0 even when a chain-budget trip occurs mid-flight | **PASS.** `q3` part B: `future_delivered=400, future_refused=0, inflight_counter_after=0, raise_depth_after_quiescence=0`. `L-7` independently hammers the same path clean. |
| `L-8` (#165) | `__slots__` compatibility | **Clean.** `__dict__` retained where subclassing and plugin attribute injection need it. |
| `L-9` (#153) | `_guard_denied_this_step` stickiness on `wait=False` | **Negative — correctly reset.** The sibling of R7-11; only `_deferred_this_step` leaks. |
| `L-10` | sentinels, lazy deadline-heap lock, single-pass parser (#165/#176) | **Clean.** No behavioural change found. |
| `p9` | `after`-timer charged mid-step | **Not separately reproducible.** The mechanism is identical to R7-02 and a slower service would expose it; folded into R7-02 rather than filed. |
| `prior-defects-carryforward` | 9 legacy observability defects | **All re-verified unchanged** on `221ce7c`. |
| #122 | `tick()` on a `RealClock` real-delay ladder | **Correctly closed as working-as-designed.** `tick()` drains what is due at the current reading; no synchronous call can make wall time pass. The original repro encoded the async engine's wall-clock wait as a sync expectation. |

---

## 7. What the round-7 evidence changes

1. **The round-6 cycle fix landed on the wrong side of a fork.** #166/#167/#168
   are real and verified on our own contract machines — with `def` services.
   The `async def` path, which #174 tells users to prefer, was never on the
   charged lane to begin with. The library's three pinned tests all declare
   `def`, so the suite cannot see it. One extra parametrisation over service
   kind would have caught every one of the six filings folded into R7-01.

2. **Two of the three Blockers are new in round 7.** R7-02 is a regression in
   `_deliver_priority`'s provenance test, and R7-03 is a regression introduced
   by #171's unbounded `gather`. Both were introduced by round-6/7 fix work.

3. **`status` is not a liveness signal on the async engine.** R7-01, R7-03
   and R7-04 all present as `status == "running"` with `last_error is None`.
   R7-15 explains why `last_error` cannot be trusted as the backstop. Any
   supervisor we ship must key on progress counters, not on `status`.

4. **R7-01 has no wrapper-level workaround** (DC-4). Plain-`def` services are
   the only mitigation and they break the `after`-timer behaviour B19's retry
   ladder depends on.

**Adoption recommendation: hold the gate.** R7-01, R7-02 and R7-03 are each
either a round-7 regression or an incomplete round-6 fix — not pre-existing
documented limitations — and all three are silent on the order path.
Everything else in the round-6/7 surface (#170, #171 apart from R7-03, #172,
#173, #157's loop-side half, and the whole of #165/#176 apart from R7-11) is
clean.
