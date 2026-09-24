---
r4: R4-14
title: "Bug: dict/non-str event `type` raises untyped AttributeError/TypeError, escaping the documented exception hierarchy"
labels: [bug, severity/medium, area/events, area/validation]
severity: Medium
repro_script: repro/R4-14_untyped_event_type_errors.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`_prepare_event` accepts a dict event and pops `"type"` with no
`isinstance(str)` check, then forwards whatever it finds to
`_check_strict` → `UnknownEventError.__init__`, which itself crashes with
an untyped `AttributeError`/`TypeError` when the type is not a `str` (e.g.
`difflib.get_close_matches(None, known, ...)`). Separately, the final
`else` branch of `_prepare_event` — reached for any object that is not a
`str`, `dict`, known `Event` subclass, or duck-typed event — raises a bare
Python `TypeError`, not a library exception, even though the library
documents a single catch-all `XStateMachineError` hierarchy. A caller doing
`except XStateMachineError` to safely reject malformed input from a wire
decoder does not catch either shape.

## Environment

- Commit: `5e07ba8` (post-0.8.0, pre-0.8.1 tag; `__version__` reports `0.8.0`)
- Python: 3.13.7
- Install: editable (`pip install -e .`) against
  `C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine`

## Minimal reproduction

```python
"""R4-14: a dict event with a non-str `type` (or a non-event object) raises
an UNTYPED AttributeError/TypeError instead of a documented
XStateMachineError subclass -- escaping `except XStateMachineError`.

`_prepare_event` (base_interpreter.py ~1616-1619) pops `type` from a dict
event with no `isinstance(str)` check and forwards it straight to
`_check_strict` -> `UnknownEventError.__init__`, which calls
`difflib.get_close_matches(event_type, known, ...)` -- that crashes with a
bare AttributeError/TypeError when `event_type` is not a `str` (e.g. `None`
or `123`). Separately, `_prepare_event`'s final `else` branch (case 5, "any
non-event object") raises a bare builtin `TypeError`, not a library
exception, even though the docstring documents this as the "unsupported
format" path.

EXPECTED: any malformed event given to send() raises a typed
XStateMachineError subclass, catchable via `except XStateMachineError`.
OBSERVED: dict events with a non-str `type` raise untyped
AttributeError/TypeError, and non-event objects raise a bare TypeError that
`except XStateMachineError` does not catch.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

from xstate_statemachine import MachineLogic, SyncInterpreter, XStateMachineError, create_machine

CFG = {
    "id": "m",
    "initial": "a",
    "states": {"a": {"on": {"GO": "#m.b"}}, "b": {}},
}


def main() -> int:
    untyped_dict_cases = []
    for strict in (False, True):
        i = SyncInterpreter(create_machine(CFG, logic=MachineLogic()), strict=strict)
        i.start()
        for ev in ({"type": None}, {"type": 123}):
            try:
                i.send(ev)
                untyped_dict_cases.append((strict, ev, "accepted"))
            except XStateMachineError as exc:
                untyped_dict_cases.append((strict, ev, f"typed {type(exc).__name__}"))
            except Exception as exc:  # noqa: BLE001
                untyped_dict_cases.append((strict, ev, f"UNTYPED {type(exc).__name__}: {exc}"))

    i2 = SyncInterpreter(create_machine(CFG, logic=MachineLogic()))
    i2.start()
    bare_type_error_cases = []
    for ev in (None, 123, b"B", ["GO"], object()):
        try:
            i2.send(ev)
            bare_type_error_cases.append((type(ev).__name__, "accepted"))
        except XStateMachineError as exc:
            bare_type_error_cases.append((type(ev).__name__, f"typed {type(exc).__name__}"))
        except TypeError as exc:
            bare_type_error_cases.append((type(ev).__name__, f"bare TypeError: {exc}"))

    print("dict-with-non-str-type cases:")
    for row in untyped_dict_cases:
        print(" ", row)
    print("\nnon-event-object cases:")
    for row in bare_type_error_cases:
        print(" ", row)

    n_untyped = sum(1 for r in untyped_dict_cases if "UNTYPED" in r[2])
    n_bare = sum(1 for r in bare_type_error_cases if "bare TypeError" in r[1])

    defect_present = n_untyped > 0 or n_bare > 0
    print(
        f"\nOBSERVED: {n_untyped}/4 dict-with-non-str-type cases raised an "
        f"untyped error, {n_bare}/5 non-event objects raised a bare TypeError"
    )
    print(
        "EXPECTED: 0/4 and 0/5 -- every malformed event raises a typed "
        "XStateMachineError subclass"
    )
    print("RESULT:", "FAIL - defect present" if defect_present else "PASS")
    return 1 if defect_present else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Observed behaviour

```
dict-with-non-str-type cases:
  (False, {'type': None}, "UNTYPED AttributeError: 'NoneType' object has no attribute 'startswith'")
  (False, {'type': 123}, "UNTYPED AttributeError: 'int' object has no attribute 'startswith'")
  (True, {'type': None}, "UNTYPED TypeError: 'NoneType' object is not iterable")
  (True, {'type': 123}, "UNTYPED TypeError: 'int' object is not iterable")

