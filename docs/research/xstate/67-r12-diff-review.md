# 67 — R12 diff review: `c78ce99..de2da4e` (unreleased 0.8.1)

Scope: 3 commits, 16 files, ~1.3k lines (`adf1b31` fix #218–#222, `30ae276`
test determinism pin, `de2da4e` merge). Library is read-only; every claim
below is reproduced by a STANDALONE probe under
`docs/research/xstate/probes/main-de2da4e/` (stdlib + `xstate_statemachine`
only, run from neutral cwd `<home>`).

**Suite (pre-existing background run, complete):** `3545 passed, 13 skipped,
15 warnings in 752.21s`; total coverage **92.87 %** (gate 90 %).
`validation.py` 99 %, `sync_interpreter.py` 97 %, `interpreter.py` 92 %,
`models.py` 88 %. No test was deleted or weakened in this diff: the test
delta is `+794 / -1` lines, all in the new
`tests/test_round11_findings.py`; no `xfail`, no `skip`, no `@unittest.skip`
anywhere in it. `30ae276` only strengthens a #219 pin (asserts the refusal
via `on_action_error` rather than via `last_error`, whose ordering differs
3.9–3.11 vs 3.12+ — a legitimate determinism fix, not a weakening: it also
adds a new assertion that the machine still reaches `y`).

---

## Verdict summary

| ID | Area | Severity | Status |
|----|------|----------|--------|
| **Q-1** | #219 `ReentrantWaitError` false-positives via inherited contextvar | **HIGH** | CONFIRMED |
| Q-2 | #219 cross-interpreter `wait=True` correctly NOT refused | none (good) | CONFIRMED |
| Q-3 | #218 handle release — bounded on fire/cancel/exit/stop, no double-pop | none (good) | CONFIRMED |
| Q-4 | #220 recursive key check — no false positive on 54-chart corpus | none (good) | CONFIRMED |
| Q-5 | #220 does NOT recurse into an inline-machine `invoke.src` | LOW (gap) | CONFIRMED |
| Q-6 | #221 parked re-emit — verbatim, no double-emit, fires once | none (good) | CONFIRMED |
| Q-7 | #222 latch not persisted / not restored across `from_snapshot` | LOW (doc gap) | CONFIRMED |
| Q-8 | `__version__` still `0.8.0` on an `[Unreleased] 0.8.1` tree | LOW | CONFIRMED |

Nothing here reverses the row-6 **ADOPT** verdict of `64-r11-final-readiness-verdict.md`.
Q-1 is a **new-behaviour regression risk** that adopters must be told about
before they upgrade.

---

## Q-1 (HIGH, new behaviour) — `ReentrantWaitError` fires on shapes that cannot deadlock

**Probe:** `p7_reentrant_false_positive.py`, `p2_reentrant_wait.py` (cases C2, D).

The guard (`interpreter.py:1144`) is

```python
if _ACTIVE_ACTION_OWNER.get() is self and not receipt.done():
    raise ReentrantWaitError(self.id, event_type)
```

`_ACTIVE_ACTION_OWNER` is a `ContextVar` set for the duration of
`_run_user_action` (`interpreter.py:2256`). The intended reading is "the
running task is inside one of my actions". But `asyncio.ensure_future` /
`create_task` **copy the current context**, so a task created inside an
action keeps `_ACTIVE_ACTION_OWNER is self` *for its whole life* — long
after the creating action returned and the run loop went idle. The guard
therefore cannot distinguish "in-step" from "descended from a step", and
refuses two shapes in which no deadlock is possible:

```
helper task born INSIDE the action : ('OK changed=True', 'y')
helper with a FRESH context        : ('OK changed=True', 'y')
bg task sends 300 ms after idle    : ('ReentrantWaitError', 'x')   <-- FALSE POSITIVE
docs idiom + action yields         : ('ReentrantWaitError', 'x')   <-- FALSE POSITIVE
```

1. **Background worker.** An `entry` action does
   `asyncio.ensure_future(worker(i))`; `worker` sleeps 300 ms — the machine
   is long idle, the loop is not in a step — then `await i.send("GO",
   wait=True)`. Refused. This is the standard "action kicks off a long-lived
   helper that later asks the machine a question" pattern; it worked on
   `c78ce99` and raises on `de2da4e`.
