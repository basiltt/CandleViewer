---
id: DE-L5
title: "Bug: priority lane not honoured on sync-engine restore (SyncInterpreter._enqueue_restored ignores priority)"
labels: [bug, severity/low, persistence, sync-interpreter]
severity: Low
repro_script: repro/DE-L5-repro.py
commit: de2da4e
verified: true
---

## Summary

This is one of the last items on the "make it perfect" list after twelve
rounds of adoption battle-testing — the library is already adopted and this
sits well inside "adopt with constraints". `#214`'s `lane` persistence
records whether a pending event was in the priority lane so a restore can
put it back ahead of the plain inbox; the **async** engine's
`_enqueue_restored` honours that (`interpreter.py:1613`, called with
`priority=record.get("lane") == "priority"` from `base_interpreter.py:1937`),
but the **sync** engine's `_enqueue_restored`
(`sync_interpreter.py:713-717`) accepts the same `priority` keyword and then
ignores it — it always appends to the single queue in persisted order,
regardless of lane.

## Environment

- `_ref/xstate-statemachine` @ `de2da4e` (targeting 0.8.1; `__version__` still
  0.8.0)
- `.venv-main`, `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`, cwd `C:/Users/basil`

## Minimal reproduction

```python
"""DE-L5 repro: SyncInterpreter._enqueue_restored ignores the persisted
priority lane. STANDALONE: stdlib + xstate_statemachine only. Run from cwd
C:/Users/basil.
"""
import sys, json
sys.path.insert(
    0,
    "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/"
    "xstate-statemachine/src",
)
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter

cfg = {"id": "m", "initial": "w", "states": {"w": {"on": {"A": "w", "B": "w"}}}}
m = create_machine(cfg, logic=MachineLogic())
i = SyncInterpreter(m).start()
snap = json.loads(i.get_snapshot())
# 'A' recorded as normal-inbox, 'B' recorded as priority lane -- on restore
# a priority-lane record is supposed to be re-admitted ahead of the inbox.
snap["pending_events"] = [
    {"type": "A", "payload": {}, "lane": "normal"},
    {"type": "B", "payload": {}, "lane": "priority"},
]
snap = json.dumps(snap)
r = SyncInterpreter.from_snapshot(snap, m)
order = [getattr(e, "type", e) for e in r._event_queue]
print("restored queue order:", order)
reproduced = order == ["A", "B"]
print("priority lane not honoured (B stayed behind A):", reproduced)
print()
print("REPRODUCED:", reproduced)
sys.exit(1 if reproduced else 0)
```

Output on `de2da4e`:

```
restored queue order: ['A', 'B']
priority lane not honoured (B stayed behind A): True
```

## Observed behaviour

`B` is recorded with `lane: "priority"` but restores at its original
persisted-order position (behind `A`), identical to what a `lane: "normal"`
record would do. The `priority` keyword argument reaching
`SyncInterpreter._enqueue_restored` is accepted but never consulted.

## Expected behaviour

A restored event whose persisted record carries `lane: "priority"` should be
re-admitted ahead of the plain inbox on the sync engine too, matching the
async engine's behaviour for the same persisted record shape (`#214`'s
stated guarantee: "a restore puts it back ahead of the inbox rather than
demoting it to plain inbox traffic").

## Root cause analysis

`sync_interpreter.py:713-717`:

```python
def _enqueue_restored(
    self, event: AnyEvent, *, priority: bool = False
) -> None:
    # The sync engine has one queue; a priority-lane record restores
    # at its recorded position (the lane is persisted first).
    self._event_queue.append(event)
```

The comment claims the lane is honoured "because it is persisted first" —
but the implementation only ever appends; it never inspects `priority` to
insert at the front (or otherwise ahead of already-appended inbox events).
Contrast with `interpreter.py:1613` (async engine's `_enqueue_restored`),
which does branch on `priority` to place the event ahead of the plain inbox.

## Impact

Low, documented-gap shape (per our round-12 security track): a supervisor
that relies on priority-lane events (e.g. a restored external control
signal) jumping the queue on restore gets silently demoted to FIFO-with-the-
rest-of-the-inbox specifically on the sync engine, while the async engine
honours the same persisted record correctly — a service-kind asymmetry.

## Proposed fix

Give `SyncInterpreter._enqueue_restored` the same branch the async engine
has: when `priority=True`, insert the event ahead of any already-restored
plain-inbox events (e.g. `self._event_queue.appendleft(event)` if
`_event_queue` is a `deque`, or track a priority insertion index) rather than
unconditionally appending.

## Acceptance criteria

- A new test (e.g. `test_sync_restore_honours_priority_lane`) restores a
  snapshot with a mix of `lane: "normal"` and `lane: "priority"` pending
  events on `SyncInterpreter` and asserts the priority-lane event is queued
  ahead of the normal-lane one, matching the existing async-engine test for
  the same shape.
- The async engine's existing priority-lane restore behaviour is unchanged.

## Verification

- Repro run from the neutral cwd `C:/Users/basil` with the `.venv-main`
  interpreter: **exit 1**, no `ImportError`, output as quoted above —
  `restored queue order: ['A', 'B']`, i.e. the priority-lane record stayed
  behind the inbox record, and `REPRODUCED: True`.
- The code block under "## Minimal reproduction" is **byte-identical** to
  `repro/DE-L5-repro.py` (1137 bytes, compared programmatically).
- Root-cause lines confirmed open in current source at `de2da4e`:
  - `sync_interpreter.py:713-718` — `_enqueue_restored(self, event, *,
    priority: bool = False)` whose body is a bare
    `self._event_queue.append(event)`. The `priority` parameter is
    accepted and never read; the in-source comment ("a priority-lane
    record restores at its recorded position") is quoted verbatim in the
    Root cause section above.
  - `interpreter.py:1613-1624` — the async engine's override, which **does**
    branch: `if priority: self._priority_queue.append((event,
    is_system_event(event))); ... return`, with the `#214` comment "goes
    back into the lane, ahead of the inbox, with engine standing -- not
    demoted to inbox traffic."
  - `base_interpreter.py:1937-1939` — the shared caller,
    `interpreter._enqueue_restored(ev, priority=record.get("lane") ==
    "priority")`, confirming both engines are handed the same lane
    information from the same persisted record.
- So the persisted `lane` is produced correctly and consumed correctly by
  one engine and discarded by the other — a service-kind asymmetry, which
  is exactly what this issue reports.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 320` searched for `priority lane`, `_enqueue_restored`,
  `sync-interpreter`. `#214`, `#192`, `#107` and `#180` all touch the
  priority lane and are all CLOSED; none concerns the sync engine's
  restore path ignoring the lane.

## Related

- our round-12 security track §1 (our carried restore-observability finding row: "carried, unverified
  this pass (Low)" — this issue re-verifies it fresh on `de2da4e` and finds
  it STILL-PRESENT)
- `base_interpreter.py:1937` / `interpreter.py:1613` (async engine's
  correct handling of the same persisted record)
