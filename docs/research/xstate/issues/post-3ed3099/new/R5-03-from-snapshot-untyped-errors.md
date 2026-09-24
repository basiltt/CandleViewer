---
r5: R5-03
title: "Bug: `from_snapshot()` leaks raw `TypeError`/`AttributeError`/`ValueError` for hostile `version`/`status`/`history`/`actors`/`system`/`deferred` fields, escaping `except XStateMachineError`"
labels: [bug, severity/high, area/persistence, area/validation]
severity: High
repro_script: repro/R5-03_from_snapshot_untyped_errors.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

`#110` added `persistence.check_shape()` so that a corrupted snapshot is
refused with a typed `SnapshotCorruptError` "rather than a bare
KeyError/AttributeError -- or, worse, silently accepted" (its own docstring).
The check covers only the fields the original reporters named -- `status`
membership, `context`, `state_ids`, `configuration`, `pending_events`,
`deferred` *list shape*. Every other field a snapshot carries is read
unguarded, and one guard (`check_version`) runs **before** `check_shape` and
raises from a bare `int()`. Eleven of thirteen hostile single-field inputs
escape as untyped `ValueError` / `TypeError` / `AttributeError`, so the
documented `except XStateMachineError` handler -- the one contract a caller
restoring from Redis, disk or a queue has -- does not catch them.

## Environment

- Commit: `3ed3099` (`main`, "Merge pull request #139 from fix/0.8.1-round4"),
  unreleased 0.8.1 (`__version__` still reports `0.8.0`; keyed on the commit)