non-event-object cases:
  ('NoneType', "bare TypeError: Unsupported event type passed to send(): <class 'NoneType'>")
  ('int', "bare TypeError: Unsupported event type passed to send(): <class 'int'>")
  ('bytes', "bare TypeError: Unsupported event type passed to send(): <class 'bytes'>")
  ('list', "bare TypeError: Unsupported event type passed to send(): <class 'list'>")
  ('object', "bare TypeError: Unsupported event type passed to send(): <class 'object'>")

OBSERVED: 4/4 dict-with-non-str-type cases raised an untyped error, 5/5 non-event objects raised a bare TypeError
EXPECTED: 0/4 and 0/5 -- every malformed event raises a typed XStateMachineError subclass
RESULT: FAIL - defect present
```

(exit code 1)

## Expected behaviour

The library documents a single exception hierarchy rooted at
`XStateMachineError` (see `exceptions.py`), and `_prepare_event`'s own
docstring says: "Raises: TypeError: If the input cannot be resolved into a
valid event format" — implying malformed-input handling is a deliberate,
documented contract, not an accident. A consumer relying on
`except XStateMachineError` as the single catch-all for "this send() call
had a problem the caller can react to" (e.g. reject a malformed message off
a wire and continue) is a reasonable, encouraged usage pattern; both shapes
here defeat it silently by escaping through builtin exception types.

## Root cause analysis

Two related gaps, one function:

1. `base_interpreter.py:1616-1619` (`_prepare_event`, case 2 — dict input):
   ```python
   if isinstance(event_or_type, dict):
       data = event_or_type.copy()
       event_type = data.pop("type", "UnnamedEvent")
       return Event(type=event_type, payload=data)
   ```
   `event_type` is never checked to be a `str`. It is stored on the `Event`
   and later reaches `_check_strict` (`base_interpreter.py:1523-1559`),
   which under `strict=True` calls
   `self.machine.is_known_event(event.type, user_sent=True)`
   (`models.py:1543` calling `.startswith`/iteration on `event_type`) and,
   on a miss, `UnknownEventError(event.type, ...)`
   (`base_interpreter.py:1549-1551`) whose `__init__`
   (`exceptions.py:347-359`) calls
   `difflib.get_close_matches(event_type, known, n=1, cutoff=0.6)` — all of
   these assume `event_type` is a `str` and raise untyped
   `AttributeError`/`TypeError` when it is not `str` (`None`/`int` in the
   repro). This is reachable even under `strict=False` because
   `is_known_event`/`startswith` in the non-strict validation path (schema
   lookup via `self.machine.event_schemas.get(event.type)`,
   `base_interpreter.py:1552`) still assumes hashable/str-like input, and
   the fuzz harness shows both `strict=False` and `strict=True` produce
   untyped errors (via different call paths: `AttributeError` from
   `.startswith` when not strict-validating the type shape early enough,
   `TypeError` from iteration under `strict=True`).

2. `base_interpreter.py:1635-1637` (`_prepare_event`, case 5 — unsupported
   object):
   ```python
   raise TypeError(
       f"Unsupported event type passed to send(): {type(event_or_type)}"
   )
   ```
   is a bare builtin `TypeError`, not an `XStateMachineError` subclass,
   despite the surrounding docstring calling this "an unsupported format"
   — the exact kind of caller-facing condition the library's typed
   exception hierarchy exists for.

Confirmed by `battle-5e07ba8/fuzz/repros.py` `d4` (dict/non-str `type`,
merged here as `D-fuzz-4`) and `d5` (non-event objects, `D-fuzz-5`); the
register notes these were merged as "one missing type guard in one
function" and the in-track triage already treats them as the same defect
class.

## Impact

**General users:** any application that deserializes events from an
external source (HTTP body, message queue, websocket frame) and forwards
the decoded dict/object straight to `send()` — a very common integration
pattern — can trip this the moment a producer sends a malformed or
mistyped `"type"` field. The library's own documented safety net
(`except XStateMachineError`) does not catch it, so the untyped exception
propagates to whatever generic handler the caller has, typically crashing
a request handler or, worse, an unguarded async task.

**Order-management scenario:** an order-processing service accepting
inbound `{"type": ..., ...}` events from a message bus is exposed to
however the upstream producer serializes its event type field. A single
malformed message (`{"type": null, ...}` from a JSON decoder given bad
input, or any non-JSON-mappable object slipping through a lenient decoder)
takes down the handler that was written specifically to catch and log
`XStateMachineError` and move on, instead of a well-defined `send()`
failure.

## Proposed fix

- In `_prepare_event`'s dict branch, validate `event_type` is a `str`
  before constructing the `Event`; if not, raise a new/existing
  `XStateMachineError` subclass (e.g. `InvalidEventPayloadError` or a new
  `InvalidEventTypeError`) with a clear message instead of silently
  forwarding a non-`str` value downstream.
- Make `UnknownEventError.__init__` defensive against a non-`str`
  `event_type` (e.g. `str(event_type)` before calling
  `difflib.get_close_matches`, or short-circuit and skip the fuzzy-match
  hint for non-`str` input) so it is `repr()`/`str()`-safe regardless of
  what upstream passes it — this closes the crash even if some other call
  site is later found to pass a non-`str` type.
- Change the final `else` branch of `_prepare_event`
  (`base_interpreter.py:1635-1637`) to raise a library exception type
  (e.g. `InvalidEventPayloadError` or a new dedicated
  `UnsupportedEventTypeError`) instead of a bare `TypeError`. This is a
  docstring-visible behavior change, but the current docstring already
  documents the bug ("Raises: TypeError...") rather than the intended
  contract.

Compatibility: additive for the typed-exception cases; changing the bare
`TypeError` to a library exception subclass is a minor breaking change for
any caller specifically catching `TypeError` here, but `XStateMachineError`
subclasses can be made to also inherit from `TypeError` if strict
backward-compatibility is required.

## Acceptance criteria

- [ ] `repro/R4-14_untyped_event_type_errors.py` exits 0
- [ ] New test `tests/test_events.py::test_non_str_dict_event_type_raises_typed_error`
      covers `{"type": None}` / `{"type": 123}` under both `strict=False`
      and `strict=True`
- [ ] New test `tests/test_events.py::test_unsupported_event_object_raises_typed_error`
      covers `None`, `int`, `bytes`, `list`, `object()` inputs to `send()`
- [ ] Both tests assert the raised exception is an `XStateMachineError`
      subclass, catchable via `except XStateMachineError`

## Related

- Merges register rows for `D-fuzz-4` (High, downgraded to Medium) and
  `D-fuzz-5` (Medium) — register: "one missing type guard in one function,
  and the in-track triage already noted they are the same class"
- R4-38 (Low): a related but distinct gap in the same defensive-coding
  family — a self-referential config dict escapes `XStateMachineError` via
  `RecursionError`
- Register source ids: `battle-5e07ba8/fuzz/repros.py` `d4`, `d5`

## Verification

- Date: 2026-09-19
- Python: 3.13.7
- Commit: `5e07ba8`
- Ran `repro/R4-14_untyped_event_type_errors.py` in a fresh process: output
  matched the Observed behaviour section verbatim; exit code 1.
- Confirmed `base_interpreter.py`'s `_prepare_event` dict branch (case 2)
  pops `"type"` with no `isinstance(str)` check, and the final `else`
  branch (case 5) raises a bare `TypeError` — both match the cited source.
- No duplicate or overlapping open/closed GitHub issue found
  (`gh issue list --search "event type"` returned no match on this
  untyped-exception-escape defect).