2. **The documented idiom itself, when the action yields.**
   `interpreters.md` (this diff) prescribes
   `asyncio.ensure_future(i.send("GO", wait=True))` and "await it later".
   If the action yields at all after scheduling it (`await asyncio.sleep(...)`,
   any I/O), the wrapper task is scheduled *while the action is still on the
   stack* and is refused. The pinned test
   (`test_handing_out_the_receipt_and_awaiting_later_is_fine`) passes only
   because its action returns immediately, so the wrapper never runs before
   the loop drains `GO` — the idiom's safety is **scheduling luck, not a
   property of the API**. An action with one `await` in it flips it.

In both refusals the machine stays in `x` and the receipt is abandoned; the
caller sees a hard exception where it previously got a resolved receipt.

*Why it is not "a trust boundary the docs draw":* the docs explicitly
sanction handing the receipt out and awaiting it later. This refuses exactly
that, non-deterministically.

**Suggested narrower predicate** (both conditions, not one): gate on the
interpreter actually being mid-step — e.g. `self._processing and
_ACTIVE_ACTION_OWNER.get() is self and <the current task is the run-loop
task>` — or set/reset a plain instance flag around the *synchronous* action
call rather than relying on an inheritable `ContextVar`. A `ContextVar` is
the right tool for #105's provenance question ("who produced this event")
and the wrong one for #219's liveness question ("can this await make
progress").

**Adopter action:** treat `ReentrantWaitError` as a breaking change. Audit
every action that spawns a task which later calls `send(..., wait=True)` on
the same interpreter (CV grep target: `ensure_future`, `create_task`,
`wait=True`). CV-relevant: any OMS action that fans out a fill-confirmation
worker.

## Q-2 (good) — cross-interpreter `wait=True` is allowed, and is safe

**Probe:** `p6_cross_interpreter_wait.py`, `p2` case E/F.

A child actor's action awaiting `parent.send("FROM_KID", wait=True)` is
**not** refused on either engine, and resolves correctly:

```
async child->parent wait=True (child NOT torn down): ('receipt changed=True', {'run': 's2'})
sync  child->parent wait=True (child NOT torn down): ('receipt changed=True', {'run': 's2'})
```

Correct: the guard keys on `is self`, and the parent's loop is a different
run loop that can advance while the child's action is parked. The earlier
`CancelledError` reading in `p2` case E is a harness artefact — the parent's
target was a `final` state, so the transition tore the child down and
cancelled its own pending action. Not a library defect.

`sendTo` to self is not a `send(wait=True)` call at all (it goes through
`_deliver`/`_send_to_actor`) and is unaffected.

Sync-engine parity claim holds but is a *different* rule: the sync engine
refuses on `wait and self._is_processing` (`sync_interpreter.py:590`) — a
plain re-entrancy flag, no contextvar, so it has **no** Q-1 false positive.
The two engines refuse the same headline shape by different predicates;
the sync one is the better predicate.

## Q-3 (good) — #218 handle release is complete and has no double-pop

**Probe:** `p1_handle_release.py` (200-beat `raise(delay=1)` heartbeat).

```
async  peak=1 after_settle=1 beats=202 after_stop=0
sync   peak=1 after_settle=1 beats=9   after_stop=0
cancel armed=1 after_cancel=0 after_stop=0
VERDICT: BOUNDED
```

(The sync line's low beat count is the probe's `tick()` budget under a
`RealClock`, not a library behaviour; the handle bound is what is pinned.)

Release paths reviewed — all four present:

| path | async | sync |
|---|---|---|
| fire | `_settle_debt()` in `_fire` → `_release_timer_handle` (`interpreter.py:2383`) | `sync_interpreter.py:1199` |
| cancel (`cancel` action / id reuse) | same `_settle_debt` via `_cancel` | `sync_interpreter.py:1193` |
| state exit (`after` timers) | `_timer_handles.pop(state.id)` (`interpreter.py:2618`) | `sync_interpreter.py:1505` |
| `stop()` | clears all lists (`interpreter.py:1567`) | `sync_interpreter.py:695` |

**No double-pop is possible.** `_release_timer_handle`
(`base_interpreter.py:2163`) is defensive: it returns early when the owner
key is absent and swallows `ValueError` from `list.remove` when the handle
is already gone. `after` handles are filed under `owner=state.id` while
delayed sends are filed under `owner=self.id`, so the wholesale
`pop(state.id)` on exit and the per-handle release never target the same
list. The fire path also guards the id registry (`if
self._scheduled_sends.get(key) is _cancel`), so a re-used send id does not
unregister the newer timer. `clock.clear_timeout` is documented idempotent.
Cost is O(n) in live delayed sends — bounded by design, and now actually
bounded because the list no longer grows.

