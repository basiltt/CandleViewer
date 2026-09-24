---
r5: R5-17
title: "Bug: #113's non-str event-type guard is enforced on send() but not on the restore path"
labels: [bug, severity/medium, area/persistence]
severity: Medium
repro_script: repro/R5-17_non-str-event-type-via-restore.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

`#113` made `send()` raise `InvalidEventError` for a non-`str` event `type`
instead of letting it escape the type hierarchy uncaught. That guard lives
entirely in `send()`'s synchronous entry point; `from_snapshot()`
reconstructs any queued `pending_events` via `events.restore_event()`, which
reads `record["type"]` and hands it straight to the `Event` constructor with
no type check at all, and `persistence.check_shape()` only asserts that a
pending-event record's `type` KEY is present, never that its value is a
`str`. A snapshot blob is therefore the one way to get a non-`str` event
type into a live, running interpreter — and a snapshot is exactly the
artifact that arrives from outside the process (Redis, disk, a queue),
whereas `send()` is called by the application's own code. This is the
persistence-relevant half of `#113`'s trust boundary and it is the half
facing untrusted storage.

## Environment

- Commit: `3ed3099` (`main`, unreleased 0.8.1; `__version__` still reports
  `0.8.0`, so this build is identified by commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source
  modified.

## Minimal reproduction

```python
"""R5-17 repro: #113's non-`str` event-type guard is enforced on `send()`
but not on the restore path.

`send()` rejects a non-str event type with `InvalidEventError`
(`base_interpreter.py::_prepare_event`). `from_snapshot()` reconstructs
pending events via `events.restore_event()`, which reads `record["type"]`
with no type check, and `persistence.check_shape()` only asserts the `type`
key is PRESENT on a pending-event record, never that it is a string. A
snapshot blob is therefore the one way to get a non-`str` event type into a
live, running interpreter -- and a snapshot is exactly the artifact that
comes back from untrusted storage (Redis/disk/a queue).

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import InvalidEventError

CFG = {
    "id": "rp",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}}, "b": {}},
}


def bump(interpreter, ctx, event, action_def):
    ctx["n"] += 1


def build():
    return create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))


async def main() -> int:
    live = Interpreter(build(), clock=SimulatedClock())
    await live.start()
    send_rejected = False
    try:
        await live.send(42)
    except InvalidEventError:
        send_rejected = True
    await live.stop()

    blob = {
        "version": 1,
        "status": "running",
        "context": {"n": 0},
        "state_ids": ["rp.a"],
        "configuration": ["rp", "rp.a"],
        "pending_events": [{"kind": "event", "type": 42, "payload": {}}],
    }
    restored = Interpreter.from_snapshot(json.dumps(blob), build(), clock=SimulatedClock())
    await restored.start()
    await asyncio.sleep(0.05)
    n = restored.context["n"]
    status = restored.status
    await restored.stop()

    print("OBSERVED:")
    print(f"  send(42) on a live interpreter rejected  = {send_rejected}")
    print(f"  from_snapshot() with pending type=42     = ACCEPTED (no exception)")
    print(f"  restored interpreter status              = {status}")
    print(f"  bump() ran (context.n)                   = {n}  (0 = event matched nothing)")

    print("EXPECTED:")
    print("  from_snapshot() applies the same non-str type guard #113 gives send(),")
    print("  refusing (or coercing) a pending_events record whose 'type' is not a str")

    failed = send_rejected and status == "running"
    print("RESULT:", "FAIL - restore path accepts what send() refuses" if failed else "PASS")
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED:
  send(42) on a live interpreter rejected  = True
  from_snapshot() with pending type=42     = ACCEPTED (no exception)
  restored interpreter status              = running
  bump() ran (context.n)                   = 0  (0 = event matched nothing)
EXPECTED:
  from_snapshot() applies the same non-str type guard #113 gives send(),
  refusing (or coercing) a pending_events record whose 'type' is not a str
RESULT: FAIL - restore path accepts what send() refuses
```

The battle script (`persistence/n7_restore_event_type.py`, re-run fresh)
shows the full picture: five hostile non-`str` types (`42`, `None`,
`['GO']`, `{'x': 1}`, `True`), each restored via `restore_event()` in
isolation, each producing `Event(type=<non-str>, isinstance(str)=False)`;
end-to-end through `from_snapshot()`, all five are **ACCEPTED** into a live
`status="running"` interpreter with `hooks=[]` (no drop, no unhandled hook —
the event matches nothing and vanishes silently).

## Expected behaviour

The library's own stated contract for `#113`: an event `type` that is not a
`str` is invalid input and must raise a typed `InvalidEventError` (also a
`TypeError`) rather than being accepted into the interpreter. `#113`
enforces this at `base_interpreter.py`'s `send()`/`_prepare_event()`
(`InvalidEventError` raised when `event_or_type` is not `str`, dict-with-
valid-type, or a known event class — see `exceptions.py`, `InvalidEventError`
docstring: "Raised by `send()` for a non-`str` `type` ... Replaces the bare
`TypeError`"). `from_snapshot()` restoring a queued event is functionally
equivalent to that same event being `send()`-ed once the interpreter
resumes; the same input-validation contract should apply regardless of
which door the event enters through, and doubly so here since a snapshot is
explicitly the artifact `persistence.py::check_shape` already exists to
validate against corruption from external storage.

## Root cause analysis

- `persistence.py:189-196` (`check_shape`), the `pending_events` /
  `deferred` validation loop:
  ```python
  if not isinstance(val, list) or not all(
      isinstance(r, dict) and "type" in r for r in val
  ):
      fail(f"'{key}' must be a list of event records with a 'type'")
  ```
  This asserts only that the `type` KEY exists (`"type" in r`), never that
  `r["type"]` is a `str`.
- `events.py::restore_event()` reads `record["type"]` and constructs the
  `Event` directly, with no `isinstance` check — unlike `send()`'s
  `_prepare_event` (`base_interpreter.py:1885` `isinstance(event_or_type,
  str)` branch, `:1892`/`:1898`/`:1918` raising `InvalidEventError` for every
  other shape).
- `from_snapshot()` (`base_interpreter.py`, restore path) calls
  `interpreter._enqueue_restored(restore_event(record))` for each
  `pending_events` record with no additional gate, so the malformed `Event`
  reaches the live interpreter's queue unfiltered.

## Impact

General: `#113`'s trust boundary is only half-enforced. Any code path that
writes `pending_events` into a snapshot (the library's own persistence
round-trip, or a hand-constructed/corrupted blob) can smuggle a non-`str`
event type past the guard that exists specifically to keep such values out
of `Event.type`. Today's consequence is mild — the event matches nothing and
is dropped by `onUnhandled` with no hook firing — but the invariant `#113`
established (an `Event.type` is always a `str`) is silently broken for any
code downstream that assumes it (equality checks, string formatting,
logging, routing tables keyed by `type`).

Order-management scenario: a snapshot round-tripped through Redis or a
message queue is precisely the untrusted-storage boundary `#113` was
written to defend — a malformed or tampered blob (or simply a bug in an
upstream serializer that emits `type: null` or an int) restores cleanly
into a live, healthy-looking OMS interpreter carrying an invalid pending
event, rather than being refused at the door the way the same value would
be if sent live.

## Proposed fix

Extend `persistence.check_shape()`'s `pending_events`/`deferred` validation
to assert `isinstance(r["type"], str)` in addition to key presence, raising
`SnapshotCorruptError` for a non-`str` type (write-side / structural gate,
consistent with `check_shape`'s existing role). Additionally, make
`events.restore_event()` itself defensive — raise (or wrap into)
`InvalidEventError`/`SnapshotCorruptError` when `record["type"]` is not a
`str` — so the invariant holds at the construction site too, not only at the
one call site that currently validates the envelope, matching `send()`'s
`_prepare_event` behaviour for the same class of bad input.

Compatibility: a `pending_events` blob with a non-`str` type is rejected
where it previously loaded silently; every such blob today produces a
subsequently-invisible dead event, so rejecting it is strictly an
improvement, but call it out in the changelog since `from_snapshot()`
becomes stricter.

## Acceptance criteria

- [ ] `repro/R5-17_non-str-event-type-via-restore.py` exits `0`.
- [ ] `tests/test_persistence.py::test_check_shape_rejects_non_str_pending_event_type`
      — parametrised over `42`, `None`, `['GO']`, `{'x': 1}`, `True`.
- [ ] `tests/test_persistence.py::test_from_snapshot_rejects_non_str_pending_event_type`
      — end-to-end: `from_snapshot()` raises rather than accepting.
- [ ] `tests/test_events.py::test_restore_event_rejects_non_str_type`
      — unit-level guard directly on `restore_event()`.
- [ ] `tests/test_events.py::test_restore_event_accepts_str_type_unchanged`
      — regression guard for the valid-`str` case.
- [ ] Changelog entry noting `from_snapshot()` now validates
      `pending_events`/`deferred` event types as `str`, closing the `#113`
      gap on the restore path.

## Related

- Round-4 issue: `#113` (non-`str` event-type guard on `send()`; this issue
  is the restore-path half `#113` did not cover).
- Register id: `D5-persistence-2` (§3, `33-r5-findings-register.md`).
- Evidence: `battle-3ed3099/persistence/n7_restore_event_type.py`;
  `triage-r5/t1_snapshot.py::D` (asymmetry confirmed in one process:
  `send(42)` raises, the same value through `pending_events` is accepted).

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `3ed3099` (`main`, unreleased 0.8.1)
- `repro/R5-17_non-str-event-type-via-restore.py` re-run fresh: exit `1`
  (FAIL — defect still present), matching the recorded observed output
  (`send(42)` rejected, `from_snapshot()` with pending `type=42` accepted,
  restored `status = running`, `bump()` did not run).
- Root cause re-checked against source: `persistence.py:189-196`
  (`check_shape`'s `pending_events`/`deferred` loop, `isinstance(r, dict)
  and "type" in r` with no `isinstance(r["type"], str)` check — exact line
  match); `events.py::restore_event()` (reads `record["type"]` directly with
  no type check before constructing `Event`/`DoneEvent`/`ErrorEvent`);
  `base_interpreter.py:1885/1892/1898/1918` (`_prepare_event`'s `isinstance
  (event_or_type, str)` branch and the `InvalidEventError` raises for every
  other shape — exact line match) — confirms `send()` enforces the guard
  `restore_event()`/`check_shape()` do not.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 150 --search "non-str event type restore"` — hits `#110` (general
  from_snapshot validation, CLOSED) and `#131` (DoneEvent.data stringified,
  CLOSED), neither of which covers the non-str `type` guard specifically;
  `gh issue view 113` confirms `#113` (the `send()`-side guard this issue
  extends) is CLOSED. This issue correctly frames itself as the
  restore-path half `#113` did not cover, not a duplicate.
- `verified: true` set in frontmatter.

