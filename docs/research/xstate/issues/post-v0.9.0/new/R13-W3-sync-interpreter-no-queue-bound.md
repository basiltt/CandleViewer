---
id: R13-W3
title: "Docs: SyncInterpreter has no max_queue_size / overflow_policy (async-only by design)"
labels: [documentation, sync-interpreter, area/interpreter]
severity: Low
repro_script: null
commit: "v0.9.0 (91bd979)"
---

## Summary

Not a defect — filed for tracking/docs so the trust boundary is written where a
reader will find it. `Interpreter.__init__` (async) accepts `max_queue_size` /
`overflow_policy` (`interpreter.py:314-315`, #38) to bound the inbox and choose
`RAISE` / `BLOCK` / `DROP_NEWEST` behaviour at capacity. `SyncInterpreter.__init__`
takes no such parameters — its internal queue (`_event_queue: Deque[AnyEvent]`,
`sync_interpreter.py:155`) is unbounded and silently accepts every event handed
to `send()`. This is consistent with the class's stated design (single-threaded,
blocking, no admission control needed for its target use case), but nothing in
the docstring or README API table says so next to the async class's bound, and
passing the async-only kwargs to `SyncInterpreter()` is not rejected — it simply
raises `TypeError: unexpected keyword argument`, which reads as a bug report
until you check the source.

## Environment

- `xstate_statemachine` v0.9.0 (91bd979), installed from PyPI (wheel verified
  identical to tag).
- Python 3.x, Windows, stdlib + `xstate_statemachine` only.

## Minimal reproduction

Run from a neutral cwd (e.g. `<home>`) with only `xstate_statemachine`
and stdlib imported. Shows the async engine enforcing a bound under a 40-event
burst against `SyncInterpreter` silently swallowing the same burst unbounded.

```python
"""Async Interpreter enforces max_queue_size; SyncInterpreter has no such knob."""
import asyncio

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    SyncInterpreter,
    create_machine,
)

CFG = {
    "id": "m",
    "initial": "a",
    "states": {"a": {"on": {"T": "a"}}},
}


async def main() -> None:
    machine = create_machine(CFG, logic=MachineLogic())

    # --- async: bounded inbox, RAISE policy is the default surface, but we
    # ask explicitly for the reporting shape (sent / refused / dropped). ---
    i = Interpreter(machine, max_queue_size=4, overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    sent, refused = 0, 0
    for _ in range(40):
        try:
            await i.send("T", wait=False)
            sent += 1
        except Exception:
            refused += 1
    print(f"async : sent={sent} refused={refused} qsize={i._event_queue.qsize()}")
    await i.stop()

    # --- sync: no admission control exists to configure. ---
    s = SyncInterpreter(create_machine(CFG, logic=MachineLogic()))
    s.start()
    for _ in range(40):
        s.send("T")
    print(f"sync  : all 40 accepted, status={s.status}")

    # Passing the async-only kwargs to SyncInterpreter is a plain TypeError,
    # not a documented ValueError — that's the ask below.
    try:
        SyncInterpreter(
            create_machine(CFG, logic=MachineLogic()),
            max_queue_size=4,  # type: ignore[call-arg]
        )
    except TypeError as e:
        print(f"sync ctor rejects kwarg via bare TypeError: {e}")


asyncio.run(asyncio.wait_for(main(), 25))
```

Observed on `v0.9.0`:

```
async : sent=4 refused=36 qsize=4
sync  : all 40 accepted, status=running
sync ctor rejects kwarg via bare TypeError: __init__() got an unexpected keyword argument 'max_queue_size'
```

## Current state

`max_queue_size` / `overflow_policy` are async-only. `SyncInterpreter` has no
admission bound and no equivalent constructor surface. This is defensible: the
sync engine already blocks the caller for the duration of `send()`, so an
unbounded caller-owned deque is a different risk profile than an async inbox
fed by concurrent producers. But the asymmetry is currently discoverable only
by reading both source files.

## Expected behaviour / Requested change

Either of:

1. **Doc-only (preferred, smallest change):** add one sentence to
   `SyncInterpreter`'s class docstring and the README API/feature-comparison
   table stating that admission bounding (`max_queue_size` / `overflow_policy`)
   is an async-`Interpreter`-only feature, and that sync callers needing a
   bound must implement it in their own wrapper around `send()`.
2. **Small fix (optional, if maintainers want parity of the *contract* rather
   than the *feature*):** make `SyncInterpreter.__init__` accept
   `max_queue_size=None, overflow_policy=OverflowPolicy.RAISE` for signature
   compatibility with `Interpreter`, and raise a documented `ValueError` (not a
   bare `TypeError`) if a caller passes a non-`None` `max_queue_size`, so the
   rejection is a stable, documented part of the API rather than an accident
   of the parameter not existing.

## Root cause analysis

N/A — design choice, not a defect. `sync_interpreter.py:155` (`_event_queue:
Deque[AnyEvent]`, no bound); `interpreter.py:314-315,388-390` (async-only
`max_queue_size` / `overflow_policy`, validated in `__init__`).

## Impact

Low. No adopter is blocked; any project running a `SyncInterpreter` under
untrusted or bursty input must add its own admission bound in the wrapper
layer around `send()` — which we are already doing. Filed so the boundary is
written down rather than rediscovered by the next reader who greps for
`max_queue_size` and finds it only on one of the two classes.

## Proposed fix

Docstring/README sentence as in option 1 above; option 2 only if maintainers
want the constructor surfaces to match.

## Acceptance criteria

- [ ] `SyncInterpreter`'s docstring and the README API/feature table state
      explicitly that queue-bounding (`max_queue_size` / `overflow_policy`) is
      an async-`Interpreter`-only feature.
- [ ] (Optional) `SyncInterpreter.__init__` accepts the same two keyword
      names and raises a documented `ValueError` — not a bare `TypeError` —
      when a bound is requested that it cannot honour.

## Related

`R13-W3` / `W-03` in `73-r13-findings-register.md` §5 (NEEDS-WRAPPER); `#38`
(async `max_queue_size` / `overflow_policy` introduction).