## Q-4 (good) — #220 recursion: no false positive on 54 real charts

**Probe:** `p3_unknown_keys.py`.

```
corpus: 54 charts, 0 rejected under strict_config
```

(the `battle-c78ce99`, `battle-19cb1f1` and `battle-3ed3099` contract sets,
run at `strict_config=True` — the strictest setting an adopter can choose).
All 11 synthetic cases behave as intended, including `history` / `target` on
a history node, `output` on a final state, list-form transitions, `cond` as
well as `guard`, `internal` and `reenter`, and `x-` / `meta` /
`description` / `tags` at every level.

I walked the parser against the four key sets and found **no real key
missing**:

- `StateNode.__init__` + `_prefetch_node_keys` (`models.py:735`) read exactly
  `states, type, initial, tags, meta, entry, exit, on, always, onDone, after,
  invoke`, plus `id` (`cfg_get("id")`), `history` (`models.py:971`), `target`
  (history default) and `output` — all in `KNOWN_STATE_KEYS`, with
  `description` accepted as metadata.
- `TransitionDefinition` reads `target, guard|cond, internal, reenter,
  actions` and the internal `__forbidden__` — all covered. `__forbidden__`
  (`models.py:558`) is synthesised by the parser itself (`models.py:1387`),
  never user-written, so its absence from `KNOWN_TRANSITION_KEYS` cannot be
  reached from a config.
- `InvokeDefinition` reads `src, input, id, systemId, onDone, onError` — all
  covered.
- Root adds `context, version, maxIterations, strict, strictTargets,
  strictConfig, spawnBlockingTimeout, actionErrorPolicy, guardErrorPolicy,
  onUnhandled` — all covered.

One deliberate, correct strictness: a root-only policy key written **inside a
state** (`{"states": {"a": {"maxIterations": 5}}}`) is reported, because it
would be inert there. Documented in the `KNOWN_ROOT_KEYS` comment.

## Q-5 (LOW gap) — the check does not descend into an inline-machine `invoke.src`

**Probe:** `p3_unknown_keys.py`, case *"invoke src = inline machine dict"*.

```python
{"invoke": {"id": "kid", "src": {"id": "kid", "initial": "k",
                                 "states": {"k": {"entyr": ["nope"]}}}}}
```

passes `strict_config=True` clean. `_collect_unknown_keys` recurses only
into `config["states"]`; an `invoke.src` that is a nested machine *config
dict* is treated as an opaque value. So the exact class of typo #220 exists
to catch is still silent one level down, inside the sub-machine.

Impact is limited: the supported spawn shapes pass a pre-built `MachineNode`
or a factory callable (`interpreter.py:2501/2508`), both validated by their
own `create_machine()`. A raw inline dict is the uncommon path. Not a
blocker; worth a follow-up so the recursion is uniform — e.g.
`_collect_unknown_keys(inv["src"], ..., KNOWN_ROOT_KEYS, out)` when
`isinstance(inv.get("src"), dict)`.

## Q-6 (good) — #221 parked re-emit is verbatim, single, and fires once

**Probe:** `p4_parked_sends.py` (SimulatedClock, 60 s deadline, snapshot at
t+1 s).

```
ASYNC
  live armed          : [('LATE', 59000.0)]
  re-persist #1..#3 (no start): [('LATE', 59000.0)] x3
  after start()       : [('LATE', 59000.0)]   <-- ONE entry, not two
  value after deadline: b  transitions: 1     <-- fires exactly once
SYNC  (identical)
VERDICT: NO DOUBLE-EMIT
```

- **Verbatim, not recomputed.** `remaining_ms` is a stable `59000.0` across
  three restore→re-persist hops, each with a fresh `SimulatedClock`. No
  clock is bound while parked, so no time is charged: a compaction job can
  rewrite a blob any number of times without eroding the deadline. Matches
  the code — `_persist_scheduled_sends` (`base_interpreter.py:1253`) copies
  `_restored_self_sends` first and only then adds the live armed set.
- **No double-count after `start()`.** `_rearm_restored_self_sends`
  (`base_interpreter.py:1278`) does `records, self._restored_self_sends =
  self._restored_self_sends, []` — a swap, so the parked list is emptied
  *before* the records are armed. A snapshot taken after `start()` sees the
  armed entry only, and the event lands once (one subscriber transition).
