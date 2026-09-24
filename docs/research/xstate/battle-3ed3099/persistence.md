# Battle-test track: PERSISTENCE & crash consistency — re-run on `3ed3099`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`3ed3099`** (merge of PR #139, `fix/0.8.1-round4`), CHANGELOG
`[Unreleased] — targeting 0.8.1`. **`__version__` still reports `0.8.0`; this
build is identified by commit, never by version string.**

**Date:** 2026-09-19 · **Python:** CPython 3.13.7 · **OS:** Windows 11 Pro
10.0.26200 · **Interpreter:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

No library source was modified. No `git` command was run in the CandleViewer
repository. GitHub was read-only throughout.

Scripts: `docs/research/xstate/battle-3ed3099/persistence/`.
Predecessor: `battle-5e07ba8/persistence.md` + `persistence.triage.md`.

---

## 0. Bottom line

**The round-4 persistence work is real and it lands. The Blocker is
downgraded, not closed.**

Five of the seven prior defects are **FIXED** and the fixes are not cosmetic —
each was re-attacked by a route the original repro did not use, and each held:

- `restart_timers=` / `has_dormant_timers` (#128) close D-2 completely, and
  the re-arm is measurably *from zero* as documented, in both regions of a
  parallel state.
- `from_snapshot(clock=)` (#117) closes D-1; `harness.attach_clock()`'s
  private-attribute surgery is no longer needed anywhere.
- The priority lane *is* persisted (#107) and replayed, by both a unit route
  and an end-to-end route where a real `after` fires while the loop is parked
  inside an `await`ing action. D-6 is closed.
- `AfterEvent` lateness round-trips (#118). D-7 is closed.
- `SnapshotMidStepError` (#102) closes the *globally-empty* tear: **0** empty
  configurations in 179 action-boundary snapshots, against 100/447 before.

And the headline property the brief asked for **passes at full scale**:
**2,000 events, a snapshot at every one of the 2,000 quiescent points, a full
restore-and-compare at every one — 2,000/2,000 snapshots succeeded, zero
`SnapshotMidStepError` at quiescence, zero round-trip mismatches** (`n2`,
24 s). A 150 s chaos soak did 5,192 snapshots and 3,564 restore-and-resume
cycles with **zero** raw exceptions, zero mismatches and flat memory (`n9`).

**But the #102 guard is `any(leaf)`, not `one leaf per region`.**

```python
# base_interpreter.py:1112
def _active_leaf_present(self) -> bool:
    return any(not node.states or node.is_final
               for node in self._active_state_nodes
               if node is not self.machine)
```

In a **parallel** state, a macrostep mid-way through one region leaves the
*other* region's leaf active, so `any(...)` is `True`, the guard passes, and
the snapshot records a configuration with a whole region missing. **27.4 %
of action-boundary snapshots (49/179) still record an illegal
configuration**, all of them missing-region, and every one restores without
complaint into a machine that reports `running` and silently defers every
event belonging to the absent region. `d3b_partial_parallel.py` — the prior
D-3b repro — reproduces **verbatim**, unchanged.

This is the same defect class as the old Blocker, narrowed from "any machine"
to "any machine with a parallel state". The CandleViewer order path
(`order.submitted` is parallel: `exchange` × `risk`) is exactly that shape,
so the operational exposure on *our* machine is undiminished — but the
blast radius across the library's user base is genuinely smaller, and the
fix is a one-word change (`any` → per-region), so it is filed **High**, not
Blocker.

Two smaller new findings: `check_shape()` does not validate `version`,
`actors` or `system`, so **545/5,000 fuzzed blobs (10.9 %) still leak a raw
builtin** past `except XStateMachineError`; and **#113's non-`str` event-type
guard is enforced on `send()` but not on the restore path**, which is the
half that matters, since a blob arrives from outside the process.

**Four defects: 0 Blocker, 1 High, 2 Medium, 1 Low.**

---

## 1. Method

Machine, harness and comparison technique are unchanged from
`battle-5e07ba8/persistence.md` §1 — `order_machine.py` (parallel
`submitted` region, `invoke` with `onDone`/`onError`, two `after` timers,
machine-level `onUnhandled: "defer"`, `SimulatedClock` throughout), and the
`TraceP` plugin collecting the emitted-action trace through the public
`PluginBase.on_action_execute` hook.

**Two adaptations were required by this round's behaviour changes**, both
recorded in the prior-defect table below:

1. `d3_torn_snapshot.py` and `t5_midmacrostep.py` now terminate on an
   *expected* `SnapshotMidStepError` instead of printing a torn blob. That
   raise **is** the #102 fix, so the scripts are left unmodified and their
   traceback is read as a PASS. Their intent — "a torn blob must not be
   producible" — is met.
2. `d6_priority_lane.py`'s freeze technique (cancel `_event_loop_task`, set
   `_processing = True`) no longer parks a fired `AfterEvent` in
   `_priority_queue` on this build, because #114 now flips `status` and fails
   receipts on a cancelled loop. The old script therefore prints an empty
   lane and proves nothing either way. It is **superseded by
   `n1_priority_lane_107.py`**, which tests the #107 claim by two independent
   routes, one of which (route B) uses no private surgery at all.

### Exact commands

```
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
PYTHONPATH=/c/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src \
"C:/.../.venv-main/Scripts/python" <script>
```

### Parameter reductions (stated as required by the brief)

| Script | Brief / prior | Run here | Why |
|---|---|---|---|
| `n9_soak.py` | 12 min | **150 s + 300 s** (two runs) | task wall-clock bound. Both PASS; the 300 s run contributed the memory series, the 150 s run the counters. At 5,192 snapshots / 3,564 restores in 150 s the *cycle count* far exceeds what 12 min of a slower workload would reach, so the reduction costs duration-dependent coverage (slow leaks, timer drift over minutes) but not cycle coverage. |
| `n3_parallel_tear.py` | prior `t8` used 2,000 hypothesis cases | **300 runs / 179 snapshots** | time bound. Result (27.4 % torn) is the same order as the prior 37.6 %/447 and 41.3 %/150 measurements; the composition, not the exact rate, is the finding. |
| `n5_corrupt_fuzz.py` | brief: 5k mutations | **5,000** — not reduced | |
| `n2_quiescent_property.py` | brief: 2k-event run | **2,000 events, restore at every one** — not reduced | |
| `n8_determinism.py` | brief: 50x both engines | **50x both engines** — not reduced | |
| `t8_midstep_property.py` | 2,000 cases | **not re-run**; superseded by `n3` | `n3` measures the same property with a classifier that distinguishes D-3 from D-3b, which is the distinction this round turns on. |

---

## 2. Prior defects: FIXED / STILL-PRESENT / CHANGED

| ID | Prior sev | Verdict | Evidence |
|---|---|---|---|
| **D-persistence-3** (mid-macrostep snapshot records an illegal configuration) | **Blocker** | **CHANGED — partially fixed; surviving half re-filed as D5-persistence-1** | `d3_torn_snapshot.py` now raises `SnapshotMidStepError` (globally-empty case closed). `t6_action_boundary.py`: **2/6 refused, 0/6 torn** (was 2/6 torn). `n3`: **0** EMPTY configurations in 179 snapshots (was 100/447). **But** `d3b_partial_parallel.py` reproduces verbatim and `n3` finds **49/179 = 27.4 % MISSING_REGION**. |
| **D-persistence-2** (`after` timers never re-armed on restore) | High | **FIXED** | `n4`: `restart_timers=True` re-arms; measured from-zero (`+1.5 s` after restoring a snapshot taken 4 s into a 5 s deadline → `fired=0`; `+5.5 s` → `fired=1`); `has_dormant_timers` is `True` after a static restore, `False` after a re-arm, `False` on a timer-less machine; the default correctly follows `restart_services` across all 6 flag combinations; both regions of a parallel state re-arm (`a=1 b=1`). `t1_crashpoints.py --restart`: **22/22** (was 20/22). |
| **D-persistence-6** (priority/timer lane never persisted) | High | **FIXED** | `n1` route A: `_priority_queue=['after.1000.lanes.waiting']` → `SNAPSHOT pending_events=['after.1000.lanes.waiting'] kinds=['after']` → restored machine reaches `lanes.expired`, `fired=1`. Route B (no private surgery): a real 1 s `after` fires while the loop is parked inside an `await`ing action; the snapshot carries it and the restore replays it. |
| **D-persistence-4** (malformed blobs silently accepted / raw builtins leaked) | Medium | **CHANGED — silent-acceptance fixed, raw leaks remain; re-filed as D5-persistence-3** | `t3_probes.py` P7: all three prior silent acceptances are now typed — `status: "banana"` → `SnapshotCorruptError`, `context: 42` → `SnapshotCorruptError`, `pending_events: 5` / missing `type` → `SnapshotCorruptError`. **But** `actors: [1]` still leaks `AttributeError`, `version: null` still leaks `TypeError`, and `n5` (5,000 mutations) finds **545 raw leaks (10.9 %)** across `version` (TypeError/ValueError, 227) and `actors`/`system` (AttributeError, 318). Crucially, **0/2,592 accepted blobs were unsound** — no accepted mutation produced an invalid `status`, a non-dict `context`, or an unusable interpreter. |
| **D-persistence-1** (`from_snapshot()` has no `clock=`) | Medium | **FIXED** | `n4` test A: `from_snapshot(..., clock=c2)`; `i2.clock is c2` → `True`; virtual time drives the restored machine to `t1.expired`. `harness.attach_clock()` is no longer used by any new script. |
| **D-persistence-7** (`AfterEvent` lateness resets to 0.0) | Medium | **FIXED** | `t3_probes.py` **P5 now PASS** ("all classes round-trip"; was the one FAIL). `n1` route C: `{'kind': 'after', 'type': ..., 'scheduled_for': 1.0, 'fired_at': 2.0}` → `AfterEvent scheduled_for=1.0 fired_at=2.0`. |
| **D-persistence-8** (v1 blob launders an engine-shaped user event) | Low | **STILL-PRESENT — unchanged** | `t4_receipts_provenance.py` P12: `after.hours` → `system=True`, `xstate.custom` → `system=True`, `done.review` correctly `system=False`. Identical to the prior result. Assessment unchanged: needs a pre-0.8.1 blob containing a user event with an engine-shaped name; #79 closes the intake path for new events. Re-filed as **D5-persistence-4 (Low)**. |

### Regression check on the previously-clean results

| Script | Prior | Now |
|---|---|---|
| `p0_smoke.py` | layout `version == 2` | unchanged, `version == 2` |
| `t1_crashpoints.py` | 20/22 (both modes) | **20/22** static, **22/22** `--restart` (the 2 static failures are the documented static-restore default, not D-2) |
| `t3_probes.py` P1/P6/P6b/P6c/P8/P9/P9b/P10 | PASS | **all still PASS**; P8 got faster (snapshot 7.9→4.5 ms, restore 4.4→2.6 ms for 1 MB) |
| `t7_rollback.py` | correct post-rollback restore; torn mid-macrostep | post-rollback restore still correct; the mid-macrostep snapshots are now **refused** |
| `d5_invoke_dormancy.py` | as documented | unchanged; `restart_services=True` still re-runs the service (calls 1→2) — CV-P05 stands |

---

## 3. New attacks

| # | Script | Attack | Result |
|---|---|---|---|
| N1 | `n1_priority_lane_107.py` | #107 priority lane persisted + replayed, two independent routes; #118 lateness round-trip | **PASS** (3/3) |
| N2 | `n2_quiescent_property.py` | **2,000-event run; snapshot at every quiescent point; full restore-and-compare at every one**; `SnapshotMidStepError` must never fire at quiescence | **PASS** — 2,000/2,000 snapshots OK, **0** mid-step raises, **0** other raises, 2,000 restores, **0** mismatches, 24.0 s |
| N3 | `n3_parallel_tear.py` | quantify what the #102 guard still admits, classified EMPTY (D-3) vs MISSING_REGION (D-3b) | **FAIL** — 179 snapshots: 59 legal, 71 refused, **0 EMPTY**, **49 MISSING_REGION (27.4 %)** → **D5-persistence-1** |
| N4 | `n4_restart_timers.py` | `restart_timers=` × `restart_services=` matrix, `has_dormant_timers`, from-zero re-arm measured, `from_snapshot(clock=)`, parallel regions | **PASS** (5/5) |
| N5 | `n5_corrupt_fuzz.py` | **5,000 structural mutations**; bucket TYPED / RAW / ACCEPTED, and probe every ACCEPTED blob for soundness | **PARTIAL** — 1,863 typed, **545 raw leaks (10.9 %)**, 2,592 accepted of which **0 unsound** → **D5-persistence-3** |
| N6 | `n6_hostile_and_hooks.py` | `InvalidEventError` over hostile types (live + restore); `SnapshotSerializationError`; hook matrix incl. `on_plugin_error`/`last_plugin_error`; `LoggingInspector` redaction; exported API surface | **MIXED** — live `send()` 8/8 genuine hostiles typed; **restore path 0/5** → **D5-persistence-2**. Serialization, hooks, redaction, API surface all **PASS** |
| N7 | `n7_restore_event_type.py` | minimal repro for the restore-path type gap | reproduces 5/5 |
| N8 | `n8_determinism.py` | **50× per engine**, byte-identical canonicalised snapshot blobs | **PASS** — async 50 runs → 1 distinct blob; sync 50 runs → 1 distinct blob |
| N9 | `n9_soak.py` | reduced chaos soak: random bursts, snapshot/restore/resume, virtual-time jumps, flag toggling, RSS + object sampling | **PASS** — 6,456 cycles, 19,471 events, 5,192 snapshots, 3,564 restores, **0** raw exceptions, **0** mismatches, RSS 30.2→33.8 MB and objects flat from the first sample onward |
| N10 | `n10_semantics_persist.py` | this round's semantics fixes in their persistence bearing: #109 output, #108 root target, #130 escalate, #116 inline sync service | **MIXED** — #109, #130, #116 **PASS** (incl. engine parity `n=1`/`n=1` and no double-replay); #108 build-time PASS, **restore-side gap** (folded into D5-persistence-1) |

### Notes on two N6/N10 sub-results that are *not* defects

- `n6` A reports `{'type': 'GO'}` as "ACCEPTED". That is correct and
  documented: `_resolve_event` (`base_interpreter.py:1888`) accepts a dict
  carrying a `type` key. The 8 genuine hostile inputs (`42`, `None`, `3.5`,
  `b"GO"`, `["GO"]`, `object()`, `True`, `(1,2)`) are all typed. Not counted.
- `n8` cross-engine blobs differ because `order_machine`'s `ack_service` is
  `async def`, which `SyncInterpreter` rejects with `NotSupportedError` by
  design. Per-engine determinism — the property under test — is 50/50 on
  both. Not counted.

---

## 4. Defects

### D5-persistence-1 — **High** — the `#102` mid-step guard is `any(leaf)`, so a parallel state can still be snapshotted with a whole region missing

**Repro:** `d3b_partial_parallel.py` (minimal, unchanged from the prior
round), `n3_parallel_tear.py 300` (quantified), `n10_semantics_persist.py`
test B (restore-side half).

**Source:** `base_interpreter.py:1112` `_active_leaf_present()`, consumed at
`base_interpreter.py:1156`.

```python
def _active_leaf_present(self) -> bool:
    """``True`` when the configuration contains at least one atomic
    state -- i.e. it is a legal SCXML configuration (#102/#108)."""
    return any(not node.states or node.is_final
               for node in self._active_state_nodes
               if node is not self.machine)
```

The docstring's claim is the bug: "at least one atomic state" is **not** what
makes an SCXML configuration legal. Legality requires *exactly one* active
leaf **per parallel region**. `any()` is satisfied by a single surviving
region, so the guard passes precisely when the tear is a partial-parallel
tear rather than a total one.

**Measured (`n3`, 300 randomised runs, snapshot at a random action boundary
via the public `on_action_execute` hook — no monkeypatching):**

```
runs=300  snapshots attempted=179
   legal           : 59
   refused         : 71
   MISSING_REGION  : 49

   TORN (accepted illegal configuration) = 49/179 = 27.4%
   of which globally-empty (D-3, expected 0) = 0
   of which missing-parallel-region (D-3b)   = 49
```

**Consequence (`d3b_partial_parallel.py`, verbatim on this build):**

```
snapshot taken during the exchange region's onDone:
   state_ids    = ['order.submitted.risk.checking']
   configuration= ['order', 'order.submitted', 'order.submitted.exchange',
                   'order.submitted.risk', 'order.submitted.risk.checking']
   -> the whole `exchange` region is ABSENT.

restored (no error raised):
   status  = running     error   = None     dormant = False
   RISK_OK receipt: True | FILL: False True | DONE: False True
   filled  = 0 (uninterrupted run: 3)
```

The order can never fill or complete. `status` is `running`, `error` is
`None`, `has_dormant_invocations` is `False` — every health signal the
library offers says the machine is fine, and every exchange event is
silently swallowed by `onUnhandled: "defer"`.

**The restore side has no second line of defence.**
`persistence.check_shape()` (`persistence.py:186`) tests only:

```python
if status == "running" and not (
    snapshot.get("configuration") or snapshot["state_ids"]
):
    fail("status is 'running' but the configuration is empty")
```

— emptiness, never per-region legality. `n10` test B confirms the gap is not
specific to parallel regions: a hand-built blob whose `configuration` is
`["order"]` (the machine root — the exact shape #108 rejects **at build
time**) is **accepted**, producing `status=running` with
`current_state_ids == []`. So the two checks that should catch this
(`_active_leaf_present` at write time, `check_shape` at read time) both miss
the same class.

**Why High and not Blocker.** The prior round's Blocker applied to *every*
machine — 100/447 snapshots recorded a totally empty configuration. That is
closed. What survives needs a parallel state, and the fix is a one-word
change in a single function plus a symmetric read-side check. But
CandleViewer's `order.submitted` **is** parallel (`exchange` × `risk`), so
our own exposure is not reduced at all, and CV-P01 stands unchanged.

**Suggested fix.** Replace `any(...)` with a per-region check — for every
active parallel node, assert each of its regions contributes exactly one
active leaf — and apply the same predicate inside `check_shape()` so a
torn blob is refused on read as well as unproducible on write. The read-side
check also closes the root-only shape from `n10` B.

---

### D5-persistence-2 — **Medium** — `#113`'s non-`str` event-type guard is enforced on `send()` but not on the restore path

**Repro:** `n7_restore_event_type.py` (minimal), `n6_hostile_and_hooks.py`
test A.

**Source:** `events.py:persist_event`/`restore_event` read `record["type"]`
and construct the event with no type check;
`persistence.py:190–196` `check_shape()` asserts the `type` key is
**present**, never that it is a `str`:

```python
for key in ("pending_events", "deferred"):
    val = snapshot.get(key)
    if val is not None and (
        not isinstance(val, list)
        or not all(isinstance(r, dict) and "type" in r for r in val)
    ):
        fail(f"'{key}' must be a list of event records with a 'type'")
```

`#113` added the guard at `base_interpreter.py:1892–1899`, on the `send()`
path only.

```
live send(): typed 8/8 genuine hostiles   (InvalidEventError, also a TypeError)

restore path: typed/refused 0/5
   type=42           ACCEPTED status=running
   type=None         ACCEPTED status=running
   type=['GO']       ACCEPTED status=running
   type={'x': 1}     ACCEPTED status=running
   type=True         ACCEPTED status=running

unit level:
   record type=42   -> Event(type=42, isinstance(str)=False)
   record type=None -> Event(type=None, isinstance(str)=False)
```

**Why this is the half that matters.** `send()` is called by our own code;
a snapshot arrives from Redis, disk or a queue — i.e. from outside the
process, which is precisely the trust boundary `#113` exists to defend. A
restore is the *only* remaining way to get a non-`str` event type into a
live interpreter.

**Observed consequence is currently mild** — the event matches nothing and
is swallowed (`hooks=[]`, not even an `on_event_dropped`), so today it is a
silently-lost event rather than a crash. It is Medium rather than High for
that reason, but the silence is itself part of the defect: a malformed
pending record produces no hook, no log line and no receipt.

**Suggested fix.** Add `isinstance(r["type"], str) and r["type"]` to the
`check_shape()` predicate above, so the blob is refused with the same
`SnapshotCorruptError` as every other malformed record.

---

### D5-persistence-3 — **Medium** — `check_shape()` does not validate `version`, `actors` or `system`, so 10.9 % of fuzzed blobs still leak a raw builtin past `except XStateMachineError`

**Repro:** `n5_corrupt_fuzz.py 5000`; `t3_probes.py` P7 (`actors: [1]`,
`version: null`).

**Source:** `persistence.py:149` `check_shape()` validates `status`,
`context`, `state_ids`, `configuration`, `pending_events`, `deferred` — and
stops. `version` is consumed earlier by `check_version()`
(`persistence.py:138`) as a bare `int(snapshot.get("version", 0))` before
`check_shape()` ever runs. `actors` and `system` are read *after*, at
`base_interpreter.py:1493` and `:1518`, as
`(snapshot.get("actors") or {}).items()`.

```
mutations           : 5000
TYPED (XStateMachineError) : 1863
     SnapshotCorruptError      : 1581
     SnapshotDriftError        :  220
     SnapshotVersionError      :   60
     StateNotFoundError        :    2
RAW builtin leaks          : 545   <- must be 0
     AttributeError            : 318   e.g. actors=True  -> 'bool' object has no attribute 'items'
                                       e.g. system=42    -> 'int' object has no attribute 'items'
     TypeError                 : 167   e.g. version:type->list -> int() argument must be a string...
     ValueError                :  60   e.g. version='wat'      -> invalid literal for int() with base 10
ACCEPTED                   : 2592
  of which UNSOUND         : 0   <- must be 0
```

**This is a genuine improvement over the prior round and should be said
plainly:** all three prior *silent acceptances* are now typed
(`status: "banana"`, `context: 42`, malformed pending records), and — the
result that matters most — **0 of 2,592 accepted mutations produced an
unsound interpreter**. Every accepted blob had a valid `status`, a dict
`context`, and still processed events. The remaining defect is purely that
`except XStateMachineError`, which the source explicitly names as the
documented way to catch this library's failures (`base_interpreter.py:1374`,
the comment justifying the `JSONDecodeError` wrap), does not catch three
field shapes.

**Suggested fix.** Move the `version` read inside a typed wrapper (or
validate it in `check_shape()` before `check_version()` consumes it), and
add `actors` / `system` to `check_shape()`'s mapping checks. Three lines.

---

### D5-persistence-4 — **Low** — a v1 blob still launders an engine-shaped user event into a system event

**Repro:** `t4_receipts_provenance.py` P12. **Unchanged from the prior
round**; carried forward for completeness.

```
v1 record 'done.review'   -> Event system=False
v1 record 'after.hours'   -> Event system=True   <-- USER EVENT LAUNDERED
v1 record 'xstate.custom' -> Event system=True
v1 record 'PLAIN'         -> Event system=False
```

`events.py` re-derives provenance from the event *name* for a v1 record,
which carries no `kind`. There is no other signal available at that
boundary, so this is arguably unfixable as stated — the real remedy is
explicit migration (CV-P07). Exposure requires a pre-0.8.1 blob containing a
user event with an engine-shaped name; `#79` closes the intake path for new
events. Ride-along on #79/#86.

---

## 5. Coverage — and what was NOT covered

**Covered this pass:** every script in `battle-5e07ba8/persistence/` re-run
(15 scripts); all 7 prior defects dispositioned; 10 new attack scripts; a
2,000-event quiescent-snapshot property run with restore-and-compare at every
point; 5,000-mutation corruption fuzz with soundness probing of every
accepted blob; 50× per-engine snapshot determinism; a 150 s + 300 s chaos
soak with memory sampling; the full `restart_timers` × `restart_services`
matrix; the new-error-class hook matrix; redaction; exported API surface.

**NOT covered — stated plainly:**

- **The 12-minute soak was reduced to 150 s + 300 s.** Cycle coverage is high
  (3,564 restores in the 150 s run), but duration-dependent failure modes —
  a slow leak, timer drift accumulating over minutes, a scheduler artefact
  that needs sustained pressure — are **not** ruled out. The memory series is
  flat from the first sample, which is evidence against a leak, not proof.
- **`SyncInterpreter` persistence is thinly covered.** `n8` snapshots a sync
  interpreter and `n10` D checks engine parity on the inline-service path,
  but there is no sync equivalent of `n2`'s 2,000-point property run, and
  the `#122` `tick()` chained-deadline fix was not exercised across a
  restore. The sync engine's `_is_processing` arm of `_step_in_flight()` is
  therefore untested here.
- **Child-actor tear.** `get_persisted_snapshot()` *waits* (bounded) for a
  child caught mid-step rather than failing the parent (the #102
  ride-along). The wait's bound was not stressed, and no test here forces a
  child to stay mid-step past that bound to see what is recorded.
- **Repeated snapshot→restore→snapshot chains over many generations** —
  `n9` does resume-on-restore, but no test drives 50+ generations of the
  *same* logical order to look for cumulative drift in `history` or `actors`.
- **History states across a restore** — still untested, as in the prior
  round: `history` is persisted and restored in the code path, but no test
  drives a transition to a history target after a restore.
- **`output` / `error` restoration** for a machine snapshotted in `done` or
  `error` status.
- **Concurrency items from the brief (#105 per-task gate, #104 BLOCK under
  16 producers) and the fuller determinism/semantics matrices** are the
  concurrency and determinism tracks' scope; only their persistence bearing
  was tested here (`n10`).

---

## 6. Constraints, updated

- **CV-P01 — narrowed, still required.** Validate every restored
  configuration before trusting it. The check shrinks from "reject empty
  configurations *and* verify per-region legality" to **"verify per-region
  legality"** only — the empty case is now refused by the library. Because
  `order.submitted` is parallel, this constraint is **not** relieved.
- **CV-P02 — RELAXED.** `after` timers now survive a crash in both windows:
  before firing (`restart_timers=True`, #128) and after firing (priority lane
  persisted, #107). External durability for order-lifecycle deadlines remains
  *advisable* — a re-armed timer restarts **from zero**, so a 30 s staleness
  deadline crashed at 29 s gets a fresh 30 s — but it is no longer
  *mandatory* to avoid silent loss. Downgrade from must to should.
- **CV-P03 — WITHDRAWN.** `from_snapshot(clock=)` exists (#117). No
  private-attribute surgery needed.
- **CV-P04 — unchanged.** `InterpreterStoppedError` on a receipt still means
  "unknown — possibly replayed after restore". Every `wait=True` caller on
  the order path carries its own idempotency key.
- **CV-P05 — unchanged.** `restart_services=True` re-runs the service from
  scratch (`d5_invoke_dormancy.py`: calls 1→2). Idempotency key mandatory.
  Now also read `has_dormant_timers` alongside `has_dormant_invocations`.
- **CV-P06 — narrowed.** Still wrap `from_snapshot()` in `except Exception`
  rather than `except XStateMachineError` (D5-persistence-3), but the
  post-restore assertions on `status` and `isinstance(context, dict)` are now
  redundant — `check_shape()` enforces both, and 0/2,592 accepted fuzz
  mutations violated them.
- **CV-P07 — unchanged.** Migrate any pre-0.8.1 blob explicitly; never name a
  user event with an engine shape.
- **CV-P08 — NEW.** Validate `pending_events[].type` is a non-empty `str`
  before restoring (D5-persistence-2).

---

## 7. Recommended disposition

| ID | Sev | One line | Action |
|---|---|---|---|
| **D5-persistence-1** | **High** | `#102`'s `_active_leaf_present()` is `any(leaf)`, so a parallel state snapshots with a whole region missing (27.4 % of 179); `check_shape()` has no read-side legality check either | **new issue** — `d3b_partial_parallel.py` + `n3_parallel_tear.py` + `n10` test B; propose per-region predicate applied at both write and read |
| **D5-persistence-2** | Medium | `#113`'s non-`str` event-type guard covers `send()` but not the restore path, the side facing untrusted storage | **new issue** — `n7_restore_event_type.py`; one-line addition to `check_shape()` |
| **D5-persistence-3** | Medium | `check_shape()` omits `version`, `actors`, `system`; 545/5,000 fuzzed blobs leak a raw builtin past `except XStateMachineError` | **new issue** — `n5_corrupt_fuzz.py`; note prominently that 0/2,592 accepted blobs were unsound |
| **D5-persistence-4** | Low | v1 blob launders an engine-shaped user event | **ride-along on #79/#86**, unchanged |

**Gate impact.** The prior round's **Blocker is cleared**. Under the
`26-verify-3c527b0-verdict.md` decision table a High is not dispositive, so
the persistence track no longer forces DEFER on its own. The remaining High
is a one-word predicate change with a symmetric read-side check, and the two
Mediums are three-line additions to a function that already exists.

**Recommendation for the persistence path specifically: move from DEFER to
CONDITIONAL-ADOPT**, conditional on D5-persistence-1 landing, with CV-P01 as
the in-house guard until it does. This is a track-level recommendation; the
overall gate verdict depends on the other tracks' round-5 results, which this
pass did not see.

**What is genuinely good here, and should be said:** #102, #107, #110, #117,
#118, #128 and #131 all do what the CHANGELOG says, and they were verified by
routes their own repros did not use. A 2,000-event run with a snapshot and a
full restore-and-compare at every single quiescent point produced **zero**
failures of any kind. A 150 s chaos soak did 3,564 restore-and-resume cycles
with zero raw exceptions and flat memory. Snapshot blobs are byte-identical
across 50 runs on both engines. 1 MB of context now round-trips in 4.5 ms
(down from 7.9 ms). The corruption path went from three silent acceptances to
zero, and from "7 shapes leak" to "3 fields leak, none of them producing an
unsound machine". The format was already sound; this round largely fixed
*when* it is captured, and the one thing it missed is that `any` is not
`every`.
