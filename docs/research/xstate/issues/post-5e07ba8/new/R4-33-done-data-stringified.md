---
r4: R4-33
title: "Bug: DoneEvent.data is silently stringified into the snapshot by json.dumps(default=str)"
labels: [bug, severity/low, area/persistence, area/events]
severity: Low
repro_script: repro/R4-33_done_data_stringified.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`get_snapshot()` serializes pending events, including a `DoneEvent`'s
`data` payload, via `json.dumps(..., default=str)`. Any non-JSON-native
value in `data` (e.g. `Decimal`, `datetime`) is therefore silently coerced
to its `str()` form when the snapshot is written, with no warning. A
restored machine's `onDone` handler then receives a `str` where the original
completion produced a `Decimal` -- arithmetic that worked before a restore
(`data["amount"] * qty`) raises `TypeError` after one. This is Low severity
because it requires a restore of a *pending* completion event carrying
non-JSON data, but it is listed because `Decimal` is exactly the type used
for money.

## Environment

- Commit: `5e07ba8` (`main`, unreleased 0.8.1; `__version__` reports `0.8.0`)
- Python: 3.13.7 (CPython, 64-bit)
- OS: Windows 11 Pro (10.0.26200)
- Install: editable (`pip install -e .`) into a project venv
- Found by our adoption audit (#26), round 4.

## Minimal reproduction

```python
"""R4-33: `get_snapshot()` uses `json.dumps(default=str)`: a `DoneEvent`
payload with a non-JSON value (e.g. `Decimal`) is SILENTLY stringified. On
restore the `onDone` handler receives a `str` where it expects a `Decimal` --
no error, no warning."""
from __future__ import annotations

import asyncio
import decimal
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import DoneEvent

seen = {}


def cap(i, c, e, a):  # noqa: ANN001
    seen["data"] = e.data


CFG = {
    "id": "m",
    "initial": "a",
    "states": {"a": {"on": {"done.invoke.svc": {"target": "b", "actions": ["cap"]}}}, "b": {}},
}


async def main() -> int:
    i = Interpreter(create_machine(CFG, logic=MachineLogic(actions={"cap": cap})))
    await i.start()
    i._event_queue.put_nowait(
        DoneEvent(type="done.invoke.svc", data={"amount": decimal.Decimal("10.50")}, src="svc")
    )
    s = i.get_snapshot()
    await i.stop()
    print("OBSERVED persisted pending_events:", json.loads(s)["pending_events"])

    i2 = Interpreter.from_snapshot(s, create_machine(CFG, logic=MachineLogic(actions={"cap": cap})))
    await i2.start()
    await asyncio.sleep(0.3)
    d = seen.get("data")
    types = {k: type(v).__name__ for k, v in d.items()}
    print("OBSERVED onDone received:", d, "types:", types)
    await i2.stop()

    print("EXPECTED: restore either preserves the Decimal or raises at persist time; "
          "it must not silently hand the handler a str.")
    ok = isinstance(d["amount"], decimal.Decimal)
    print("RESULT:", "PASS" if ok else "FAIL (Decimal silently coerced to str across snapshot)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED persisted pending_events: [{'kind': 'done', 'type': 'done.invoke.svc', 'data': {'amount': '10.50'}, 'src': 'svc'}]
OBSERVED onDone received: {'amount': '10.50'} types: {'amount': 'str'}
EXPECTED: restore either preserves the Decimal or raises at persist time; it must not silently hand the handler a str.
RESULT: FAIL (Decimal silently coerced to str across snapshot)
```

The persisted snapshot's `pending_events` already shows `'10.50'` (a string)
where the live event carried `Decimal("10.50")`; after restore the `onDone`
handler receives that string with no error or warning anywhere in the path.

## Expected behaviour

A persistence layer that claims to round-trip pending events must either (a)
preserve the value's type across the round trip, or (b) fail loudly at
persist time so the caller learns their data is not representable, per the
general principle (and this library's own stated contract for
`get_persisted_snapshot()`/`from_snapshot()`) that a restored interpreter
should be behaviorally equivalent to the one that was snapshotted. Silently
changing a value's type is neither: it is a data-corruption path that looks
identical to success.

## Root cause analysis

`src/xstate_statemachine/events.py:296-298` deep-copies `DoneEvent.data`
verbatim (preserving `Decimal` in memory), but
`src/xstate_statemachine/base_interpreter.py:946` (the snapshot-writing
path) serializes the whole pending-events list with
`json.dumps(..., default=str)`. `default=str` is what `json` calls for any
object it cannot natively encode -- it silently converts `Decimal("10.50")`
to `"10.50"` rather than raising `TypeError` (the `json` module's normal
behavior without a `default=` callback). This is not a regression introduced
by a specific change in this diff; prior to it the record was dropped
entirely (issue `#87`), so this is a partial fix that traded "data is lost"
for "data is mistyped," which is an improvement but still corrupts non-JSON
payloads silently.

## Proposed fix

**Design.** Replace the blanket `default=str` with a `default=` callback
that raises `TypeError` naming the offending key/value when it encounters a
type it cannot round-trip losslessly (or, for previously-approved types like
`Decimal`/`datetime`, encode them with an explicit tagged representation
`{"__type__": "Decimal", "value": "10.50"}` and decode it back on restore,
rather than silently downgrading to `str`).

1. In `base_interpreter.py` near the snapshot-writing call (~line 946),
   replace `default=str` with a project-defined encoder that either (a)
   supports a documented allow-list of extra types (`Decimal`, `datetime`,
   `UUID`) via tagged round-trip encoding, and (b) raises for anything else,
   naming the key path and the type it could not serialize.
2. Add the matching decoder to the restore path so tagged values round-trip
   back to their original type.
3. Document the supported non-JSON types for event `data`/`context` payloads
   in the persistence guide.

**Compatibility.** A behavior change for anyone currently relying on silent
stringification (unlikely, since it is undocumented and produces wrong
types); existing snapshots with already-stringified values continue to
restore as strings (no way to recover the original type retroactively).

**Alternatives considered.**
1. *Leave as-is and document the stringification.* Rejected: it is a
   correctness bug for the library's own headline data type (money via
   `Decimal`), and a documented footgun is still a footgun.

