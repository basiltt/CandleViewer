# Battle-test track: PERSISTENCE & crash consistency (snapshot layout v2)

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`5e07ba8`** (merge of PR #101, `fix/round3-ride-alongs`), CHANGELOG
`[Unreleased] — targeting 0.8.1`. **`__version__` still reports `0.8.0`; this
build is identified by commit, never by version string.**

**Date:** 2026-09-18 · **Python:** CPython 3.13.7 · **OS:** Windows 11 Pro
10.0.26200 · **Interpreter:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

No library source was modified. No `git` command was run in the CandleViewer
repository. GitHub was read-only throughout.

Scripts: `docs/research/xstate/battle-5e07ba8/persistence/`.

---

## 0. Bottom line

**The snapshot format is good. The moment at which a snapshot is taken is
not defended, and that is a Blocker for an order path.**

Layout v2 does what the CHANGELOG says: every event class round-trips, the
deferral buffer and the bounded inbox survive, machine-hash drift is refused
with a precise error, 1 MB of context round-trips in ~8 ms, and child actors
(spawned *and* invoked) come back alive and drivable. A 2,000-case hypothesis
run crashing at every *quiescent* boundary of random event sequences found
**zero divergences** in final state, context or emitted-action trace.

But `get_persisted_snapshot()` has no transactional relationship with the
macrostep. `_exit_states → actions → _enter_states` is documented in the
source as "ONE transaction" (`base_interpreter.py:2338`) and is correctly
rolled back on *action failure* — but a snapshot taken from inside that window
reads `_active_state_nodes` directly and observes the half-applied
configuration. **37.6 % of snapshots taken at a random action boundary of a
random event sequence record an illegal configuration** (2,000 hypothesis
cases, `t8_midstep_property.py`), and every one of them is accepted by
`from_snapshot()` without a word. The restored machine reports
`status == "running"`, `error is None`, `has_dormant_invocations == False` —
and can never transition again.

A crash is precisely an interruption at an arbitrary moment. A snapshot API
whose correctness depends on not being called during a macrostep does not
provide crash consistency, which is the thing it exists to provide.

Separately, **an `after` timer does not survive a restore in any window** —
not before it fires (never re-armed, D-2) and not after it fires (the
priority lane is not persisted, D-6). For the order path, `after` *is* the
exchange-ack timeout.

**Six defects: 1 Blocker, 2 High, 2 Medium, 1 Low.**

---

## 1. Method

### 1.1 The machine under test

`order_machine.py` — shaped like the CandleViewer order path (B1–B20):

- `draft → submitted → {cancelling, closed}`, `closed` final;
- `submitted` is a **parallel** state with two regions: `exchange`
  (`acking → working → complete/stale/timed_out/rejected`) and `risk`
  (`checking → passed/blocked`);
- `exchange.acking` carries an **`invoke`** (`ack_service`) with `onDone` /
  `onError`, plus an **`after: 5000`** timeout;
- `exchange.working` carries an **`after: 30000`** staleness timer;
- machine-level **`onUnhandled: "defer"`**;
- a `FAIL_HARD` transition whose action raises, for `actionErrorPolicy`
  work;
- all time driven by **`SimulatedClock`**.

### 1.2 Harness

`harness.py` provides `run_plain(seq)` (uninterrupted reference) and
`run_interrupted(seq, k)` (run `seq[:k]`, `get_snapshot()`, destroy the
interpreter, `from_snapshot()` into a fresh one, resume with `seq[k:]`).
Both return an `Outcome` compared field-by-field on **state ids, context,
emitted-action trace and status**. The action trace is collected through the
public `PluginBase.on_action_execute` hook and carried across the restore, so
the comparison is of the *whole* emitted-effect sequence, not just the
endpoint.

**One harness concession, itself a finding.** `Interpreter.from_snapshot()`
has **no `clock=` parameter**, so a restored interpreter is always built with
a `RealClock` and virtual time cannot be carried across a restore through any
public API. `harness.attach_clock()` re-derives the two attributes
`BaseInterpreter.__init__` sets from `clock=` (`self.clock`,
`self._clock_accepts_sync`) and calls the clock's `_attach`. This is a
faithful substitute for a constructor argument that does not exist, but it is
private-attribute surgery and it is filed as **D-persistence-1**.

### 1.3 Exact commands

All run from the scripts directory with:

```
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
PYTHONPATH=/c<workspace>/_ref/xstate-statemachine/src \
"<workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python" <script>
```

| Script | What it does |
|---|---|
| `p0_smoke.py` | sanity: the machine runs, layout `version == 2` |
| `t1_crashpoints.py` [`--restart`] | exhaustive: crash at **every** k of 4 hand-built sequences |
| `t2_property.py` | **hypothesis, 2,000 cases** — random sequence × random quiescent crash point |
| `t8_midstep_property.py 2000` | **hypothesis, 2,000 cases** — snapshot at a random action boundary *inside* a macrostep |
| `t3_probes.py` | P1–P10: deferred buffer, receipts, in-flight invoke, v1 upcast, v2 round-trip, hash drift, 17 corrupt blobs, 1 MB context, child actors, bounded inbox |
| `t4_receipts_provenance.py` | receipts for an inbox-resident event; v1 provenance laundering |
| `t5_midmacrostep.py` | freeze the run loop inside an action, crash, compare |
| `t6_action_boundary.py` | snapshot before every action of a realistic run and classify |
| `t7_rollback.py` | `actionErrorPolicy: "rollback"` across the snapshot boundary |
| `d2_after_timer_lost.py` | **D-2** minimal repro |
| `d3_torn_snapshot.py` | **D-3** minimal repro (empty configuration) |
| `d3b_partial_parallel.py` | **D-3b** minimal repro (missing parallel region) |
| `d5_invoke_dormancy.py` | documents the `pending_invocations` / `restart_services` surface |
| `d6_priority_lane.py` | **D-6** minimal repro (fired timer lost) |

---

## 2. Results

### 2.1 Differential: crash at a quiescent boundary

`t1_crashpoints.py` — every crash point of 4 sequences (22 points):

| | matches |
|---|---|
| `restart_services=False` | **20 / 22** |
| `restart_services=True` | **20 / 22** |

Both failures are the same sequence (`timers`) at k=1 and k=2, and both are
**D-persistence-2**: the crash happens while an `after` is armed, the restore
does not re-arm it, so the later `__TICK__` fires nothing. Nothing else
diverges.

`t2_property.py` — **hypothesis, 2,000 cases**, random sequences of 1–8 events
from an 11-event pool × random crash point 0–8:

```
cases run: 2000   failing cases: 0   distinct: 0   timers=False
```

**Zero divergences in state, context, action trace or status.** Timer events
are excluded from this pool because D-2 makes every timer case fail by
construction; with `--timers` the failures are all D-2 and carry no new
information.

**This is a genuinely strong result** for the quiescent-boundary case, and it
is the case the library's own tests cover.

### 2.2 Differential: crash *inside* a macrostep

`t8_midstep_property.py` — **hypothesis, 2,000 cases**. A snapshot is taken at
the *n*th action executed (via `on_action_execute`, a documented public hook —
no monkeypatching) and classified against the minimum necessary property: the
recorded configuration must be non-empty and must have exactly one active leaf
per parallel region.

```
cases=2000  snapshots taken=447
  legal          : 279
  EMPTY config   : 100
  missing region :  68
  snapshot raised:   0
  => 168/447 = 37.6% TORN
```

`t6_action_boundary.py` shows the same on one realistic run: **2 of 6**
snapshots are torn, both while entering `submitted`.

**Not one torn blob is rejected by `from_snapshot()`.**

### 2.3 Targeted probes (`t3_probes.py`)

| Probe | Verdict | Evidence |
|---|---|---|
| **P1** deferral buffer round-trips | **PASS** | 2 held events persisted with `kind`, `deferred_count` 2→2, replayed correctly on `SUBMIT` (`filled=5`) |
| **P2** `wait=True` awaiter at crash | **INFO** | see §2.4 |
| **P3** in-flight invoke | **INFO** | see §2.5 |
| **P4** v1 → v2 upcast | **INFO** | see D-4 |
| **P5** v2 round-trip, all classes | **FAIL** | `AfterEvent.scheduled_for`/`fired_at` lost → D-7 |
| **P6** hash drift refused | **PASS** | `SnapshotDriftError` with both hashes and the remedy |
| **P6b** `verify_machine_hash=False` | **INFO** | resumes on the new shape as documented |
| **P6c** cosmetic edit still restores | **PASS** | `description` correctly excluded from the hash |
| **P8** 1 MB context | **PASS** | 1,049,107 B, snapshot 7.9 ms, restore 4.4 ms, byte-intact |
| **P9** child actors across restore | **PASS** | spawned **and** invoked child both persisted, restored, context intact |
| **P9b** restored child accepts events | **PASS** | `BUMP` increments both children post-restore |
| **P10** bounded inbox persisted | **PASS** | `max_queue_size=4` + `DROP_NEWEST`: the 4 accepted events persist exactly |

### 2.4 What a `wait=True` awaiter gets when the process dies — **documented**

This was called out in the brief as "document". The answer is **good**, and it
is the one part of the crash path that is unambiguously well-engineered.

From `t5_midmacrostep.py`, with the run loop frozen inside an action and three
`wait=True` sends outstanding (one mid-macrostep, two queued):

```
awaiter GO: RESOLVED Receipt(state_ids=frozenset(), changed=False,
            error=InterpreterStoppedError("Interpreter 'freeze' stopped
            before the event was processed."), deferred=False)
awaiter X:  RESOLVED  (same)
awaiter Y:  RESOLVED  (same)
```

**Every outstanding receipt resolves with `InterpreterStoppedError` — none
hangs.** `_fail_all_receipts()` in `_teardown` is the mechanism. This is the
correct behaviour and it closes the #75/#39 hang for the crash path too.

**The caveat the application must absorb:** the receipt says *"not
processed"*, and for an event that was in the inbox that is true and the event
**is** persisted and **will** be replayed after the restore — so
`InterpreterStoppedError` means *"unknown: possibly replayed later"*, not
*"did not happen"*. There is no correlation id linking the dead awaiter to the
replayed event. Confirmed in `t4_receipts_provenance.py` P11: the event is
replayed on restore and **no receipt is handed to anyone**. This is inherent
to a process crash rather than a library defect, but it is a constraint (§5).

Caveat two: in the *torn* case the receipt's `state_ids` is `frozenset()` —
consistent with D-3 but useless to a caller.

### 2.5 In-flight invoke across a restore — as documented

`d5_invoke_dormancy.py`:

| | `has_dormant_invocations` | `pending_invocations()` | service calls |
|---|---|---|---|
| live, invoke genuinely in flight | `False` | `[]` | 1 |
| restored, pre-`start()` | `True` | `[('order.submitted.exchange.acking','ackSvc','ack_service')]` | 1 |
| restored + `start()`, `restart_services=False` | `True` (forever) | as above | 1 |
| restored + `start()`, `restart_services=True` | `False` | `[]` | **2** |

This matches #44's documentation exactly, including the honest warning that
`status` is not a liveness signal after a restore. The `restart_services=True`
re-run is from scratch and the docs say so. **No defect**; it is a constraint
(CV-C07 must carry an idempotency key — §5).

Note the snapshot contains **no record of the invoke itself** — no call id, no
started-at. Dormancy is re-derived from the configuration. That is sufficient
for "something was parked here" and insufficient for "was the exchange call
actually placed?", which is why the reconciliation must be external.

### 2.6 Corrupt and truncated blobs (`t3_probes.py` P7)

17 mutations. **Well-handled (4):** truncated, empty, `null`, a JSON list —
all `InvalidConfigError`, i.e. catchable as `XStateMachineError`, exactly as
the source comment promises. **Correctly refused (3):** unknown state id
(`StateNotFoundError`), `version: 999` (`SnapshotVersionError`), hash drift
(`SnapshotDriftError`).

**Leaks a raw builtin exception (7)** — not catchable via
`XStateMachineError`:

| mutation | raises |
|---|---|
| `context` key missing | `KeyError: 'context'` |
| `state_ids`+`configuration` missing | `KeyError: 'state_ids'` |
| `version: null` | `TypeError: int() argument must be …` |
| `pending_events: 5` | `TypeError: 'int' object is not iterable` |
| pending record missing `type` | `KeyError: 'type'` |
| `deferred: "x"` | `AttributeError: 'str' object has no attribute 'get'` |
| `actors: [1]` | `AttributeError: 'list' object has no attribute 'items'` |

**Silently accepted (3)** — these are the interesting ones:

| mutation | result |
|---|---|
| `status: "banana"` | restored, `interp.status == "banana"` — an invalid status value propagates into a live interpreter |
| `context: 42` | restored, `interp.context == 42` — the `isinstance(dict)` merge guard falls through to a bare assign; every action doing `ctx["x"]` will now `TypeError` at runtime instead of at restore |
| pending record `kind: "wat"` | restored; `restore_event` falls through its `if` ladder and silently produces a plain user `Event` |

Filed as **D-persistence-4** (Medium).

### 2.7 Rollback across the boundary (`t7_rollback.py`)

Correct. After a `rollback`-policy transition whose action raises:

```
receipt = Receipt(state_ids={'rb.a'}, changed=False,
                  error=RuntimeError('action failed'), deferred=False)
states  = ['rb.a']       context = {'n': 0, 'log': []}
SNAPSHOT state_ids = ['rb.a']   context = {'n': 0, 'log': []}
SNAPSHOT pending   = []        <- the withdrawn `raise`d SELF is NOT persisted
restored: states = ['rb.a'], context = {'n': 0, 'log': []}
```

Context is restored, the configuration is restored, and **#27's withdrawal of
the `raise`d event holds across the snapshot** — the withdrawn `SELF` is not
persisted and not replayed. Good.

But the same script shows the tear again: snapshots taken *during* the failing
macrostep record `state_ids=[]` **with half-applied context** (`n=1`,
`log=['bump']`) — a blob that would restore a machine into a state the
rollback was specifically written to prevent.

### 2.8 v1 → v2 upcast, per event class (`t3_probes.py` P4, `t4` P12)

A v1 record has no `kind`, so `restore_event` re-derives provenance **from the
event name** (`events.py:322`). Consequences:

| v1 record | restores as | correct? |
|---|---|---|
| user `Event` | `Event`, `system=False` | ✅ |
| engine-minted `Event` (e.g. `___xstate_init`) | `Event`, `system=True` | ✅ |
| `DoneEvent` | **`Event`**, `system=True` | ❌ class lost |
| `ErrorEvent` | **`Event`**, `system=True` | ❌ class lost — **no `.error`** |
| `AfterEvent` | **`Event`**, `system=True` | ❌ class lost |

The class loss is **not a defect**: 0.8.0 never persisted those classes at all
(that was #86/#87), so no real v1 blob contains one. Recorded for completeness.

The **name-based re-derivation is** a defect. `t4` P12:

```
v1 record 'done.review'   -> Event system=False
v1 record 'after.hours'   -> Event system=True   <-- USER EVENT LAUNDERED
v1 record 'xstate.custom' -> Event system=True
v1 record 'PLAIN'         -> Event system=False
```

A user event named `after.hours` or `xstate.custom`, persisted by 0.8.0 and
restored by this build, comes back flagged **engine-minted** — invisible to
`"*"`, exempt from `strict`, exempt from `onUnhandled`. This is exactly the
#79 defect, reintroduced at the upgrade boundary. Filed as **D-persistence-8**
(Low: it needs a v1 blob *and* an engine-shaped user name, and #79 makes such
names rejected going forward — but a blob written before the upgrade predates
that rejection, which is the whole exposure).

Note `done.review` correctly does **not** launder, because `ENGINE_EVENT_SHAPES`
lists `"done.invoke."`/`"done.state."` and not bare `"done."` — so the
laundering set is `after.*`, `xstate.*`, `___xstate*`, `error.platform.*`,
`done.invoke.*`, `done.state.*`.

---

## 3. Defects

### D-persistence-3 — **Blocker** — a snapshot taken mid-macrostep records an illegal configuration and restores silently

**Repro:** `d3_torn_snapshot.py` (empty), `d3b_partial_parallel.py` (missing
region). Quantified by `t8_midstep_property.py` (**37.6 % of 447 snapshots**).

**Root cause.** `base_interpreter.py:995–1000` —
`get_persisted_snapshot()` reads `self._active_state_nodes` directly, with no
interlock against a macrostep in progress. `_exit_states` and `_enter_states`
are "the sole authorities on `_active_state_nodes` membership — they discard
and add as they go" (`base_interpreter.py:2330`), so between the two the set
is genuinely empty or genuinely half-populated. The source calls that window
"ONE transaction" and rolls it back on action failure
(`base_interpreter.py:2338–2418`) — but a *read* from outside the transaction
is not defended, and an `await` inside any user action (or any `invoke`
handler, or any `await asyncio.sleep(0)`) makes that window arbitrarily long
and schedulable.

`from_snapshot()` then performs **no validity check on the restored
configuration**: `base_interpreter.py:1208–1221` accepts any list of resolvable
ids, adds their ancestors, and returns. An empty `configuration` list is
simply an empty loop.

**Failure scenario (d3, verbatim output):**

```
MID-MACROSTEP snapshot:
   state_ids    = []
   configuration= ['torn']
   status       = running
RESTORED from the torn snapshot:
   states                 = []
   status                 = running
   error                  = None
   has_dormant_invocations= False
   send('PING') receipt   = Receipt(state_ids=frozenset(), changed=False,
                                    error=None, deferred=False)
   states after PING      = []
```

A machine that reports itself perfectly healthy on every available signal and
will never transition again.

**Failure scenario (d3b — operationally worse, because the blob looks fine):**
a snapshot taken during the `exchange` region's `onDone` records
`state_ids=['order.submitted.risk.checking']` — the entire `exchange` region
absent — and `configuration` even contains `order.submitted.exchange` (the
region node) while containing none of its children. Restored:

```
   states = ['order.submitted.risk.checking']  status = running  error = None
   RISK_OK receipt: True | FILL: changed=False deferred=True | DONE: deferred=True
   filled = 0   (uninterrupted run: 3)
```

**The order can never fill and can never complete.** `onUnhandled: "defer"` —
the policy chosen precisely to avoid losing events — turns every exchange
event into a silent deferral, so the failure produces no error, no log, no
hook. Real money, silently stuck.

**Why Blocker.** A crash is by definition an interruption at an arbitrary
moment. Every persistence strategy that survives a crash (a periodic
checkpointer, a plugin that snapshots on transition, a shutdown handler racing
a SIGTERM) can and will land in this window; at 37.6 % the odds are not
remote. The two reasonable fixes are both cheap: (a) make
`get_persisted_snapshot()` refuse or wait while `self._processing` is true,
and (b) have `from_snapshot()` validate that the restored configuration is
legal — non-empty, with exactly one active leaf per region of every active
parallel state — and raise `SnapshotDriftError`/a new
`SnapshotIntegrityError` otherwise. (b) alone converts a silent corruption
into a loud one, which for an OMS is the whole difference.

---

### D-persistence-2 — **High** — `after` timers are not re-armed by a restore, in either mode, with no signal

**Repro:** `d2_after_timer_lost.py`. Also the only 2 failures in
`t1_crashpoints.py`.

```
REFERENCE  after 6 s : ['timeout_demo.expired'] fired = True
  restart_services=False: dormant=False pending_invocations=[] clock.pending=0
  RESTORED after 11 s: ['timeout_demo.waiting'] fired = False  status=running
  restart_services=True:  dormant=False pending_invocations=[] clock.pending=0
  RESTORED after 11 s: ['timeout_demo.waiting'] fired = False  status=running
```

**Root cause.** `from_snapshot()`'s docstring
(`base_interpreter.py:1120–1123`) states that "no invoked service **or `after`
timer** is restarted", so the static default is deliberate and documented.
Two things make it a defect anyway:

1. **There is no opt-in.** `restart_services=True` re-drives invokes
   (`_restart_dormant_invocations`, `base_interpreter.py:1340`) and walks
   `state.invoke` only — it never touches `state.after`. There is therefore
   **no supported way** to restore a machine with its timeouts live. The
   parameter name reads as "services", but a user restoring a machine with
   both an invoke and an `after` gets one of the two re-armed and no hint
   about the other.
2. **There is no signal.** `pending_invocations()` /
   `has_dormant_invocations` — the two APIs #44 added precisely so that "the
   configuration claims work is in flight that nothing is running" is
   observable — model invokes only. A dormant `after` is invisible:
   `dormant=False`, `pending_invocations=[]`, `clock.pending=0`. A health
   check built on the documented liveness signal returns green.

**Impact on the order path.** `after` is how an exchange-ack timeout is
expressed (B-series contracts). A crash during `acking` produces an order
that sits in `acking` forever — the timeout that exists to catch a
non-responding exchange is exactly what the crash deletes.

**Fix shape:** re-arm `after` timers alongside invokes under a
`restart_timers=` flag (or fold into `restart_services` and rename), *and*
extend the dormancy report to timers so the static default is at least
observable.

---

### D-persistence-6 — **High** — the priority (timer) lane is never persisted, so an already-fired `after` is lost too

**Repro:** `d6_priority_lane.py`.

```
timer HAS fired; the AfterEvent is in the priority lane:
   _priority_queue = ['after.1000.lanes.waiting']
   pending_events  = []
   SNAPSHOT pending_events = []
   SNAPSHOT deferred       = []
restored: states = ['lanes.waiting'] fired = 0
   after a further 60 s of virtual time: ['lanes.waiting'] fired = 0
```

**Root cause.** `Interpreter` runs three queues: the inbox
(`_event_queue`), the priority lane (`_priority_queue`, `interpreter.py:219`,
where #48 delivers a fired `AfterEvent` so it cannot queue behind bulk
traffic) and the internal lane (`_internal_queue`, for `raise`).
`_snapshot_pending_events()` (`interpreter.py:1017–1026`) reads **only** the
inbox. `get_persisted_snapshot()` therefore omits the priority lane entirely.

The internal lane's omission is deliberate and annotated in the source —
`"mid-macrostep state; never persisted"` (`interpreter.py:995`) — and is
defensible. **The priority lane has no such annotation and is not
mid-macrostep state:** the deadline has genuinely elapsed and the engine has
committed to delivering the event. Dropping it is the same class of silent
loss that #47 (persist the inbox) and #86/#87 (persist every event class)
were filed to close; the third queue was simply not considered.

**Compounding.** D-2 loses the timer before it fires; D-6 loses it after. For
an `after`-driven timeout **there is no window in which a crash is
survivable**. That is why these are filed separately at High rather than
merged.

---

### D-persistence-4 — **Medium** — `from_snapshot()` accepts three classes of malformed blob and leaks raw builtins for seven more

**Repro:** `t3_probes.py` P7 (17 mutations, table in §2.6).

**Silently accepted:** `status: "banana"` → a live interpreter whose `status`
is not one of the four documented values; `context: 42` → a non-mapping
context assigned straight onto a live interpreter (the
`isinstance(interpreter.context, dict) and isinstance(restored, dict)` guard at
`base_interpreter.py:1195` falls through to a bare assignment on the `else`
branch instead of rejecting); a pending record with `kind: "wat"` → falls off
the end of `restore_event`'s `if` ladder (`events.py:326–335`) and becomes a
plain user `Event`, so an unrecognised future kind is silently downgraded
rather than refused.

**Leaks raw builtins** (`KeyError`, `TypeError`, `AttributeError`) for seven
shapes, defeating `except XStateMachineError` — the documented way to catch
this library's failures, which the source explicitly cites as the reason
`json.JSONDecodeError` was wrapped (`base_interpreter.py:1165–1169`). The
wrap was applied to the decode step and not to the field reads that follow.

Not High because a corrupt blob usually means a corrupt store, and the four
realistic corruption shapes (truncation, empty, wrong type, wrong version) are
all handled correctly. It is Medium because `status` and `context` acceptance
put an invalid object into service.

---

### D-persistence-1 — **Medium** — `from_snapshot()` has no `clock=` parameter, so virtual time cannot be restored through any public API

**Repro:** `harness.py:72` (`attach_clock`) exists solely because of this.

`Interpreter.__init__` takes `clock=` (`interpreter.py:182`); `from_snapshot`
(`base_interpreter.py:1103–1112`) takes `snapshot_str`, `machine`,
`verify_machine_hash`, `restart_services` — and constructs via `cls(machine)`
(`base_interpreter.py:1186`), so a restored interpreter **always** gets a
`RealClock`. Nor is virtual time itself persisted: the snapshot has
`taken_at` (wall clock, `time.time()`) but no clock reading.

Consequences: (a) a `SimulatedClock`-driven test suite cannot test its own
restore path without private-attribute surgery — which is likely why D-2
and D-6 have no library test; (b) any application on a custom `Clock` (the
#49/#76 feature) loses it on every restore and silently reverts to real time.

Medium rather than High because the workaround is two attribute assignments
and most production users are on `RealClock` anyway — but the feature whose
whole purpose is deterministic time has a hole exactly where determinism
matters most.

---

### D-persistence-7 — **Medium** — `AfterEvent` lateness telemetry does not survive a snapshot

**Repro:** `t3_probes.py` P5.

```
[FAIL] P5 v2 round-trip: AfterEvent lateness lost: 1.0/2.0 -> 0.0/0.0
```

**Root cause.** `persist_event` (`events.py:284–297`) writes only `kind` and
`type` for an `AfterEvent`; `restore_event` (`events.py:330–331`) reconstructs
`AfterEvent(type=etype)`, defaulting `scheduled_for` and `fired_at` to `0.0`.

`AfterEvent.scheduled_for` / `fired_at` / `lateness_ms` were added by #48
specifically so an application can **alarm on timer starvation instead of
inferring it from symptoms**. A restored deadline event reports
`lateness_ms == 0.0` — i.e. "perfectly on time" — for a timer that may have
been hours late. The metric silently reports the best possible value in
exactly the degraded condition it exists to detect.

Two lines in the codec. Note this is currently unreachable in practice
*because* of D-6 (a fired `AfterEvent` is never persisted at all) — fixing D-6
without this makes it live.

---

### D-persistence-8 — **Low** — a v1 blob launders an engine-shaped user event into a system event

**Repro:** `t4_receipts_provenance.py` P12.

```
v1 record 'after.hours'   -> Event system=True   <-- laundered
v1 record 'xstate.custom' -> Event system=True
```

**Root cause.** `restore_event`, `events.py:320–323`:

```python
if kind is None:  # v1 record
    kind = "system" if etype.startswith(ENGINE_EVENT_SHAPES) else "event"
```

The source comment defends this as "the one place a name is all we have, and
only at this boundary", which is a fair argument — but it means a user event
persisted by 0.8.0 under an engine-shaped name is restored with forged
provenance, bypassing `strict`, `onUnhandled` and `"*"`. That is the #79
defect, at the upgrade boundary.

Low because it requires a real v1 blob containing such an event, and #79 now
rejects those names on `send()` — but a v1 blob is by construction older than
that rejection, which is the exposure. The safe default at this boundary is
`"event"` (user traffic): a genuine engine event restored as user traffic is
*loud*; a user event restored as engine traffic is *silent*.

---

## 4. What was covered, and what was not

### Covered

- Quiescent-boundary crash consistency: **2,000 hypothesis cases, 0
  divergences** in state / context / action trace / status, plus 22 exhaustive
  hand-built crash points.
- Mid-macrostep interruption at action boundaries: **2,000 hypothesis cases**,
  via the public `on_action_execute` hook.
- Deferred buffer (persisted, counted, replayed correctly on unblock).
- Bounded inbox + `DROP_NEWEST` (accepted events persist exactly).
- `wait=True` receipts at crash — **documented in §2.4**.
- In-flight invoke: `pending_invocations()`, `has_dormant_invocations`,
  `restart_services` both ways — **documented in §2.5**.
- `after` timers with `SimulatedClock`, both before and after firing.
- Child actors, **spawned and invoked**, across a restore, including driving
  them afterwards.
- v1 → v2 upcast and v2 round-trip for **all five event classes**.
- Machine-hash drift: behavioural edit refused, cosmetic edit accepted,
  `verify_machine_hash=False` escape hatch.
- 17 corrupt / truncated / type-confused blobs.
- 1 MB context.
- `actionErrorPolicy: "rollback"` across the boundary, including #27's
  raised-event withdrawal.

### Not covered — stated plainly

- **`SyncInterpreter`.** Every result here is the async engine. Given the
  round-3 history of sync/async divergence (#77, #99, #31), the sync engine's
  persistence path needs its own pass. In particular `SyncInterpreter` has no
  priority lane in the same shape, so D-6 may not transfer, and D-3 almost
  certainly does (the same `_exit_states`/`_enter_states` code in
  `base_interpreter.py` is shared).
- **Full replay-equivalence for mid-macrostep snapshots.** §2.2 measures the
  *necessary* property (the configuration is legal). A torn blob fails that,
  so the stronger property is moot for 37.6 % of cases; for the remaining
  62.4 % it was not separately verified.
- **Real concurrency.** Everything is single-loop with `SimulatedClock`. No
  test of a snapshot taken from another thread via `send_threadsafe`, and no
  test under `RealClock` timing pressure.
- **A cyclic actor graph.** `get_persisted_snapshot`'s `seen` cycle guard
  (`base_interpreter.py:974`) and its `{"ref": …, "cycle": True}` record were
  not exercised; nor was `_pending_actor_snapshots` (the unresolvable-actor
  path) — P9 restored cleanly and never hit it.
- **Deep actor hierarchies** (>1 level) and actor-id collisions across a
  restore.
- **Snapshot size/latency beyond 1 MB**, and no memory-growth measurement over
  repeated snapshot/restore cycles.
- **`output` and `error` restoration** for a machine snapshotted in `done` /
  `error` status.
- **History states across a restore.** `history` is persisted and restored in
  the code path, but no test here drives a transition to a history target
  after a restore.

---

## 5. Constraints we would need

If the library is adopted for the order path with these defects open, all of
the following are mandatory, and **CV-P01 is not implementable as a
constraint** — it needs a library fix.

- **CV-P01 (blocked on D-3).** *"Only snapshot at a quiescent boundary"* is
  not a constraint we can honour, because a crash is not something we
  schedule. The only in-house mitigation is to **validate every blob before
  restoring it** — reject an empty `configuration`, and reject any active
  parallel state that does not have exactly one active leaf per region — and
  treat a rejected blob as "fall back to the previous good checkpoint and
  reconcile against the exchange". That is ~30 lines and it converts D-3 from
  silent corruption to a loud, recoverable one. It belongs in the library.
- **CV-P02 (D-2/D-6).** Never express an order-lifecycle timeout with `after`
  alone. Every deadline that matters must be **externally durable** (a
  scheduled job / a `deadline_at` column) and re-asserted after every restore,
  because the library's timer does not survive a crash in any window.
- **CV-P03 (D-1).** Wrap `from_snapshot()` in a helper that re-attaches our
  `Clock` (the `attach_clock` shape in `harness.py:72`) and pin it with a test,
  since it depends on two private attributes and will break without notice.
- **CV-P04 (§2.4).** `InterpreterStoppedError` on a receipt means
  **"unknown — possibly replayed after restore"**, never "did not happen".
  Every `wait=True` caller on the order path must carry its own idempotency
  key and reconcile, because the replayed event gets no receipt and nothing
  correlates it to the dead awaiter.
- **CV-P05 (§2.5, existing CV-C07).** `restart_services=True` re-runs the
  service **from scratch**. The exchange call must be idempotent on a
  client-supplied key. Confirmed: `d5_invoke_dormancy.py` shows calls 1 → 2.
  Also: `has_dormant_invocations` tells us an invoke is parked, never whether
  the side effect happened — reconciliation is external, always.
- **CV-P06 (D-4).** Wrap `from_snapshot()` in `except Exception`, not
  `except XStateMachineError`, and independently assert `status in
  {"running","done","error","stopped"}` and `isinstance(context, dict)` after
  restore.
- **CV-P07 (D-8).** If any stored blob predates the 0.8.1 upgrade, migrate it
  explicitly rather than relying on `upcast()`; never name a user event with
  an engine shape.

---

## 6. Recommended disposition

| ID | Sev | One line | Action |
|---|---|---|---|
| **D-persistence-3** | **Blocker** | mid-macrostep snapshot records an illegal configuration; restored silently as a healthy-looking dead machine (37.6 % of 447) | **new issue**, with `d3_torn_snapshot.py` + `d3b_partial_parallel.py` + the 2,000-case measurement |
| **D-persistence-2** | High | `after` timers never re-armed on restore, no opt-in, invisible to `pending_invocations()` | **new issue** |
| **D-persistence-6** | High | the priority lane is not persisted, so an already-fired `after` is lost too | **new issue** |
| **D-persistence-4** | Medium | `from_snapshot()` accepts `status`/`context`/`kind` garbage; leaks raw builtins for 7 shapes | **new issue** |
| **D-persistence-1** | Medium | `from_snapshot()` has no `clock=`; virtual/custom time cannot be restored publicly | **new issue** |
| **D-persistence-7** | Medium | `AfterEvent` lateness telemetry resets to 0.0 across a snapshot | **new issue** (fold into D-6's fix) |
| **D-persistence-8** | Low | v1 blob launders an engine-shaped user event into a system event | **ride-along on #79/#86** |

**Gate impact.** D-persistence-3 is a Blocker on the persistence path, which
CV-C08 makes load-bearing for the order lifecycle. Under the
`26-verify-3c527b0-verdict.md` decision table, a Blocker is dispositive
regardless of the High count: **the library-adoption half stays DEFER**, and
the in-house shim (ADR-0016 Part 2) remains the execution path. The three
snapshot-path defects are all cheap to fix, and a `from_snapshot()`
configuration-legality check alone would move D-3 from Blocker to Medium.

**What is genuinely good here, and should be said:** the v2 layout is
well-designed and the #86/#87 work is correct; the hash is scoped exactly
right (behaviour in, cosmetics out); receipts fail loudly rather than hanging
at teardown; child-actor persistence is complete including invoked children;
the deferral buffer and bounded inbox round-trip exactly; 1 MB of context
costs 8 ms; and 2,000 randomised quiescent-boundary crashes produced **zero**
divergence in state, context or emitted-effect trace. The format is sound. The
defect is that nothing guards *when* it is captured.
