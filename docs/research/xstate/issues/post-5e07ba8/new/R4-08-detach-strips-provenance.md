---
r4: R4-08
title: "Bug: send(engine_event, wait=True) silently strips engine provenance via _detach()'s dataclasses.replace()"
labels: [bug, severity/medium, area/interpreter]
severity: Medium
repro_script: repro/R4-08_detach_strips_provenance.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`Interpreter._detach()` copies every event handed to `send(..., wait=True)`
so that the receipt map can key on a private, unshared identity. For a plain
`Event`, it does this via `dataclasses.replace()`. `Event._provenance` is
declared `init=False` (`events.py:122-124`), so `dataclasses.replace()` —
which reconstructs the object by calling `__init__` — cannot carry it
forward. The result: the *exact same* engine-minted `Event` (e.g. one
produced by `system_event(...)`, or an `xstate.error.actor.*` escalation
being forwarded/replayed) is treated as engine traffic when sent with
`wait=False`, but demoted to ordinary user traffic the moment a caller asks
for a receipt with `wait=True`. In a long-running service that forwards
escalations between supervisors and confirms delivery via receipts, or
replays a persisted engine event, this flips `onUnhandled` / `strict`
enforcement outcomes based purely on whether the caller wanted a receipt —
an effect entirely orthogonal to what `wait` is documented to mean.

## Environment

- Commit: `5e07ba8` (post-0.8.0, pre-0.8.1 tag; `__version__` reports `0.8.0`)
- Python: 3.13.7
- Install: editable (`pip install -e .`) against
  `C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine`

## Minimal reproduction

```python
"""R4-08: send(engine_event, wait=True) silently demotes an engine-minted
event to user traffic, because Interpreter._detach() rebuilds the Event
through dataclasses.replace(), which constructs via __init__ and therefore
cannot carry the init=False `_provenance` field (events.py:122-124).

Compares wait=False (no _detach path) with wait=True (_detach path) sending
the SAME engine-minted event to an onUnhandled:"error" machine.

EXPECTED (per this library's own #85/#86 contract, quoted in events.py:114-121):
    an engine-minted Event's provenance must survive re-processing; asking
    for a receipt (wait=True) must not change whether the event is treated
    as system traffic.
OBSERVED: wait=False -> status stays "running" (event honoured as system
traffic). wait=True -> status becomes "error" (UnhandledEventError): the
same object, merely re-detached for a receipt, is now user traffic.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import system_event

CFG = {
    "id": "m",
    "initial": "a",
    "onUnhandled": "error",
    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
}


async def run(wait: bool) -> str:
    interp = Interpreter(create_machine(CFG, logic=MachineLogic()))
    await interp.start()
    await interp.send(
        system_event("xstate.error.actor.child", error="boom"), wait=wait
    )
    await asyncio.sleep(0.2)
    status = interp.status
    if status == "running":
        await interp.stop()
    return status


async def main() -> int:
    status_false = await run(False)
    status_true = await run(True)
    print(f"wait=False -> status={status_false}")
    print(f"wait=True  -> status={status_true}")

    defect_present = status_false == "running" and status_true == "error"
    print(
        "\nOBSERVED:",
        "wait=True demoted the engine-minted event to user traffic "
        "(status='error')"
        if defect_present
        else "provenance preserved across both calls",
    )
    print(
        "EXPECTED: both calls report status='running' "
        "(provenance preserved regardless of wait=)"
    )
    print("RESULT:", "FAIL - defect present" if defect_present else "PASS")
    return 1 if defect_present else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
wait=False -> status=running
wait=True  -> status=error

OBSERVED: wait=True demoted the engine-minted event to user traffic (status='error')
EXPECTED: both calls report status='running' (provenance preserved regardless of wait=)
RESULT: FAIL - defect present
```

(exit code 1)

## Expected behaviour

The library's own contract, quoted from `events.py:114-121`:

> `_provenance`: #79/#85: provenance. Set ONLY by `system_event()` via the
> private `_provenance` slot, which holds an engine-owned sentinel object
> that user code cannot obtain by name.

and `is_system_event`'s docstring (`events.py:243-250`):

> Provenance, not spelling: a `DoneEvent` / `ErrorEvent` / `AfterEvent` is
> always engine-made; a plain `Event` is engine-made only when it was
> created via `system_event` … A user `Event("done.review")` is user
> traffic.

