# Battle-test track: **DETERMINISM & REPLAY** — `xstate-statemachine` @ `3ed3099`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `3ed3099` ("Merge pull request #139 from basiltt/fix/0.8.1-round4").
`CHANGELOG.md` `[Unreleased] — targeting 0.8.1`; **`__version__` still reports
`0.8.0`** (`__init__.py:195`), so this build is identified **by commit**,
never by version string.

**Date:** 2026-09-19 · **Python:** CPython 3.13.7 · **OS:** Windows 11 Pro 10.0.26200
**Interpreter for every run:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

No library source was modified. No `git` command was run in the adopting
project's repository. GitHub was read-only throughout.

**Predecessor.** This is the round-4 re-run of
`battle-5e07ba8/determinism.md` (defects `D-determinism-1..6`) and its
triage. New defects found in this pass are numbered **`D5-determinism-n`**.

---

## 0. Bottom line

**The round-4 work is a large, genuine improvement on this track. Four of the
six prior defects are FIXED, including both of the two the prior report
considered structural for a replay pipeline.** `Receipt.deferred` is now
stable and truthful; `from_snapshot(clock=)` exists, so checkpoint-and-resume
under a `SimulatedClock` reproduces the straight-through tail *byte-for-byte on
both engines*; the async engine now runs a plain-sync `invoke` inline, so the
`(GO, CANCEL)×10` outcome agrees across engines and across all four call
shapes; and the `___xstate_statemachine_init___` hook record is now emitted by
both engines.

Three defects are new, and one of them is the one that matters:

