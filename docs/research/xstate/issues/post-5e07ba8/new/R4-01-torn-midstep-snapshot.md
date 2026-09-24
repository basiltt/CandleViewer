---
r4: R4-01
title: "Bug: Mid-macrostep configuration is snapshottable; a snapshot taken in the exit→actions→enter window restores as a permanently inert machine reporting healthy"
labels: [bug, severity/blocker, area/persistence]
severity: Blocker
repro_script: repro/R4-01_torn-midstep-snapshot.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`_execute_transition` documents in its own source comment that
"exit → actions → enter is ONE transaction", but nothing enforces that
transaction against *observers*. While an `await`ing transition action is
running, `_active_state_nodes` contains no leaf, and
`get_persisted_snapshot()` reads `_active_state_nodes` directly with no
check on the interpreter's `_processing` flag. A snapshot taken in that
window serialises `state_ids: []`, and `from_snapshot()` accepts it without
any legality check — producing a live interpreter with an empty
configuration, `status="running"`, `error=None` and
`has_dormant_invocations=False`. That machine matches no further event,
forever, while every public health probe reports it healthy. For a
long-running stateful service this is silent, unrecoverable state loss: a
crash or a concurrent snapshotter in a ~40% window of realistic
interruption points persists a blob that restores clean and then does
nothing.

## Environment