Nothing in that contract makes provenance conditional on whether the caller
requested a receipt. `wait=True`/`wait=False` is documented purely as "do I
get a `Receipt` back", not as a channel that can flip `is_system_event()`.
XState v5's own model treats an event's origin (internal engine vs.
external) as intrinsic to the event, independent of how the caller consumes
the result of dispatching it (https://stately.ai/docs/transitions#wildcard-transitions).

## Root cause analysis

- `interpreter.py:701-716`, `_detach()`:
  ```python
  if isinstance(event_obj, Event):
      return dataclasses.replace(event_obj)
  replace = getattr(event_obj, "_replace", None)  # NamedTuple events
  return replace() if callable(replace) else copy.copy(event_obj)
  ```
  `dataclasses.replace()` constructs a new instance by calling
  `Event.__init__` with the fields it can see. `_provenance` is declared
  `init=False` (`events.py:122-124`), so `replace()` has no way to pass it
  through — the new instance gets `_provenance`'s class-level `default=None`
  instead of the original `_ENGINE_MARK` sentinel. The `NamedTuple`/`copy.copy`
  branches on the same line are unaffected (`_replace()` on a NamedTuple
  copies every field including engine-defined ones; `copy.copy` performs a
  shallow attribute copy that does not go through `__init__`).
- `interpreter.py:602-603` calls `_detach()` whenever a caller-supplied
  `Event` object is queued with `wait=True` (to give the receipt map a
  private identity — see `_detach`'s own docstring at `interpreter.py:702-712`,
  which explains the identity requirement but not this side effect on
  provenance).
- Confirmed independently by two probes cited in the register:
  `probes/main-5e07ba8/r44_detach_ab.py` (wait=False vs wait=True on the
  same event) and `probes/main-5e07ba8/r43_detach_strips_provenance.py`
  (direct `is_system_event(dataclasses.replace(ev))` check, which prints
  `False`).
- This is the same underlying mechanism as R4-40 (provenance not surviving
  `deepcopy`/`pickle`, `events.py:240,253`): whichever reconstruction path
  goes through `Event.__init__` rather than a raw attribute copy loses
  `_provenance`. `_detach`'s dataclass branch is the in-process instance of
  that same defect class; R4-40 is the cross-process instance, tracked
  separately because it has a real, complete fix here versus a documented
  limitation there.

## Impact

**General users:** any code that re-sends, forwards, or replays an
engine-minted `Event` and *also* wants a receipt for it (a very natural
combination — "did my escalation propagate?") gets a silent, wait-dependent
change in how the event is classified by `onUnhandled`, `strict`, and the
`"*"` wildcard matcher.

**Order-management scenario:** a supervisor actor forwards a child's
`xstate.error.actor.*` event up to its own parent and awaits `send(...,
wait=True)` to confirm the forward "took" before acknowledging the child.
On a machine configured `onUnhandled: "error"` (a reasonable choice for
"any event I don't explicitly model is a bug"), this innocuous
confirmation-seeking `wait=True` call throws `UnhandledEventError` and can
terminate the interpreter — the exact regression class R4-08's sibling
`_provenance` mechanism (#85/#86) was introduced to close, reopened by
`_detach()`.

## Proposed fix

Audit every site that reconstructs an `Event` and explicitly re-stamp
`_provenance` where the source carried it:

```python
@staticmethod
def _detach(event_obj: Any) -> Any:
    if isinstance(event_obj, Event):
        new = dataclasses.replace(event_obj)
        if event_obj._provenance is not None:
            object.__setattr__(new, "_provenance", event_obj._provenance)
        return new
    replace = getattr(event_obj, "_replace", None)
    return replace() if callable(replace) else copy.copy(event_obj)
```

Treat this as one systematic audit rather than a single patch: search for
every other `dataclasses.replace(...)` call site on an `Event` in the
codebase (persistence/restore paths, any future helper), and add a unit
test asserting `is_system_event(_detach(system_event("x"))) is True` so a
future reconstruction path cannot silently regress this again. `__deepcopy__`
/ `__reduce__` (R4-40) should be fixed under the same audit for consistency,
even though that one is being tracked separately for severity reasons.

Compatibility: purely additive — no observable behavior changes except that
the previously-lost provenance is now preserved, which is the documented
intent.

## Acceptance criteria

- [ ] `repro/R4-08_detach_strips_provenance.py` exits 0
- [ ] New test `tests/test_events.py::test_detach_preserves_engine_provenance`
      (or equivalent under `tests/`) asserts
      `is_system_event(Interpreter._detach(system_event("x")))` is `True`
- [ ] New/updated test covering `send(system_event(...), wait=True)` against
      an `onUnhandled: "error"` machine keeps `status == "running"`
- [ ] Audit note in `CHANGELOG.md` referencing the fixed reconstruction
      path(s)

## Related

- R4-40 (provenance lost across `deepcopy`/`pickle`) — same underlying
  mechanism, cross-process instance, tracked separately
- R4-09 (register-refuted counterpart) — not filed
- Register source ids: `probes/main-5e07ba8/r44_detach_ab.py`,
  `probes/main-5e07ba8/r43_detach_strips_provenance.py`,
  `probes/main-5e07ba8/r1_provenance_copy.py`
- Prior library issues referenced in source comments: #75 (`_detach`), #79,
  #85, #86 (provenance/system-event mechanism)

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (venv: `xstate-statemachine/.venv-main`)
- Commit: `5e07ba8`
- Ran `repro/R4-08_detach_strips_provenance.py` in a fresh process (60 s
  cap): output matched the Observed block verbatim; exit code `1`.
- Confirmed root cause at `src/xstate_statemachine/events.py:114-124`
  (`_provenance: Any = field(default=None, init=False, compare=False,
  repr=False)`) and `src/xstate_statemachine/interpreter.py:701-716`
  (`_detach`, `dataclasses.replace(event_obj)` on the `Event` branch) — line
  ranges and code exactly as cited.
- Corrected the Expected-behaviour citation: `stately.ai/docs/event-descriptors`
  404s; replaced with `https://stately.ai/docs/transitions#wildcard-transitions`,
  fetched and confirmed it documents event descriptors/wildcard matching as
  intrinsic to the event's `type`, supporting the "origin is intrinsic to the
  event" claim.
- Searched `gh issue list -R basiltt/xstate-statemachine --state all --limit
  120 --search "detach provenance"`: no matching open/closed issue; no
  duplicate found.
- No project name/label leakage found in the file.
