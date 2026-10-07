---
id: P-1
title: "Bug: the #222 chain-trip latch is not persisted, so restart-from-snapshot erases the evidence that work was discarded"
labels: [bug, persistence, area/interpreter, sync-interpreter, severity/medium]
severity: Medium
repro_script: repro/P-1-chain-trip-latch-not-persisted.py
commit: de2da4e
verified: true
---

## Summary

This is from our "make it perfect" list after twelve rounds of adoption
review: the library is adopted and running, and these are the few items
left between *adopt with constraints* and *nothing open*.

#222 added `chain_trips` and `last_chain_error` as the supervisor's sticky
signal that the runaway-chain guard cut a chain and **discarded work** —
deliberately sticky precisely because `last_error` is erased by the next
benign event. That works exactly as specified on a live interpreter (our
round-12 persistence track confirms the latch survives five benign events
that erase `last_error`).

But neither field is a snapshot key. A process that trips the guard, is
snapshotted and restarted comes back reporting `chain_trips == 0` and
`last_chain_error is None` — a clean machine, with no trace that the
previous process threw work away. The stickiness that makes the signal
useful stops at the process boundary, which is the one boundary a
supervisor is most likely to be watching across.

We are filing this as a Bug rather than a Feature because the field's
documented purpose (`base_interpreter.py:2099`: *"cleared only by
`clear_chain_error()`"*) and its actual lifetime disagree: a restore
clears it without anyone calling `clear_chain_error()`.

## Environment

* Library: `main` @ `de2da4e` (unreleased 0.8.1; `__version__` still
  reports `0.8.0`, so this keys on the commit).
* CPython 3.13.7, Windows 11, fresh venv, run from a neutral cwd.
* Both engines (`Interpreter`, `SyncInterpreter`); snapshot envelope v3.

## Minimal reproduction

Standalone: stdlib + `xstate_statemachine` only, every helper inlined, run
from the neutral cwd `<home>`. **Exit 1 = reproduced.**

```python
"""STANDALONE repro -- P-1: the #222 chain-trip latch is process-local.

`chain_trips` and `last_chain_error` are NOT snapshot fields, so a
restart-from-snapshot comes back reporting `chain_trips == 0` and
`last_chain_error is None` on a machine that provably discarded work in
the previous process. The evidence that a runaway chain was cut exists
only for the lifetime of the object that cut it.

Library @ de2da4e (unreleased 0.8.1; __version__ still reports 0.8.0).
stdlib + xstate_statemachine only. Every helper inlined. Run from ANY cwd.

Exit 1 == DEFECT REPRODUCED (latch present live, erased across restore).
"""

import asyncio
import json
import sys

from xstate_statemachine import create_machine, Interpreter, SyncInterpreter
from xstate_statemachine.actions import raise_ as raise_action
from xstate_statemachine.exceptions import RunawayChainError
from xstate_statemachine.machine_logic import MachineLogic

# A self-raising spin state with a small chain budget: sending GO trips
# the runaway-chain guard, which is exactly the #222 supervisor signal.
CONFIG = {
    "id": "p1",
    "initial": "a",
    "maxIterations": 3,
    "states": {
        "a": {
            "entry": [raise_action({"type": "GO"})],
            "on": {
                "GO": {"target": "a", "reenter": True},
                "CALM": "b",
            },
        },
        "b": {},
    },
}

SNAPSHOT_KEYS = ("chain_trips", "last_chain_error")


def _machine():
    return create_machine(dict(CONFIG), logic=MachineLogic())


def _trip_sync(machine):
    """Drive a real chain trip on the sync engine and snapshot afterwards."""
    interp = SyncInterpreter(machine)
    try:
        interp.start()
    except RunawayChainError:
        pass  # the entry raise_ can trip during start()
    try:
        interp.send("GO")
    except RunawayChainError:
        pass
    live = (interp.chain_trips, type(interp.last_chain_error).__name__
            if interp.last_chain_error is not None else None)
    blob = json.loads(interp.get_snapshot())
    interp.stop()
    return live, blob


async def _trip_async(machine):
    """Same trip on the async engine -- the latch is reported via the API."""
    interp = Interpreter(machine)
    try:
        await asyncio.wait_for(interp.start(), timeout=10.0)
    except RunawayChainError:
        pass
    await interp.send("GO")
    await asyncio.sleep(0.15)
    live = (interp.chain_trips, type(interp.last_chain_error).__name__
            if interp.last_chain_error is not None else None)
    blob = json.loads(interp.get_snapshot())
    await interp.stop()
    return live, blob


def _restored_view(cls, machine, blob):
    interp = cls.from_snapshot(json.dumps(blob), machine)
    return (
        interp.chain_trips,
        type(interp.last_chain_error).__name__
        if interp.last_chain_error is not None
        else None,
    )


async def main():
    print("P-1 -- the #222 chain-trip latch across a snapshot round-trip\n")

    m_sync = _machine()
    live_sync, blob_sync = _trip_sync(m_sync)
    keys_sync = [k for k in SNAPSHOT_KEYS if k in blob_sync]
    rest_sync = _restored_view(SyncInterpreter, m_sync, blob_sync)

    m_async = _machine()
    live_async, blob_async = await _trip_async(m_async)
    keys_async = [k for k in SNAPSHOT_KEYS if k in blob_async]
    rest_async = _restored_view(Interpreter, m_async, blob_async)

    print(f"  sync   live (trips, latch)     : {live_sync}")
    print(f"  sync   snapshot keys present   : {keys_sync}")
    print(f"  sync   restored (trips, latch) : {rest_sync}")
    print()
    print(f"  async  live (trips, latch)     : {live_async}")
    print(f"  async  snapshot keys present   : {keys_async}")
    print(f"  async  restored (trips, latch) : {rest_async}")

    print()
    tripped = live_sync[0] >= 1 and live_sync[1] is not None and live_async[0] >= 1
    no_keys = keys_sync == [] and keys_async == []
    erased = rest_sync == (0, None) and rest_async == (0, None)
    print(f"a real chain trip happened, both engines           : {tripped}")
    print(f"neither key appears in the v3 envelope             : {no_keys}")
    print(f"restore reports a clean machine (0, None)          : {erased}")

    reproduced = tripped and no_keys and erased
    print(f"\nREPRODUCED: {reproduced}")
    return 1 if reproduced else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(main(), timeout=60.0)))
    except asyncio.TimeoutError:
        print("WATCHDOG: hung")
        sys.exit(2)
```

## Observed behaviour

```
P-1 -- the #222 chain-trip latch across a snapshot round-trip

  sync   live (trips, latch)     : (2, 'RunawayChainError')
  sync   snapshot keys present   : []
  sync   restored (trips, latch) : (0, None)

  async  live (trips, latch)     : (2, 'RunawayChainError')
  async  snapshot keys present   : []
  async  restored (trips, latch) : (0, None)

a real chain trip happened, both engines           : True
neither key appears in the v3 envelope             : True
restore reports a clean machine (0, None)          : True

REPRODUCED: True
```

Exit code **1**. Identical on both engines. The trip demonstrably happened
(`chain_trips == 2`, `last_chain_error` is a `RunawayChainError`); the v3
envelope contains neither key; the restored interpreter is
indistinguishable from one that never tripped.

## Expected behaviour

The latch is part of the interpreter state a snapshot captures, so a
restored interpreter reports the same `chain_trips` and the same
`last_chain_error` the snapshotted one did, and `clear_chain_error()`
remains the only thing that clears it — as `base_interpreter.py:2099`
documents.

A restart should not be an implicit acknowledgement of a discarded-work
incident.

## Root cause analysis

The fields exist only as instance state:

* `base_interpreter.py:502-503` — `"_last_chain_error"`, `"chain_trips"` in
  `__slots__`.
* `base_interpreter.py:623-624` — initialised to `0` / `None` in
  `__init__`, which is also what a `from_snapshot`-built instance gets,
  since the restore path never writes them.
* `base_interpreter.py:2085-2089` — `_trip_chain_budget` increments the
  counter and sets the latch.

The v3 envelope is built at `base_interpreter.py:1556-1601`
(`get_persisted_snapshot`). It carries `deferred`, `pending_events`,
`scheduled_sends`, `history`, `actors`, `error`, `output` — every other
piece of "what was in flight / what went wrong" — but no chain-trip keys.
Correspondingly the restore path (`base_interpreter.py:~1916-1945`) reads
`output`, `error`, `deferred`, `scheduled_sends`, `pending_events`,
`history`, `actors` and never touches the latch.

So the omission is symmetric and consistent — it simply was not in scope
when #222 landed. Nothing else has to change for it to be added.

## Impact

* **Operational**: the exact signal a supervisor is meant to act on is the
  one signal that does not survive the event a supervisor most often
  reacts to — a restart. A crash-loop that trips the chain budget every
  cycle presents as a series of clean starts.
* **Silent**: unlike DE-L1 this failure has no exception and no log at the
  point it matters; the reader simply sees `0`. Our board treats
  "supervisor-facing evidence that silently disappears" as the shape worth
  filing.
* **Counter semantics**: `chain_trips` is documented as monotonic. Across
  a restore it is not merely stale, it is reset, so a supervisor
  accumulating it across a fleet under-counts.
* **Workaround exists** (which is why this is Medium, not higher): an
  adopter can read `chain_trips` / `last_chain_error` immediately before
  `get_persisted_snapshot()` and carry them in their own sidecar record.
  We do this today — it is wrapper constraint our wrapper constraint on our side — but it
  requires every snapshot call site to remember, and a snapshot taken by a
  generic journal-compaction job cannot do it at all.

## Proposed fix

Add both as **additive** v3 envelope fields — no version bump needed, since
a reader that does not know them ignores them and a writer that does not
emit them upcasts to the documented defaults.

```python
# get_persisted_snapshot (~1596), alongside "error"
"chain_trips": self.chain_trips,
"last_chain_error": (
    str(self._last_chain_error)
    if self._last_chain_error is not None
    else None
),
```

```python
# from_snapshot, beside the `recorded_error` handling (~1916)
interpreter.chain_trips = int(snapshot.get("chain_trips") or 0)
latched = snapshot.get("last_chain_error")
interpreter._last_chain_error = (
    RestoredError(str(latched)) if latched else None
)
```

Two notes on the shape:

* **Upcast defaults `0` / `None`** — exactly what an old blob (and a v2
  blob) produces today, so every existing snapshot restores to the current
  behaviour and nothing regresses.
* **`RestoredError` is the established precedent**: `error` already
  round-trips as a string and comes back wrapped, for the same reason (the
  original exception type cannot survive JSON) and with the same tradeoff
  already accepted in this codebase. A supervisor that wants to
  discriminate can still read `chain_trips`, which is exact.

If you would rather not widen the envelope, the alternative that closes the
observability hole is to document the field as process-local in the
`last_chain_error` docstring and in `persistence.md`, and to say plainly
that a restore is not an acknowledgement. We would find that acceptable,
though less good — the sidecar is easy to forget and impossible for a
generic snapshot consumer.

## Acceptance criteria

* `repro/P-1-chain-trip-latch-not-persisted.py` exits **0**: both engines
  report the snapshot keys present and the restored view equal to the live
  view.
* New test `test_chain_trip_latch_survives_snapshot_round_trip`,
  parametrised over both engines: trip the budget, round-trip through
  `get_persisted_snapshot` / `from_snapshot`, assert `chain_trips` and a
  non-`None` `last_chain_error` match the pre-snapshot values.
* New test `test_restored_chain_latch_is_cleared_only_by_clear_chain_error`:
  after restore, benign events leave the latch set; `clear_chain_error()`
  clears it and leaves `chain_trips` unchanged — the #222 contract,
  now holding across the boundary.
* New test `test_snapshot_without_chain_keys_upcasts_to_zero_and_none`: a
  blob with neither key (i.e. every snapshot written before this change,
  and any v2 blob) restores to `chain_trips == 0`,
  `last_chain_error is None` — no regression for existing stores.
* `chain_trips` remains monotonic within a process and across a restore
  (a second trip after restore gives `previous + 1`).
* No `SNAPSHOT_VERSION` bump; the existing v3 round-trip property tests
  still pass unchanged.

## Verification

- Repro run from the neutral cwd `<home>` with the `.venv-main`
  interpreter: **exit 1**, no `ImportError`, output as quoted above —
  `REPRODUCED: True` on both engines.
- The code block under "## Minimal reproduction" is **byte-identical** to
  `repro/P-1-chain-trip-latch-not-persisted.py` (4520 bytes, compared
  programmatically).
- Root-cause lines confirmed open in current source at `de2da4e`:
  - `base_interpreter.py:502-503` — `"_last_chain_error"` in `__slots__`,
    an instance attribute with no snapshot counterpart.
  - `base_interpreter.py:623-624` — `self.chain_trips: int = 0`, the
    counter initialised per construction.
  - `base_interpreter.py:2085-2089` — `self._last_chain_error = error`,
    where the latch is set on a trip.
  - `base_interpreter.py:2099` — the docstring describing the latch as
    "cleared only by `clear_chain_error()`. Pair with `chain_trips`".
  - `base_interpreter.py:1556-1601` — the v3 envelope builder. Confirmed by
    inspection **and** empirically: a live snapshot's key set is
    `['actors', 'configuration', 'context', 'deferred', 'error', 'history',
    'machine_hash', 'machine_id', 'output', 'pending_events',
    'scheduled_sends', 'state_ids', 'status', 'system', 'taken_at',
    'value', 'version']` — neither `chain_trips` nor `last_chain_error`
    appears.
  - `plugins.py:423` — the `on_chain_budget_exceeded` hook doc naming "the
    sticky `interpreter.chain_trips`", i.e. the durability promise this
    issue says stops at the process boundary.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 320` searched for `chain_trips`, `scheduled_sends`,
  `persistence`. Only `#222` (CLOSED) covers the latch, and it concerns
  liveness across events, not across a restart.

## Related

* #222 (the latch this extends), #213 / #221 (`scheduled_sends`, the
  precedent for adding an in-flight field to the envelope), #45 (the
  envelope).
* `base_interpreter.py:2094-2107` — `last_chain_error` / `clear_chain_error`
  docstrings, which describe a lifetime the restore path does not honour.
* `plugins.py:423` — `on_chain_budget_exceeded`, which names these two
  fields as the supervisor's signal.
* Our adoption audit (#26), round 12 — recorded there as the §3.1 contract
  gap and wrapper constraint our wrapper constraint.