- Python: 3.13.7 (CPython, 64-bit)
- OS: Windows 11 Pro (10.0.26200)
- Install: editable (`pip install -e .`) into a project venv
- Found by our adoption audit (#26), round 5.

## Minimal reproduction

```python
# -*- coding: utf-8 -*-
"""R5-03: `from_snapshot()` leaks untyped exceptions for hostile snapshot fields.

#110 added `check_shape()` so a corrupted blob raises a typed
`SnapshotCorruptError`, and #45 documents `XStateMachineError` as the single
base class a caller catches. Neither holds: `version`, `status`, `history`,
`actors`, `system`, `deferred` and a non-string pre-parse payload all escape
as bare `TypeError` / `AttributeError` / `ValueError`.

Standalone: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import json
import logging
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.exceptions import XStateMachineError

CFG = {"id": "fz", "initial": "b", "states": {"b": {"on": {"GO": "c"}}, "c": {}}}


def mk():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


def classify(payload) -> str:
    """Restore `payload` and report how the failure (if any) was typed."""
    try:
        SyncInterpreter.from_snapshot(payload, mk())
        return "ACCEPTED"
    except XStateMachineError as exc:
        return f"TYPED:{type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001
        return f"UNTYPED:{type(exc).__name__}: {exc}"


def main() -> int:
    good = SyncInterpreter(mk()).start().get_persisted_snapshot()

    # Single-field mutations of an otherwise VALID snapshot.
    mutations = {
        "version='x'": ("version", "x"),
        "version=None": ("version", None),
        "version={}": ("version", {}),
        "status=[]": ("status", []),
        "status={}": ("status", {}),
        "history=3.14": ("history", 3.14),
        "history='junk'": ("history", "junk"),
        "actors=7": ("actors", 7),
        "system=7": ("system", 7),
        "deferred=None": ("deferred", None),
        "output=7 (control)": ("output", 7),
    }
    results = {}
    for name, (key, value) in mutations.items():
        blob = json.loads(json.dumps(good, default=repr))
        blob[key] = value
        results[name] = classify(json.dumps(blob, default=repr))

    # Pre-parse payloads: not a str at all, and a str that is not JSON.
    results["payload=None"] = classify(None)
    results["payload='{not json'"] = classify("{not json")

    width = max(len(k) for k in results)
    for name, verdict in results.items():
        print(f"  {name:<{width}}  ->  {verdict}")

    untyped = [k for k, v in results.items() if v.startswith("UNTYPED")]
    print()
    print("OBSERVED: %d of %d hostile inputs escape as UNTYPED exceptions: %s"
          % (len(untyped), len(results), untyped))
    print("EXPECTED: 0 untyped -- every rejection is a SnapshotCorruptError "
          "(or another XStateMachineError subclass), per #110/#45.")
    print("RESULT:", "PASS" if not untyped else "FAIL")
    return 0 if not untyped else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

## Observed behaviour

```
  version='x'          ->  UNTYPED:ValueError: invalid literal for int() with base 10: 'x'
  version=None         ->  UNTYPED:TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'
  version={}           ->  UNTYPED:TypeError: int() argument must be a string, a bytes-like object or a real number, not 'dict'
  status=[]            ->  UNTYPED:TypeError: unhashable type: 'list'
  status={}            ->  UNTYPED:TypeError: unhashable type: 'dict'
  history=3.14         ->  UNTYPED:AttributeError: 'float' object has no attribute 'items'
  history='junk'       ->  UNTYPED:AttributeError: 'str' object has no attribute 'items'
  actors=7             ->  UNTYPED:AttributeError: 'int' object has no attribute 'items'
  system=7             ->  UNTYPED:AttributeError: 'int' object has no attribute 'items'
  deferred=None        ->  UNTYPED:TypeError: 'NoneType' object is not iterable
  output=7 (control)   ->  ACCEPTED
  payload=None         ->  UNTYPED:TypeError: the JSON object must be str, bytes or bytearray, not NoneType
  payload='{not json'  ->  TYPED:InvalidConfigError

OBSERVED: 11 of 13 hostile inputs escape as UNTYPED exceptions: ["version='x'", 'version=None', 'version={}', 'status=[]', 'status={}', 'history=3.14', "history='junk'", 'actors=7', 'system=7', 'deferred=None', 'payload=None']
EXPECTED: 0 untyped -- every rejection is a SnapshotCorruptError (or another XStateMachineError subclass), per #110/#45.
RESULT: FAIL
```

Exit code `1`. Note that the `status=[]` case is especially pointed: the
`TypeError` is raised *inside* the membership test that exists to reject a bad
status. Four independent round-5 fuzz corpora agree on the same frames
(339/5000, 432/5000, 906/5000 and 545/5000 untyped escapes respectively).

## Expected behaviour

The library's own documented contract, quoted from
`persistence.check_shape` (`src/xstate_statemachine/persistence.py:149-157`):

> Reject a structurally invalid payload with a typed error (#110).
> Runs after `check_version` / `check_identity` and before any field is
> read, so a corrupted blob cannot surface as a bare ``KeyError`` or be
> restored into an impossible state.

and from `from_snapshot` (`base_interpreter.py:1372-1376`):

> Snapshots come back from Redis, disk or a queue, so corruption is an
> ordinary runtime condition callers are expected to handle. Leaking
> `json.JSONDecodeError` — the documented way to catch this library's
> failures — silently missed it.

Every rejection on this path must therefore be an `XStateMachineError`
subclass. Two further sub-expectations follow from the text itself:

1. "*before any field is read*" is violated by `check_version`, which reads
   and coerces `snapshot["version"]` before `check_shape` runs at all.
2. `"{not json"` yields `InvalidConfigError`. That is typed, so it satisfies
   the base-class contract, but it is the *wrong* type for a corrupt snapshot:
   `SnapshotCorruptError` is the class `#110` introduced for exactly this.

## Root cause analysis

Three independent holes on one path,
`src/xstate_statemachine/base_interpreter.py:1293-1530` (`from_snapshot`):

1. **Ordering.** `persistence.check_version()` is called at
   `base_interpreter.py:1391`, *nine lines before* `check_shape()` at `:1400`.
   Its body (`persistence.py:138`) is a bare coercion:

   ```python
   version = int(snapshot.get("version", 0))
   ```

   Any `version` that is not `int`-coercible raises `ValueError`/`TypeError`
   straight out of the classmethod. There is no `isinstance` guard and no
   `try`.

2. **Incomplete shape coverage.** `check_shape()`
   (`persistence.py:149-196`) validates `status`, `context`, `state_ids`,
   `configuration`, `pending_events` and `deferred`-as-a-list. It never
   validates `history`, `actors` or `system`, each of which is then walked
   with an unchecked `.items()`:

   - `base_interpreter.py:1481` — `(snapshot.get("history") or {}).items()`
   - `base_interpreter.py:1493` — `(snapshot.get("actors") or {}).items()`
   - `base_interpreter.py:1518` — `(snapshot.get("system") or {}).items()`

   The `or {}` idiom defends only against `None`/falsy, not against a wrong
   *type*: `3.14`, `"junk"` and `7` are all truthy and go straight to
   `.items()`.

3. **`deferred=None` slips the list check.** `check_shape`'s
   `pending_events`/`deferred` clause is `if val is not None and ...`, so an
   explicit `null` passes. `base_interpreter.py:1465-1466` then does
   `for d in snapshot.get("deferred", [])` — `dict.get` returns the *stored*
   `None`, not the default, and the iteration raises `TypeError`.

4. **Pre-parse.** `json.loads(snapshot_str)` at `base_interpreter.py:1378` is
   wrapped only in `except json.JSONDecodeError`. A non-`str` payload raises
   `TypeError` from `json.loads` itself, before that handler can apply.

`status=[]` is the same class of bug as (1): `status not in _VALID_STATUSES`
at `persistence.py:170` tests membership in a `frozenset`, which hashes the
left operand — so an unhashable status raises inside the rejection check.

## Impact

**General users.** `from_snapshot()` is the library's trust boundary with
external storage. A caller who follows the documentation and writes
`except XStateMachineError` around a restore gets an uncaught
`AttributeError` from deep inside the interpreter for the majority of
malformed inputs — the process crashes rather than falling back to a clean
boot. Every one of these fields is attacker- or corruption-reachable when the
blob comes from Redis, a queue, or a file another process wrote. The typed
hierarchy `#110` and `#113` built is real work that this gap makes
unreliable to depend on.

**Concrete order-management scenario.** An order service snapshots each order
machine into Redis on every transition and restores on boot. A partial write,
a schema skew between two deployed versions (a rolled-back `version` field
written as a string), or a tampered key leaves `history` or `actors` a
non-mapping. On restart the recovery loop — written as
`try: restore(blob) except XStateMachineError: start_fresh_and_alert()` —
does not catch the `AttributeError`. The recovery worker dies on the first
bad order instead of quarantining it, and every *subsequent* order in the
restore queue is never restored either: one corrupt blob takes down recovery
for the whole book.

## Proposed fix

**Design.** Make the envelope validation total and put it first.

1. **Harden `check_version`.** Guard the type before coercing:

   ```python
   raw = snapshot.get("version", 0)
   if isinstance(raw, bool) or not isinstance(raw, int):
       raise SnapshotCorruptError(
           f"'version' is {type(raw).__name__}, expected an integer"
       )
   ```
   (Accepting a `str` of digits for compatibility is fine, but it must be an
   explicit branch, not a bare `int()`.)

2. **Hash-safe status check.** In `check_shape`, test
   `isinstance(status, str)` *before* the `in _VALID_STATUSES` membership
   test, so an unhashable value is reported rather than raising.

3. **Extend `check_shape` to every field `from_snapshot` reads.** Add:
   - `history`: `None` or `dict[str, list[str]]`
   - `actors`: `None` or `dict[str, dict]`
   - `system`: `None` or `dict[str, str]`
   - `deferred` / `pending_events`: change `if val is not None` to
     `if key in snapshot and val is not None` → simpler, make an explicit
     `null` a failure (`"'deferred' is null, expected a list"`), since the
     writer never emits `null` for it.

   The cheap, future-proof version of this is to validate *the whole
   envelope* against one declarative table of `(key, required, validator)`
   rather than an ad-hoc sequence of `if`s, so a new persisted field cannot
   be added without a shape rule. That table also gives `check_shape` a
   natural place to reject unknown top-level keys with a warning.

4. **Order.** Move `check_shape()` (or at minimum an envelope-types
   pre-pass) *above* `check_version` / `check_identity`, matching what
   `check_shape`'s own docstring promises about running before any field is
   read. The docstring should then be corrected either way so it describes
   the real order.

5. **Pre-parse.** Wrap the decode as
   `except (json.JSONDecodeError, TypeError) as e: raise SnapshotCorruptError(...)`,
   and change the JSON-decode failure from `InvalidConfigError` to
   `SnapshotCorruptError` — a bad snapshot is not a bad machine config. Keep
   `InvalidConfigError` in the class's `__bases__`/alias if back-compat with
   existing `except InvalidConfigError` handlers matters.

**Compatibility.** Behaviour only changes for inputs that currently *crash*
with an untyped exception; no currently-accepted snapshot is affected (the
`output=7` control stays accepted). The one visible change for existing code
is the JSON-decode error class, which is why step 5 suggests preserving the
old class as a base.

**Alternatives considered.** A blanket
`try: ... except Exception as e: raise SnapshotCorruptError(...) from e`
around the body of `from_snapshot` would close the contract hole in one line,
but it also swallows genuine internal bugs as "corrupt snapshot" and gives
the caller no way to tell a bad blob from a library defect. Rejected as a
primary fix; acceptable only as a belt-and-braces outer net *after* the
per-field checks exist.

## Acceptance criteria

- [ ] `repro/R5-03_from_snapshot_untyped_errors.py` exits `0`.
- [ ] `check_shape()` validates every top-level key `from_snapshot` reads:
      `version`, `status`, `context`, `state_ids`, `configuration`,
      `pending_events`, `deferred`, `history`, `actors`, `system`, `output`.
- [ ] `tests/test_persistence_shape.py::test_hostile_scalar_per_field_is_typed`
      — parametrised over every persisted key × `{None, 7, 3.14, "junk", [],
      {}, True}`: each either restores successfully or raises
      `SnapshotCorruptError`; `pytest.raises(XStateMachineError)` holds for
      every rejection and no case raises anything else.
- [ ] `tests/test_persistence_shape.py::test_unhashable_status_is_typed`
      — `status=[]` and `status={}` raise `SnapshotCorruptError`, not
      `TypeError`.
- [ ] `tests/test_persistence_shape.py::test_version_not_int_is_typed`
      — `version` in `{"x", None, {}, [] }` raises `SnapshotCorruptError`
      before any interpreter is constructed.
- [ ] `tests/test_persistence_shape.py::test_non_str_payload_is_typed`
      — `from_snapshot(None, m)` and `from_snapshot(b"{}", m)` raise
      `SnapshotCorruptError`.
- [ ] `tests/test_persistence_shape.py::test_fuzz_single_field_mutation_never_untyped`
      — a hypothesis test that takes a valid snapshot, mutates exactly one
      top-level key to an arbitrary JSON value, and asserts the call either
      succeeds or raises `XStateMachineError` (never a bare builtin).
- [ ] Both engines covered (`Interpreter` and `SyncInterpreter` share the
      classmethod, but the test is parametrised over both to lock it in).

## Related

- Round 4: **#110** (`check_shape`, the fix this extends), **#113** (typed
  `InvalidEventError` hierarchy — same "typed errors, but only for the named
  fields" theme), **#45** (envelope checks first).
- **R5-17** — the same restore path accepts a non-`str` `Event.type` through
  `pending_events`, where `send()` rejects it; `check_shape` asserts only that
  the `type` key is *present* (`persistence.py:190-196`). Same function, same
  root cause shape.
- **R5-02** — the read side has no *legality* check either; R5-03 is the
  type-safety half of the same missing validation layer.
- Register source ids: `D5-persistence-3`, `D5-concurrency-2`, `D5-fuzz-2`,
  `D5-determinism-2`, `D5-semantics-4`, `D5-soak-1`, `D5-security-2`, `J-10`
  (8 submissions merged 1:1 into this row).
- Evidence: `triage-r5/t1_snapshot.py::C/E`.
- Meta: our adoption audit **#26**.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: `3ed3099`
- Ran `repro/R5-03_from_snapshot_untyped_errors.py` in a fresh process: exit
  code `1`, output pasted verbatim above.
- Root cause confirmed by reading `persistence.py:132-196` and
  `base_interpreter.py:1370-1530` at the cited lines.

## Verification (independent re-run)

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: `3ed3099`
- Fresh-process re-run of `repro/R5-03_from_snapshot_untyped_errors.py`:
  exit code `1`, output byte-identical to the pasted transcript above (11 of
  13 hostile inputs UNTYPED).
- Root-cause line citations re-checked against source and confirmed exact:
  `persistence.py:132` (`check_version`), `:149` (`check_shape`), `:170`
  (`status not in _VALID_STATUSES`); `base_interpreter.py:1378` (pre-parse
  `json.loads`), `:1391` (`check_version` call), `:1400` (`check_shape`
  call), `:1465-1466` (`deferred` iteration), `:1481` (`history` `.items()`),
  `:1493` (`actors` `.items()`), `:1518` (`system` `.items()`).
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 150 --search "from_snapshot untyped"` returns only round-4 `#110`
  (the parent this deepens, already cited under Related) and unrelated `#46`,
  `#26`. No duplicate.