- Commit: `5e07ba8842345a73ef8f830f0281de16370a7c74` (`main`,
  `[Unreleased] — targeting 0.8.1`; `__version__` still reports `0.8.0`,
  so this build is identified by commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source
  modified.

## Minimal reproduction

```python
"""R4-01 repro: mid-macrostep snapshot is torn and restores as a permanently
inert machine that reports itself healthy.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""

import asyncio
import json
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "t",
    "initial": "a",
    "context": {},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["slow"]}}},
        "b": {},
    },
}


async def slow(interpreter, ctx, event, action_def):
    # A realistic awaiting transition action: the exit->actions->enter
    # transaction is open for the whole of this sleep.
    await asyncio.sleep(0.4)


def logic():
    return MachineLogic(actions={"slow": slow})


async def main() -> int:
    live = Interpreter(create_machine(CFG, logic=logic()))
    await live.start()

    task = live.send("GO")
    await asyncio.sleep(0.15)  # we are now inside the transition window

    # Everything a health check can see says the machine is fine.
    healthy_probe = (live.status, live.queue_depth, live.is_running)

    snap = live.get_persisted_snapshot()
    blob = snap if isinstance(snap, str) else json.dumps(snap)
    doc = json.loads(blob)

    await task
    await asyncio.sleep(0.1)

    restored = Interpreter.from_snapshot(blob, create_machine(CFG, logic=logic()))
    await restored.start()
    receipt = await restored.send("PING", wait=True)

    print("OBSERVED:")
    print("  mid-window public probes  :", "status=%s queue_depth=%s is_running=%s" % healthy_probe)
    print("  snapshot state_ids        :", doc.get("state_ids"))
    print("  snapshot configuration    :", doc.get("configuration"))
    print("  snapshot status           :", doc.get("status"))
    print("  restored current_state_ids:", sorted(restored.current_state_ids))
    print("  restored status           :", restored.status)
    print("  restored dormant invokes  :", restored.has_dormant_invocations)
    print("  PING receipt              :", receipt)

    print("EXPECTED:")
    print("  snapshot state_ids        : non-empty (either ['t.a'] or ['t.b'])")
    print("  restored current_state_ids: non-empty, and PING is matched or")
    print("                              get_persisted_snapshot() refuses/awaits")
    print("                              while a macrostep is in flight")

    torn = not doc.get("state_ids")
    inert = not restored.current_state_ids and restored.status == "running"

    await restored.stop()
    await live.stop()

    if torn or inert:
        print("RESULT: FAIL - torn snapshot restores as a silently-inert machine")
        return 1
    print("RESULT: PASS")
    return 0


sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED:
  mid-window public probes  : status=running queue_depth=0 is_running=True
  snapshot state_ids        : []
  snapshot configuration    : ['t']
  snapshot status           : running
  restored current_state_ids: []
  restored status           : running
  restored dormant invokes  : False
  PING receipt              : Receipt(state_ids=frozenset(), changed=False, error=None, deferred=False)
EXPECTED:
  snapshot state_ids        : non-empty (either ['t.a'] or ['t.b'])
  restored current_state_ids: non-empty, and PING is matched or
                              get_persisted_snapshot() refuses/awaits
                              while a macrostep is in flight
RESULT: FAIL - torn snapshot restores as a silently-inert machine
```

Exit status `1`.

Note the two-layer failure. The snapshot is *torn* (`state_ids: []`,
`configuration: ['t']` — the root ancestor only, no leaf), and separately
`from_snapshot()` *accepts* that torn blob without complaint. The restored
machine then answers a `PING` with
`Receipt(state_ids=frozenset(), changed=False, error=None, deferred=False)`
— byte-identical to the receipt a legitimately-unhandled event produces, so
a caller cannot distinguish "this event does not apply here" from "this
machine is dead".

A property run over the same window (`t8_midstep_property.py`, 500 cases /
150 snapshots) put the tear rate at **62/150 = 41.3%** of snapshots taken
at a uniformly-random instant during a macrostep (31 fully empty, 31
missing a parallel region), with zero snapshot calls raising. An earlier
2,000-case run measured 37.6% of 447. The window is not a narrow race — it
is roughly the whole duration of any `await`ing transition action.

## Expected behaviour

Per W3C SCXML §3.13 (*Selecting and Executing Transitions*), the microstep
— exit set, transition executable content, entry set — is the unit of
execution; the configuration is only well-defined at a macrostep boundary,
and SCXML requires the configuration to always contain exactly one atomic
descendant per active compound/parallel region. An empty configuration with
`status="running"` is not a legal SCXML configuration at any observable
point.

XState v5 makes the same guarantee at the API level:
`actor.getPersistedSnapshot()` returns a snapshot of the actor's *settled*
state, and its persistence guide
(<https://stately.ai/docs/persistence>) describes the persisted snapshot as
something you can "restore the actor from ... and it will continue from
where it left off" — a restored actor that continues from nowhere violates
that contract.

The library's own source states the intended contract explicitly, at
`src/xstate_statemachine/base_interpreter.py:2338`:

> ⚛️ ATOMICITY: exit → actions → enter is ONE transaction. If a user
> action raises in the middle, the source has been left and the target
> never reached, so the configuration would be EMPTY while `status` still
> read "running" — permanently dead and reporting itself healthy.

The comment identifies precisely this failure mode and the rollback below
it (`base_interpreter.py:2413-2418`) defends against the *raising-action*
route into it. The observer route is left open.

Expected, concretely:

1. `get_persisted_snapshot()` never returns a configuration with zero
   leaves for a running interpreter — it either reflects the pre-transition
   configuration or the post-transition one, never the intermediate.
2. `from_snapshot()` refuses a blob whose configuration is empty (or has no
   leaf in some active region) with an `XStateMachineError`, rather than
   constructing an inert interpreter.

## Root cause analysis

Two independent gaps compose.

**1. No interlock between the transaction and the snapshotter.**

`BaseInterpreter._execute_transition` (`base_interpreter.py:2230`) performs
the transaction at `:2351-2369`:

```python
await self._exit_states(sorted(...), event)          # _active_state_nodes drained
failed_actions = await self._execute_actions(transition.actions, event)   # <-- await
...
await self._enter_states(path_to_enter, event)       # _active_state_nodes refilled
```

`_exit_states` discards the source leaves from `_active_state_nodes`
(`:3095`) and `_enter_states` adds the target leaves (`:2892`); they are,
per the architecture comment at `:2330`, "the sole authorities on
`_active_state_nodes` membership". Between them lies an unbounded `await`
on user action code. Any other coroutine scheduled during that await sees a
leafless `_active_state_nodes`.

`get_persisted_snapshot()` (`base_interpreter.py:952`) is exactly such an
observer. It builds

```python
"state_ids": sorted(self.current_state_ids),
...
"configuration": sorted(node.id for node in self._active_state_nodes),
```

reading `_active_state_nodes` directly (`:1000`) with no guard.
`current_state_ids` (`:557`) filters to `s.is_atomic or s.is_final`, which
is why it comes back `[]` while `configuration` still shows the root `'t'`
that `_exit_states` never removed. Notably, `Interpreter` *does* maintain a
`self._processing` flag (`interpreter.py:271`, set at `:1240`, cleared at
`:1270`) and already consults it in `send()` (`:620`, `:633`) — the
machinery to detect "a macrostep is in flight" exists and is simply not
consulted here.

The rollback added for the raising-action case (`:2413-2418`, restoring
`snapshot_before` captured at `:2279`) closes the window only *after* the
fact. It does not make the window unobservable, and it does nothing at all
when the action does not raise — the repro's `slow` action returns
normally.

**2. No legality check on restore.**

`from_snapshot()` (`base_interpreter.py:1103`) rebuilds the configuration at
`:1208-1219`:

```python
interpreter._active_state_nodes.clear()
restore_ids = snapshot.get("configuration") or snapshot["state_ids"]
for state_id in restore_ids:
    node = machine.get_state_by_id(state_id)
    if node:
        interpreter._active_state_nodes.add(node)
        ancestor = node.parent
        while ancestor is not None:
            interpreter._active_state_nodes.add(ancestor)
            ancestor = ancestor.parent
```

There is no post-loop assertion that the result is non-empty, that every
active compound state has an active child, or that every region of an
active parallel state has exactly one active leaf. `status` is likewise
assigned verbatim one line earlier at `:1202` with no membership check
against the status enum. So the torn blob loads a second time, clean.

This second gap is filed separately as R4-02 (Medium); it is listed here
because it is what turns a transient tear into a *durable* one, and because
the fix for it is the natural defence in depth for this issue.

## Impact

**General users.** Any application that snapshots a running interpreter on
a timer, on a signal handler, or from a sidecar health/checkpoint task —
the pattern the persistence guide encourages — has a ~40% chance, per
snapshot landing inside a macrostep, of persisting a blob that restores
into a machine that is alive, reports healthy, and ignores every event
forever. There is no error, no log line, and no public predicate that
distinguishes it from a healthy machine: `status == "running"`,
`error is None`, `has_dormant_invocations is False`, `queue_depth == 0`,
`is_running is True`. The only detection available today is for the
application to independently assert that `current_state_ids` is non-empty
after every restore — which requires knowing about this bug.

Crash-recovery is affected even without a concurrent snapshotter, because a
process killed mid-macrostep and a snapshot taken mid-macrostep produce the
same durable artefact.

**Order-management scenario (our adoption audit, #26).** We model each
order's lifecycle as an interpreter and checkpoint it so an order survives a
process restart. Transition actions on the order path `await` — they write
to the DB, call the exchange client. Those awaits *are* the window. A crash
or a checkpoint tick during `submit → awaiting_ack` persists an order whose
configuration is empty. On restart the order loads, reports `running`, and
is then silently deaf: the exchange `FILL` arrives and produces
`Receipt(state_ids=frozenset(), changed=False, error=None, deferred=False)`;
the operator-issued `CANCEL` produces the identical receipt. A filled order
is never recorded as filled and a cancel is never actually placed, with the
system asserting the whole time that the order is healthy. This is
unbounded financial exposure from a silent, non-crashing failure — the
reason this issue alone holds our adoption at DEFER for the persistence
path.

## Proposed fix

**Primary: make the transaction atomic against observers.**

Preferred design — *stage and swap*. Have `_exit_states`/`_enter_states`
operate on a staged working set during `_execute_transition`, and publish
the result to `_active_state_nodes` with a single assignment once entry
completes (and publish `snapshot_before` unchanged on the rollback path).
Observers then only ever see a committed configuration; no flag discipline
is needed and no observer has to know about the transaction. This preserves
the `:2330` architecture decision (the two methods remain the sole
authorities on membership) — they just author the staged set.

Simpler alternative — *interlock the reader*. Give
`get_persisted_snapshot()` a guard on the already-existing `_processing`
flag. Two sub-options:

- *Refuse*: raise a typed `SnapshotDuringTransitionError(XStateMachineError)`
  when `self._processing` is set. Safe and tiny, but it is a behaviour change
  for existing callers and pushes retry logic onto every user.
- *Await*: add an `async def persist()` that awaits macrostep quiescence
  (an `asyncio.Event` set when `_processing` clears) and then snapshots.
  Best ergonomics for the async engine; `get_persisted_snapshot()` stays
  sync and gets the refusal behaviour above.

Stage-and-swap is preferable because it also fixes the *crash* route — a
process killed mid-macrostep with a staged set has never written a torn
configuration to `_active_state_nodes` at all — whereas the reader
interlock only fixes the concurrent-observer route.

**Defence in depth: validate on restore.** Implement R4-02's legality check
in `from_snapshot()` after the reconstruction loop at
`base_interpreter.py:1219`: reject a configuration that is empty, or that
leaves an active compound state without an active child, or an active
parallel region without exactly one active leaf — raising
`XStateMachineError`. This is what makes the failure loud rather than
silent even if a torn blob is produced by some other route (or already sits
in a user's store today).

**Compatibility.** Stage-and-swap is internal and observationally
invisible except that torn snapshots stop occurring — no public API change.
The restore-side validation newly rejects blobs that are currently accepted;
since every such blob today produces an inert machine, rejecting them is
strictly an improvement, but it should be called out in the changelog and
could be gated behind a `validate=True` default parameter for one release
if a smoother migration is wanted.

## Acceptance criteria

- [ ] `repro/R4-01_torn-midstep-snapshot.py` exits `0`.
- [ ] `tests/test_persistence.py::test_snapshot_during_awaiting_transition_action_is_never_torn`
      — snapshot taken mid-action has a non-empty `state_ids` equal to
      either the pre- or post-transition configuration.
- [ ] `tests/test_persistence.py::test_snapshot_mid_macrostep_property`
      — property test over ≥500 randomised machines/interrupt points
      asserting every snapshot has exactly one leaf per active region;
      0 failures (currently 41.3% fail).
- [ ] `tests/test_persistence.py::test_parallel_snapshot_mid_macrostep_keeps_every_region`
      — covers the `missing_region` half of the tear, not just the fully
      empty case.
- [ ] `tests/test_persistence.py::test_from_snapshot_rejects_empty_configuration`
      — raises `XStateMachineError`, not a silently-inert interpreter.
- [ ] `tests/test_persistence.py::test_from_snapshot_rejects_region_without_leaf`
- [ ] `tests/test_interpreter.py::test_transition_rollback_still_restores_prior_configuration`
      — the existing raising-action rollback at `base_interpreter.py:2413`
      is unchanged by the staging refactor.
- [ ] Changelog entry noting that `from_snapshot()` now validates
      configuration legality.

## Related

- **Register ids:** R4-01 (this issue). Source ids `D-persistence-3`,
  `D-concurrency-3` — two tracks reaching the same non-atomic window from
  opposite directions (persistence: snapshot the window; concurrency:
  observe the window).
- **R4-02** (Medium, `from_snapshot()` performs no configuration-legality,
  status or context validation) — the restore-side half. Filed separately;
  its fix is listed above as defence in depth here. Its empty-configuration
  sub-case *is* this issue's corrupt blob loading clean a second time.
- **R4-12** (High, an `always` transition targeting the machine root empties
  the configuration on both engines, leaving `status="running"`) — same
  silent-inert-machine outcome via a build-time-reachable single-region
  path. A restore-side legality check would catch that one too.
- **Evidence:** `battle-5e07ba8/persistence/d3_torn_snapshot.py`,
  `d3b_partial_parallel.py`, `t8_midstep_property.py`, `t7_rollback.py`;
  `battle-5e07ba8/concurrency/d3_snapshot_in_window.py`,
  `probe_d_empty_window.py`; `probes/main-5e07ba8-final/v1_torn.py`.
- **Prior art in this repo:** #27 (entry/exit actions brought into the
  transaction), #45 (snapshot envelope / `from_snapshot` hardening), #58
  (hierarchical `value` in the snapshot).

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `5e07ba8842345a73ef8f830f0281de16370a7c74` (confirmed via
  `git log -1` in the library clone)
- `repro/R4-01_torn-midstep-snapshot.py` run fresh, capped at 60 s: output
  matches the Observed behaviour section verbatim (`state_ids: []`,
  `configuration: ['t']`, restored `current_state_ids: []`,
  `status='running'`, PING receipt
  `Receipt(state_ids=frozenset(), changed=False, error=None, deferred=False)`).
  Exit code `1`.
- Root-cause narrative confirmed against source: the ATOMICITY comment is
  at `base_interpreter.py:2338`; `get_persisted_snapshot()` at `:952`
  reads `_active_state_nodes` directly at `:999-1000` with no guard;
  `from_snapshot()` at `:1103` reconstructs the configuration at
  `:1208-1219` with no post-loop legality check; `_processing` is defined
  at `interpreter.py:271` and consulted at `:620`/`:633` but not by
  `get_persisted_snapshot()`.
- External claim checked: `stately.ai/docs/persistence` (fetched
  2026-09-19) confirms `actor.getPersistedSnapshot()` /
  `createActor(logic, { snapshot })` is the documented restore-and-continue
  contract, consistent with the Expected-behaviour citation.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state
  all --limit 120 --search "torn snapshot"` returned one unrelated closed
  issue (#57, reaping terminal machines); no existing issue covers a
  mid-macrostep torn snapshot. No duplicate found.
- No project-name/label leakage found in the issue body or repro script.