## Acceptance criteria

- [ ] `Decimal`/`datetime`/`UUID` values in event `data` round-trip through
      `get_snapshot()`/`from_snapshot()` with their original type intact, or
      persisting them raises `TypeError` naming the offending key.
- [ ] `repro/R4-33_done_data_stringified.py` exits `0`.
- [ ] `tests/test_persistence_types.py::test_decimal_in_done_data_roundtrips`
- [ ] `tests/test_persistence_types.py::test_unsupported_type_raises_at_persist_time`

## Related

- Register row `R4-33` (filed Low, stands as filed).
- Evidence: `probes/main-5e07ba8/r40_done_data_coercion.py`, `r38`, `r39`.
- Prior issue: **#87** (data previously dropped entirely; this is the
  follow-on mistyping defect after that fix).
- Meta: our adoption audit **#26**.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: `5e07ba8`
- Ran `repro/R4-33_done_data_stringified.py` in a fresh process: exit code
  `1`, output matches the Observed section verbatim (`Decimal("10.50")`
  persisted as `'10.50'`, restored `onDone` handler receives `str`, not
  `Decimal`).
- Root cause confirmed: `events.py` deep-copies `DoneEvent.data` verbatim
  (preserving `Decimal` in memory); `base_interpreter.py` line 946 serializes
  the snapshot with `json.dumps(snapshot, indent=2, default=str)`, which
  silently stringifies any non-JSON-native value instead of raising.
- No XState-doc claim to verify (this is a Python-`json`/persistence-format
  defect specific to this library's serialization, not an XState v5 spec
  question); the issue's stated contract (round-trip or fail loudly) is the
  library's own persistence guarantee.
- No duplicate found on `gh issue list --search "done data stringified"`
  (no results); prior issue **#87** (data previously dropped entirely) is
  explicitly cited as the predecessor defect this one follows on from, not a
  duplicate.
- Self-contained; no project-name/label leak.