1. **`restart_timers=True` is a no-op on `SyncInterpreter` + `SimulatedClock`,
   while `has_dormant_timers` reports `False` ("re-armed")**
   (**D5-determinism-1, High**). `SyncInterpreter.start()` returns at
   `sync_interpreter.py:283` on the restored-interpreter path, *before* the
   `self.clock._attach(self.tick)` at `:308`. The timer is armed in the clock
   but nothing settles the interpreter, so `clock.increment(200)` fires
   nothing and the machine sits in `armed` forever. A same-machine control on a
   fresh interpreter fires correctly, and the async engine is correct — so this
   is a sync-engine-only regression on the exact feature (#128) that round 4
   added for restore. **The liveness signal the library itself documents as the
   post-restore check is wrong**, which is silent stalling, not a loud failure.

2. **`from_snapshot()` escapes the `XStateMachineError` hierarchy for 339 of
   5 000 snapshot mutations** (**D5-determinism-2, Medium-High**). #110 promises
   a typed `SnapshotCorruptError`. `persistence.check_version()`
   (`persistence.py:138`) does a bare `int(snapshot.get("version", 0))` *before*
   `check_shape()` runs, so a non-numeric `version` is a raw `ValueError` /
   `TypeError`; `check_shape()` (`:170`) does `status not in _VALID_STATUSES`
   against a `frozenset`, so an unhashable `status` is a raw `TypeError`; and
   `history` is never shape-checked, so a scalar `history` is an
   `AttributeError` deep in the restore. A restore-from-Redis path written as
   `except XStateMachineError:` — the documented way to catch this library's
   failures — misses all of these. Reproduced deterministically, no RNG, in
   `n5b_corrupt_escapes.py` (7/9 hand-written cases escape).

3. **No new error class reaches a plugin hook** (**D5-determinism-3, Medium**).
   `SnapshotMidStepError`, `InvalidEventError` and
   `SnapshotSerializationError` all raise at the call site and emit **nothing**
   to any of the 18 `PluginBase` hooks. An audit log built from hooks — the
   documented observability surface — cannot see that a snapshot was refused or
   that a malformed order event was rejected.

**Two prior findings remain, unchanged and correctly characterised as
constraints rather than bugs:** async scheduling order still decides outcomes
when two coroutines race (`D-determinism-2`, now measured at 7 distinct
outcomes over a 64-point grid, down from 11 but the same class), and
`send_threadsafe()` still does not order against `send()` (`D-determinism-6`,
0/8 FIFO under strict alternation). Both are avoidable by design and are
restated below as adoption constraints.

**What is newly clean and worth saying so.** 2 000 quiescent-point snapshots
per engine: zero `SnapshotMidStepError`, zero round-trip failures, identical
run-to-run (`n1`). 50×50 replay: one digest per engine (`n3`). #116, #109,
#108, #130 all verified fixed (`n3`). #105's per-task gate survives
`create_task`, OS threads and a child actor at `maxIterations: 10` (`n4`);
#104 BLOCK loses nothing under 16 producers (`n4`). `LoggingInspector` redacted
all 12 sensitive keys tested while leaving benign values visible (`n6`); all 17
names promised by #137 are importable and in `__all__` (`n6`).

---

## 1. Method

### 1.1 Fixture and comparison surface

Unchanged from the prior round, so the two reports are directly comparable.
`determinism/dmachine.py` defines one machine (`oms` — a parallel root with
`trading` / `risk` / `actors` regions, machine-level `onUnhandled: "defer"`,
a sync-callable `invoke`, an `after: {50}`, a `raise`, a `sendTo` to a live
child actor) and one seeded event-script generator
(`random.Random(20260918)`), so the script is byte-identical in every process
regardless of `PYTHONHASHSEED`. Every service is a plain sync callable and
every delay is driven by `SimulatedClock`, so both engines can run identical
work. `TracePlugin` digests actions, hooks, transitions, receipts, snapshots
and context per run.

### 1.2 Exact commands

```
cd docs/research/xstate/battle-3ed3099/determinism
PY="<workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1

# --- prior-defect battery (re-run) ---
$PY smoke.py
$PY d1_replay.py --runs 20 --events 1000   # REDUCED (see below)
$PY d2_receipt_deferred.py ; $PY d2b_flag_instability.py ; $PY d2c_deferred_mechanism.py
$PY d3_perturb.py ; $PY d3b_p1_forensics.py ; $PY d3c_abort_race.py
$PY d4_ordering.py ; $PY d5_hashseed.py ; $PY d6_cross_engine.py
$PY d7_hook_parity.py ; $PY d8_sync_invoke_timing.py ; $PY d9_snapshot_replay.py
$PY d10_concurrent.py ; $PY d10b_threadsafe_order.py
$PY d11_construction.py ; $PY d12_after_timer.py

# --- new round-4 attacks ---
$PY n1_quiescent_snapshot.py     # 2000 quiescent snapshots/engine, #102
$PY n2_clock_resume.py           # #117 clock=, #128 restart_timers, resume equivalence
$PY n2b_restart_timers.py        # D5-determinism-1 minimal repro + control
$PY n3_semantics.py              # 50x50 replay + #116/#109/#108/#130
$PY n4_concurrency.py            # #105 per-task gate, #104 BLOCK
$PY n4b_maxiter_forensics.py     # forensics that cleared a false positive
$PY n5_fuzz.py                   # 5000 snapshot mutations + hostile event types
$PY n5b_corrupt_escapes.py       # D5-determinism-2 minimal repro (no RNG)
$PY n6_observability.py          # hook matrix, on_plugin_error, redaction, API
$PY n7_soak.py 720               # 12-min chaos soak, both engines
```

All JSON lands in `determinism/out/`.

### 1.3 Parameter reductions (and why)

The task imposed ≤120 s per script and ~25 min total. Reductions, all stated
so the numbers are not over-read:

| script | prior / brief | this run | effect on conclusions |
|---|---|---|---|
| `d1_replay.py` | 50 runs × 10 000 events | **20 runs × 1 000** | Within-engine stability is now a *positive* result; 20 clean runs plus `n3`'s separate 50×400 campaign cover the same claim. A 50×10 000 campaign would only strengthen an already-clean result. |
| `n3_semantics.py` | 50× byte-identical traces | **50 runs × 400 steps** (both engines) | Keeps the brief's 50× repeat count; shortens the script. |
| `n1_quiescent_snapshot.py` | 2 000-event property run | **2 000 events, full**; round-trip verified at **every 25th** quiescent point (80/engine) | The raise-check (the actual #102 contract) runs at all 2 000; only the expensive restore is sampled. |
| `n5_fuzz.py` | 5 000 mutations | **5 000, full**, but **sync engine only** | The restore path under test lives in `base_interpreter.py` / `persistence.py` and is shared by both engines. |
| `n7_soak.py` | long soak | **12 min** (~6 min/engine) | Enough to confirm invariants and independently re-find D5-determinism-2; **not** enough to claim anything about multi-hour leak behaviour. |

---

## 2. Prior defects — FIXED / STILL-PRESENT / CHANGED

| id | prior severity | verdict | evidence this pass |
|---|---|---|---|
| **D-determinism-1** `Receipt.deferred` nondeterministic (`id()`-keyed leak) | High | **FIXED** | `d2c`: `0/3000` false positives on both engines (was **2 998/3 000** on sync); `leaked ids in _deferred_this_step: 0` (was 11). `d2`: `0/400` false positives, `_deferred_this_step` start=0 end=0. `d2b`: 6/6 runs identical on both engines, `_deferred_this_step=1` stable. `d1`: the `receipts` digest is now **STABLE** over 20 runs per engine (was DIVERGENT, 46–50 distinct over 50). Matches #106/#125. |
| **D-determinism-2** asyncio scheduling changes the OUTCOME | High | **STILL-PRESENT (CHANGED, reduced)** | `d3c`: **7** distinct `{filled, aborted}` outcomes over the 8×8 grid (was **11**), still spanning the full range `20f/0a` → `0f/20a`. The control `d3b` (no competing exit) is now **1 distinct outcome over 10 jitter points** — clean. So the library's own timing is stable; what remains is two genuinely racing coroutines, which no library primitive sequences. **Design constraint, not a patchable bug** — see §6. |
| **D-determinism-3** engines not replay-equivalent on a sync `invoke` | High | **FIXED** | `d8`: async now matches sync at **every** producer gap 0–7 (`{ok:10, cancel:0}`); previously async ranged continuously from `{ok:0,cancel:10}` to `{ok:10,cancel:0}`. `n3` extends this to all four call shapes (`send` each / `send_events`, both engines): **all four agree**, one distinct result. `d6`: all 5 cross-engine scripts agree on context, state *and* trace. Matches #116. |
| **D-determinism-4** sync emits an extra `___xstate_statemachine_init___` hook record | Medium | **FIXED** | `d7`: both traces now contain the init record at index 2; `identical: True`, `async-only records: []`, `sync-only records: []`. Matches #124. |
| **D-determinism-5** `from_snapshot()` cannot take a clock | Medium | **FIXED** | `base_interpreter.py:1301` now has `clock: Optional[Clock] = None`, honoured at `:1405`. `n2`: restored clock is `SimulatedClock` on both engines; the resumed tail is **action-for-action identical** to the straight-through tail (async 330/330, sync 314/314), final snapshots byte-identical, and two resumes from the same bytes are identical. This is the capability the prior report said had "literally no supported path". Matches #117. |
| **D-determinism-6** `send_threadsafe()` does not order against `send()` | Medium | **STILL-PRESENT (unchanged)** | `d10b` case 2 (strict alternation): **0/8 runs FIFO, 8 distinct processed orders** — identical to the prior pass. Case 1 (barrier): 6/8 FIFO, 2 distinct (prior: 7/8, 2 distinct — same behaviour, different draw). Mechanism re-confirmed: `send_threadsafe` schedules a coroutine via `call_soon_threadsafe` rather than enqueueing at the call site. `d10` T3 (4 tasks + 4 threads) likewise 0/10 FIFO, **but 0 lost and fully drained in 10/10** — it is a reordering hazard, never a loss. |

**Prior clean results that stayed clean.** `d4`: all 13 lane-vs-lane ordering
cases **STABLE** over 15 repeats. `d5`: entry/exit/guard/service/actor order and
snapshot `configuration` / `value` keys invariant under `PYTHONHASHSEED` 0–5
(the one "unstable" observable, `current_state_ids_raw`, is raw *set* iteration
order — the persisted `configuration` is sorted and stable, so this is not
replay-relevant). `d11`: `structure_hash` `9592369bfc608303` identical across all
6 seeds. `d12`: `after` under `SimulatedClock` gives `late == 10` on both engines
in all three pump modes. `d10` T1/T2: 2 400 events/run × 10 runs, 10/10 FIFO,
0 lost.

**Adapted scripts.** `d9_snapshot_replay.py` was left as-is (it documents the
old no-`clock=` behaviour in its docstring) and **superseded by `n2`**, which
re-asks the same three questions using the new `clock=` parameter. `d9`'s R3
"resumed trace length 0" is therefore a stale-by-design result, not a finding;
`n2` is the live answer. No script needed adapting for
`SnapshotMidStepError` — none of the prior scripts took a mid-step snapshot.

---

## 3. New attacks

| # | attack | target | result |
|---|---|---|---|
| **N1** | 2 000-event run, snapshot at **every** quiescent point, both engines | #102 | **PASS.** 2 000 quiescent points/engine, **0** `SnapshotMidStepError`, 0 round-trip failures (80 verified/engine), snapshot-sequence digest identical run-to-run (`f167…` async, `4014…` sync). |
| **N1-Q4** | snapshot from *inside* an action (the intended positive) | #102 | **PASS (sync).** `SnapshotMidStepError` raised as designed. On async the probe's action never ran before the drain — **not covered**, see §5. |
| **N2** | `from_snapshot(clock=SimulatedClock())`, checkpoint-and-resume vs straight-through, both engines, ×2 for determinism | #117 | **PASS.** Restored clock is `SimulatedClock`; tails identical; final snapshots identical; resume deterministic. |
| **N2b** | `restart_timers=True` + `has_dormant_timers`, **against a same-machine control** | #128 | **FAIL on sync → D5-determinism-1.** Control fires (`late=1`); restored+`restart_timers=True` does not (`late=0`, stuck in `armed`) while `has_dormant_timers` reports `False`. Async passes. |
| **N3** | 50 runs × 400 steps, both engines, full digest | replay | **PASS.** 1 distinct action trace and 1 distinct final snapshot per engine. |
| **N3-116** | `(GO, CANCEL)×10` through `send`-each and `send_events`, both engines | #116 | **PASS.** All four shapes give `{ok:10, cancel:0}`; `ALL_AGREE: True`. |
| **N3-109** | child with private `context` + declared `output` | #109 | **PASS.** `done.invoke` data is `{'result': 'final-answer'}`; private `DO-NOT-LEAK` absent. |
| **N3-108** | transition targeting `#rt` (the machine root) | #108 | **PASS.** `InvalidConfigError` at build with an explanatory message. |
| **N3-130** | `escalate` from an invoked child's entry | #130 | **PASS.** Parent reaches `p130.failed`, `onError` fired, payload `RuntimeError('child-blew-up')`. |
| **N4-C1a/b/c** | #105 per-task gate: 8 `create_task` producers, 8 OS threads, and a **child actor** `sendParent`, all at `maxIterations: 10` | #105 | **PASS.** 800/800, 800/800, 100/100; zero errors in all three. |
| **N4-C2a** | `OverflowPolicy.BLOCK`, `max_queue_size=8`, **16 concurrent producers** × 60 | #104 | **PASS.** 960/960, 0 lost, 0 errors. |
| **N4-C2b** | fire-and-forget `send()` under BLOCK on an inbox with room | #104 | **PASS.** 200/200, 0 lost. |
| **N5-F1** | **5 000** mutations of a real snapshot (byte-flip, truncate, key delete, retype, envelope, event-lane, config/context) | #110 | **FAIL → D5-determinism-2.** 1 746 `SnapshotCorruptError`, 996 `InvalidConfigError`, 435 `SnapshotDriftError`, 38 `SnapshotVersionError`, 33 `StateNotFoundError`, 1 413 clean restores — and **339 untyped escapes** (171 `TypeError`, 133 `AttributeError`, 35 `ValueError`). |
| **N5-F2** | 20 hostile `send()` types incl. `__str__`-raising and `__hash__`-raising objects | #113 | **PASS.** 17/20 raise `InvalidEventError`, which is **both** an `XStateMachineError` and a `TypeError` as documented; **0 untyped raises**. `dict` is accepted by design (documented `{"type": ...}` shape). `""` / `"   "` are accepted as ordinary unhandled event names — see §5. |
| **N6-O1** | hook matrix for every new error class | observability | **FAIL → D5-determinism-3.** `SnapshotMidStepError`, `InvalidEventError`, `SnapshotSerializationError`: all raise correctly, none emits an error/drop/fail hook. (`SnapshotCorruptError` cannot fire a hook — `from_snapshot` is a classmethod with no interpreter yet; noted, not counted.) |
| **N6-O2** | `async def` hook on the sync engine; hook raising `ValueError`; hook raising `CancelledError` | #127, #114 | **PASS.** Async hook does not run, is reported via `last_plugin_error` with an explanatory `TypeError`; both raising hooks are contained, `status` stays `running`, and `on_plugin_error` fires for both — **including `CancelledError`**. |
| **N6-O3** | `sendTo` a non-existent target | #133, #134 | **PARTIAL PASS.** `on_event_dropped` fires with reason `'unresolved_target'` (passed positionally, `base_interpreter.py:2956`) — #133 confirmed. `on_resolve_error` did **not** fire on this path; see §5. |
| **N6-S1** | `LoggingInspector` vs 12 sensitive keys | #126 | **PASS.** 0 leaked; all 12 redacted; benign value still visible (so it redacts, not blanket-suppresses). |
| **N6-S2** | 17 names promised by #137 + every new error class | #137 | **PASS.** All importable, all in `__all__`. (`__version__` still `0.8.0` — expected for an unreleased build.) |
| **N7** | 12-min chaos soak, both engines: bursts + clock ticks + restore-and-compare + hostile input + corrupt restores | all | **PASS on I1–I5** over 71 507 events / 11 883 quiescent snapshots / 2 376 restore cycles, with D5-determinism-2 independently re-found. See §7. |

### 3.1 A false positive I cleared before counting it

`n4`'s first run reported `501/800` processed for the `create_task` producers
at `maxIterations: 10` with **zero errors raised** — which looks exactly like
silent event loss on the #105 path. It was not. `n4b_maxiter_forensics.py`
instrumented `on_event_dropped` / `on_unhandled_event` /
`on_transition_failed`, the inbox depth and three drain strategies, and found
`LOST: 0` with `inbox_depth_at_end: 0` at `maxIterations` 10, 100 and absent —
the events were still queued because my harness drained for only 500 loop
turns. `n4_concurrency.py` now drains 20 000 turns and reports 800/800. **No
defect.** Recorded here because "reproduce before you count" cuts both ways.

---

## 4. Defects

### D5-determinism-1 — `restart_timers=True` silently does nothing on `SyncInterpreter` + `SimulatedClock`, while `has_dormant_timers` says it worked

**Severity: High.** **Kind: LIBRARY-DEFECT (regression in a round-4 feature).**
**Engine: sync only** (async passes).

**What the library promises.** #128 adds `restart_timers=True` to re-arm
`after` timers on restore, and `has_dormant_timers` to report when they are
*not* armed. `from_snapshot`'s own docstring (`base_interpreter.py:1336-1343`)
directs the caller to `has_dormant_timers` as the post-restore liveness check,
explicitly because `status` is not one (#135).

**What happens.** With `restart_timers=True`, `has_dormant_timers` flips
`True → False` across `start()` — reporting "re-armed" — but the timer never
fires. The machine stays in `armed` indefinitely under `clock.increment()`.

**Repro:** `determinism/n2b_restart_timers.py` (control + subject, same
machine, same clock class, no RNG). Verbatim:

```
== SYNC ==
   control_state_in_armed            : ['tm.armed']
   control_has_dormant_timers        : False
   control_attached_settlers         : 1
   control_late                      : 1          <- fresh interpreter: FIRES
   control_state_after               : ['tm.idle']
   snapshot_state_ids                : ['tm.armed']
   subject_dormant_before_start      : True
   subject_dormant_after_start       : False      <- reports "re-armed"
   subject_attached_settlers         : 0          <- but nothing settles it
   subject_state_after_start         : ['tm.armed']
   subject_late                      : 0          <- DOES NOT FIRE
   subject_state_after_200ms         : ['tm.armed']
   subject_late_after_tick           : 1          <- only an explicit tick() works
   VERDICT : TIMER-DID-NOT-FIRE despite has_dormant_timers=False

== ASYNC ==
   control_late   : 1
   subject_late   : 1
   subject_attached_settlers : 1
   VERDICT : OK
```

**Root cause (source, re-read).** `SyncInterpreter.start()` has a dedicated
restored-interpreter branch:

- `sync_interpreter.py:268-283` — `if self.status == "running" and
  (self._restart_services_on_start or self._restart_timers_on_start):` … calls
  `self._rearm_dormant_timers()` at `:280`, then **`return self` at `:283`**.
- `sync_interpreter.py:307-308` — `if isinstance(self.clock, SimulatedClock):
  self.clock._attach(self.tick)` — the line that makes
  `clock.increment()` drive this interpreter — is **below** that return and is
  never reached on the restore path.

`_rearm_dormant_timers()` (`base_interpreter.py:1596-1611`) does arm the
deadline in the clock, and `SimulatedClock._drain_sync`
(`clock.py:320-330`) does fire it — but firing only appends to
`self._event_queue` (`sync_interpreter.py:1317`); the queue is drained by
`tick()`, which is exactly the settler that was never attached
(`subject_attached_settlers: 0` vs the control's `1`). The async engine
attaches its settler at `interpreter.py:1062` on a path the restore branch
does not bypass, which is why it passes.

**Why High for an OMS.** This is the restore path for a long-lived order
process. A restored machine parked in a state whose `after` is its timeout —
an unacknowledged order, a stale quote, a session keepalive — waits forever,
and the library's own documented liveness check affirmatively reports that it
is armed. Silent stalling on a timeout path, with a lying health signal, is
worse than a loud failure. Not a Blocker only because it is confined to one
engine and one opt-in flag, and an adopter can work around it by calling
`tick()` after `start()` (verified: `subject_late_after_tick: 1`).

---

### D5-determinism-2 — `from_snapshot()` escapes the `XStateMachineError` hierarchy on malformed input

**Severity: Medium-High.** **Kind: LIBRARY-DEFECT (incomplete #110).**

**What the library promises.** #110: "malformed snapshots raise
`SnapshotCorruptError`". `check_shape`'s docstring
(`persistence.py:150-157`) states it runs "before any field is read, so a
corrupted blob cannot surface as a bare `KeyError` or be restored into an
impossible state".

**What happens.** 339 of 5 000 mutations escape as raw `TypeError` (171),
`AttributeError` (133) or `ValueError` (35).

**Repro (deterministic, no RNG):** `determinism/n5b_corrupt_escapes.py` —
9 hand-written single-field mutations, **7 escape**:

```
  version_is_str               -> ValueError      [ESCAPE]  invalid literal for int() with base 10: 'x'
  version_is_dict              -> TypeError       [ESCAPE]  int() argument must be a string... not 'dict'
  version_is_None              -> TypeError       [ESCAPE]  int() argument must be a string... not 'NoneType'
  version_is_list              -> TypeError       [ESCAPE]  int() argument must be a string... not 'list'
  status_is_dict               -> TypeError       [ESCAPE]  unhashable type: 'dict'
  status_is_list               -> TypeError       [ESCAPE]  unhashable type: 'list'
  history_is_float             -> AttributeError  [ESCAPE]  'float' object has no attribute 'items'
  pending_events_type_is_int   -> RESTORED-OK
  deferred_type_is_int         -> RESTORED-OK
```

Fuzz-wide breakdown is in `out/n5_fuzz.json` (`by_mutation_kind`); the
`envelope` and `retype:*` mutation classes account for nearly all escapes.

**Root cause (source, re-read).** Three distinct gaps, all *ordering* or
*coverage* problems in the shape check rather than missing intent:

1. `persistence.py:138` — `version = int(snapshot.get("version", 0))` inside
   `check_version()`, which `from_snapshot` calls at
   `base_interpreter.py:1393`, i.e. **before** `check_shape()` at `:1400`. A
   non-numeric `version` therefore raises `int()`'s own `ValueError` /
   `TypeError` before any shape validation can convert it.
2. `persistence.py:170` — `if status not in _VALID_STATUSES:` where
   `_VALID_STATUSES` is a `frozenset` (`:144`). Membership on a set hashes the
   left operand, so an unhashable `status` (`dict`, `list`) raises `TypeError`
   *inside the very check meant to reject it*. The check needs an
   `isinstance(status, str)` guard first.
3. `check_shape` validates `status`, `context`, `state_ids`, `configuration`,
   `pending_events` and `deferred` (`:166-195`) but **never `history`**, so a
   scalar `history` survives to an `.items()` call during restore.

Separately, two mutations **restore successfully with a non-`str` event
`type`** (`pending_events_type_is_int`, `deferred_type_is_int`): `:194` checks
`isinstance(r, dict) and "type" in r` but not that `r["type"]` is a `str`.
That reintroduces, via the restore path, exactly the non-`str` event type that
#113 rejects on the `send()` path — worth noting as the same class of hole.

**Why Medium-High for an OMS.** Snapshots come back from Redis, disk or a
queue; corruption is an ordinary runtime condition, which is precisely the
reasoning the library's own comment at `base_interpreter.py:1378-1383` gives
for wrapping `JSONDecodeError`. An adopter's recovery path is
`except XStateMachineError: rebuild_from_event_log()`. These escapes skip that
handler and surface as an unhandled `TypeError` in whatever generic frame
catches it — turning a recoverable checkpoint-corruption event into an
unplanned outage, or worse, into a generic `except Exception` that swallows it
and continues on stale state. Not High because it requires an already-corrupt
snapshot and every escape is at least *loud*.

---

### D5-determinism-3 — new error classes raise but emit nothing to any plugin hook

**Severity: Medium.** **Kind: LIBRARY-DEFECT (observability gap) / DESIGN-GAP.**

**Repro:** `determinism/n6_observability.py` (§O1). A `Spy` plugin binds **all
18** `on_*` hooks `PluginBase` declares (note: `__getattr__` does not work —
`PluginBase` defines them as real no-op methods, so lookup never falls
through; the script binds them explicitly and lists them in
`spy_hooks_bound`).

```
== O1_midstep ==        raise: SnapshotMidStepError
   hooks_seen: ['on_action_execute','on_event_received','on_interpreter_start',
                'on_interpreter_stop','on_transition']
   error_hook_fired: False
== O1_invalid_event ==  raise: InvalidEventError
   hooks_seen: ['on_interpreter_start','on_interpreter_stop','on_transition']
   error_hook_fired: False
== O1_serialization ==  snapshot_raise: SnapshotSerializationError
   hooks_seen: ['on_event_received','on_interpreter_start','on_interpreter_stop',
                'on_transition','on_unhandled_event']
```

In each case the ordinary lifecycle hooks fire but **no** `on_*error*` /
`on_transition_failed` / `on_event_dropped` hook does.

**Why this matters.** The library positions plugins as the observability
surface, and round 4 invested in exactly that (`on_plugin_error`,
`on_resolve_error`, `on_event_dropped(reason=...)`). An OMS builds its audit
log from hooks. Under this gap the audit log cannot record "a snapshot was
refused mid-step" or "a malformed order event was rejected" — the only witness
is an exception object at the call site, which a caller may catch and handle
without ever telling the log. The contrast is instructive and in the library's
favour elsewhere: `on_plugin_error` and `on_event_dropped(reason=
'unresolved_target')` both fire correctly (§N6-O2/O3), so the hook plumbing
works; these three classes simply were not wired to it.

Medium, not High: nothing is silently *wrong*, and the caller does get a typed
exception. It is a completeness gap in an observability contract, on a build
whose changelog headline is observability.

---

## 5. Coverage — and what was NOT covered

**Covered.** Within-engine replay stability (both engines, 20×1 000 and
50×400); cross-engine equivalence on 5 scripts + the `(GO,CANCEL)×10`
semantics probe; 13 delivery-lane ordering cases × 15 repeats;
`PYTHONHASHSEED` 0–5 for construction and runtime ordering; snapshot
byte-stability, round-trip and resume on both engines; 2 000 quiescent-point
snapshots/engine; 5 000 snapshot mutations; 20 hostile event types; the #105
gate from three distinct issuer contexts; #104 BLOCK at 16 producers; the
18-hook matrix; redaction of 12 sensitive keys; the 17-name exported API; a
12-minute two-engine chaos soak.

**NOT covered — stated plainly so the verdict is not over-read:**

1. **`d1` at the brief's original 50×10 000 scale.** Run at 20×1 000; `n3`
   adds 50×400. Both clean, so this is a coverage reduction on an
   already-passing claim, not an unexamined risk.
2. **The async arm of the N1-Q4 mid-step positive.** The async probe reported
   `action-never-ran` — the action had not executed before the drain, so it is
   unknown whether the async engine raises `SnapshotMidStepError` from inside
   an action. The *negative* (never fires at quiescence) is fully covered on
   async at 2 000 points. This is a harness limitation, not a finding.
3. **`on_resolve_error` (#134) has no confirmed trigger.** The `sendTo`-to-a-
   ghost path fires `on_event_dropped(reason='unresolved_target')` (#133) but
   not `on_resolve_error`. I did not find the path that does fire it, so I
   cannot say whether #134 is broken or merely aimed at a different case
   (delay/actor-ref resolution). **Not counted as a defect** — unverified
   either way.
4. **Empty / whitespace event names.** `send("")` and `send("   ")` are
   accepted and treated as ordinary unhandled events (context unchanged, no
   raise). Arguably correct — they are `str` — but an OMS that builds event
   names by string concatenation would get a silent no-op from a bug. Flagged
   as an observation, **not counted as a defect**.
5. **Non-`str` event `type` inside a restored snapshot** (see
   D5-determinism-2) is reported as part of that defect's analysis but its
   downstream consequences (what happens when such an event is later
   dispatched) were not traced.
6. **Leak behaviour beyond 12 minutes.** RSS was flat over the soak
   (§7: max ≈ last on both engines), but 12 minutes says nothing about a
   multi-day OMS process.
7. **Real-clock (`RealClock`) replay**, multi-process determinism, and
   `pickle`/`deepcopy` provenance (#138) — out of this track's scope.
8. **D-determinism-2's remaining 7 outcomes were not re-root-caused** in this
   pass; I confirmed the grid reproduces and that the isolated control (`d3b`)
   is now clean, which localises it to coroutine racing, consistent with the
   prior triage.

---

## 6. Standing constraints for an adopting design

Neither is a bug to file; both must be designed around.

- **C1 — The async engine's outcome is not a pure function of the recorded
  event stream when two coroutines race** (`D-determinism-2`, `d3c`: 7 distinct
  `{filled, aborted}` splits for one fixed script). A recorded event script is
  insufficient to reconstruct history. Mitigation: drive anything on the
  order-decision path through the sync engine, or `SimulatedClock` +
  single-producer discipline on async; do not expect an async-recorded trail to
  replay byte-identically from the script alone.
- **C2 — `send_threadsafe()` does not preserve call-site order relative to
  `send()`** (`D-determinism-6`, `d10b` case 2: 0/8 FIFO, 8 distinct orders).
  Nothing is lost (`d10` T3: 0 lost, 10/10 drained) — it is purely a
  reordering hazard. Mitigation: route every send through one call path, or
  serialise through an application-owned queue before the interpreter.

Note that C1 is materially narrower than last round: with the #116 fix the
*engine-choice* variable is gone, leaving only genuine coroutine racing.

---

## 7. Soak (12 min, both engines)

`n7_soak.py 720` — bursts of 1–12 scripted events, `SimulatedClock` ticks
every 3rd iteration, a quiescent snapshot every iteration, a
restore-and-byte-compare every 5th, hostile input every 7th, a corrupt-snapshot
restore every 11th, RSS sampled every 50th.

Invariants **I1** (legal 3-leaf configuration), **I2** (`status == "running"`),
**I3** (no `SnapshotMidStepError` at quiescence), **I4** (byte-identical
round-trip) and **I5** (no untyped escape on the send/snapshot/restore paths)
held throughout on both engines:

| | sync | async |
|---|---|---|
| seconds | 360.0 | 360.0 |
| iterations | 5 352 | 6 531 |
| events | 32 136 | 39 371 |
| quiescent snapshots | 5 352 | 6 531 |
| restore-and-compare round-trips | 1 070 | 1 306 |
| **I1** illegal configurations | **0** | **0** |
| **I2** bad `status` | **0** | **0** |
| **I3** `SnapshotMidStepError` at quiescence | **0** | **0** |
| **I4** round-trip byte mismatches | **0** | **0** |
| **I5** untyped escapes (send/snapshot/restore) | **0** | **0** |
| hostile inputs raising *typed* errors | 764 | 933 |
| corrupt restores raising *typed* errors | 368 | 428 |
| RSS first → last → max (MB) | 31.2 → 38.6 → 39.0 | 38.9 → 39.5 → 39.8 |

That is **11 883 quiescent snapshots and 2 376 full restore-and-compare cycles
across 71 507 events with zero violations of I1–I5** — the strongest single
piece of evidence in this report that the #102 / persistence work holds under
churn. RSS was effectively flat (sync's 8 MB rise is first-touch growth over
the first minutes, with max ≈ last).

The only failing counter was `corrupt_untyped` — the deliberate
corrupt-restore probe independently re-finding **D5-determinism-2**
(`unhashable type: 'dict'` / `'list'`, i.e. root cause #2 above), which is why
the scripts' own `OK` flag reads `False` for both engines. Full counters in
`out/n7_soak.json`.

---

## 8. Verdict

**Round 4 moved this track substantially.** Four of six prior defects are
fixed, including the two that previously blocked a replay/audit pipeline
outright: `Receipt.deferred` is now deterministic and truthful, and
checkpoint-and-resume under a `SimulatedClock` now reproduces the
straight-through tail byte-for-byte on **both** engines. Cross-engine
equivalence on sync `invoke` completion — previously a fill-vs-cancel
divergence — now holds at every producer gap and every call shape. The new
defensive surface largely does what it claims: `#102` never misfires at
quiescence across 4 000 measured snapshots, `#105`'s per-task gate holds under
three distinct issuer contexts, `#104` loses nothing at 16 producers, `#113`
rejects 17/17 hostile types typed, redaction and the exported API are clean.

**One new finding should be fixed before this build is adopted on an
order path: D5-determinism-1.** `restart_timers=True` is inert on
`SyncInterpreter` + `SimulatedClock` because `start()` returns at
`sync_interpreter.py:283` before attaching the clock settler at `:308`, and —
this is the sharp edge — `has_dormant_timers`, the check the library's own
docstring nominates as the post-restore liveness signal, reports `False`
("armed") anyway. A restored machine whose `after` is an order timeout waits
forever while its health check says it is fine. The fix looks small (attach the
settler before the restore-path return, or move the restore branch below it),
and a workaround exists (`tick()` after `start()`), which is why this is High
rather than Blocker.

**D5-determinism-2** (339/5 000 untyped escapes from `from_snapshot`) should be
fixed for any design that restores checkpoints from external storage: the
recovery handler an adopter would naturally write does not catch them. The
three root causes are narrow and individually small — validate `version`'s type
before `int()`, guard the `status` set-membership with an `isinstance` check,
and add `history` (and the event-lane `type` field) to `check_shape`.

**D5-determinism-3** is a completeness gap rather than a correctness one, but
it undercuts the round's own observability theme: three of the new error
classes are invisible to a hook-based audit log.

**Recommendation for this track: CONDITIONAL PASS.** Determinism and replay
are in materially better shape than at `5e07ba8` and, for the sync engine
under a `SimulatedClock` with no `restart_timers` restore, I found nothing that
makes a recorded stream unreproducible. Adoption on the order path should be
gated on a fix for D5-determinism-1, should treat D5-determinism-2 as a
recovery-path hardening item, and must design around the two standing
constraints in §6 — pin the order-decision path to one engine and one send
call path.