- One trade-off, unchanged from #213 and already documented: a
  `remaining_ms` of 0 is re-armed at `max(delay, 0.001)` ms, i.e. "next
  pump", not "immediately within this step".

## Q-7 (LOW, doc gap) — the #222 latch is process-local, not persisted

**Probe:** `p5_chain_latch.py`.

```
  after BOOM          : 1 RunawayChainError plugin hits: 1
  after benign events : 1 RunawayChainError | last_error: NoneType   <-- sticky, as designed
  snapshot chain keys : []                                           <-- NOT persisted
  after clear()       : 1 None
  after 2nd BOOM      : 2 RunawayChainError | plugin hits: 2         <-- monotonic, one per trip
  after stop()        : 2 RunawayChainError                          <-- survives stop()
  restored interpreter: 0 None                                       <-- lost on restore
SYNC: identical.
```

All advertised semantics hold on **both** engines: sticky across benign
events (where `last_error` is already back to `None`), one plugin callback
per trip rather than per discarded event (`_chain_trip_open` gates it,
`base_interpreter.py:2084`), `chain_trips` monotonic and never reset, latch
cleared only by `clear_chain_error()`, and both surviving `stop()`.

The gap: `chain_trips` / `last_chain_error` appear in **no** snapshot key,
and a `from_snapshot` restore starts at `0 / None`. Defensible — they are
runtime health counters and an exception is not JSON — but a supervisor
sampling `chain_trips` across a restart-from-snapshot sees the counter
silently rewind to zero and reads that as "no trips" rather than "unknown".
The CHANGELOG and `api/index.md` say "monotonic … since construction",
which is accurate but will surprise an adopter of a *persistent* machine.
Recommend one sentence in `snapshots.md`: the chain-trip counters are
process-local and are not carried by a snapshot.

**CV action:** export `chain_trips` as a delta-since-process-start metric,
not a cumulative gauge, and emit a reset marker on restore.

## Q-8 (LOW) — version string

`__version__` is still `0.8.0` on a tree whose CHANGELOG reads
`[Unreleased] — targeting 0.8.1` and whose docs are annotated **[0.8.1]**
throughout (`ReentrantWaitError`, `chain_trips`, `on_chain_budget_exceeded`).
An adopter feature-gate written as `if __version__ >= "0.8.1"` is wrong on
this commit. Pin by commit, as this workstream already does. Expected to be
resolved at release; flagged so it is not missed.

---

## Undocumented / behaviour-change notes

- **`ReentrantWaitError` is a genuine behaviour change**, correctly called
  out in the CHANGELOG and `interpreters.md`. What is *not* documented is
  Q-1: the refusal also reaches tasks merely *descended* from an action, and
  the docs' own recommended workaround is itself affected.
- `KNOWN_MACHINE_KEYS` is retained as an alias of `KNOWN_ROOT_KEYS` — no
  break for anyone who imported the #216 name.
- `PluginBase.on_chain_budget_exceeded` is added with a `pass` body, so
  existing plugin subclasses are unaffected.
- `Event("")` is passed as the `event` argument for a **settle**-budget trip
  (`interpreter.py:2216`, `sync_interpreter.py:1056`) — documented in
  `plugins.md`; plugin authors must tolerate an empty event type.
- `__init__.py` exports `ReentrantWaitError` and re-sorts the existing
  exception imports; no export was removed.
- No deleted, weakened, xfailed or skipped test in this diff (see header).

## Probes

| file | pins |
|---|---|
| `p1_handle_release.py` | Q-3 handle bound on fire / cancel / stop, both engines |
| `p2_reentrant_wait.py` | Q-1/Q-2 the six `wait=True` shapes, both engines |
| `p3_unknown_keys.py` | Q-4/Q-5 key sets, 11 synthetic cases, 54-chart corpus |
| `p4_parked_sends.py` | Q-6 verbatim re-emit, no double-emit, fires once |
| `p5_chain_latch.py` | Q-7 latch semantics + persistence, both engines |
| `p6_cross_interpreter_wait.py` | Q-2 child→parent `wait=True` is safe |
| `p7_reentrant_false_positive.py` | Q-1 the two false positives |

All probes run in well under the 120 s bound (slowest, `p1`, ≈6 s) from
neutral cwd `<home>` with only stdlib + `xstate_statemachine`
imported.
