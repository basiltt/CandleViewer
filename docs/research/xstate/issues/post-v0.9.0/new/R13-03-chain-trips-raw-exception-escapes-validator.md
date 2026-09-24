---
id: R13-03
title: "Bug: malformed chain_trips / last_chain_error escape from_snapshot as raw ValueError/TypeError, not SnapshotCorruptError"
labels: [bug, persistence, validation]
severity: Medium
repro_script: battle-v0.9.0/persistence/repro/d13_p1_chain_trips_raw.py
commit: "v0.9.0 (91bd979)"
---

## Summary

We've pinned and adopted 0.9.0, and on the whole the restore-path contract
holds up well — this is one of the few remaining gaps between "adopt with
constraints" and "nothing open". Every envelope field that predates #226
(`version`, `status`, `state_ids`, `context`, `pending_events`,
`scheduled_sends`, `deferred`) is shape-checked by the snapshot validator and
a malformed value is reported as the documented `SnapshotCorruptError`. The
two fields #226 added — `chain_trips` and `last_chain_error` — are not: they
are read and coerced *after* the validator has already run, so a malformed
value on either field escapes as a bare `ValueError`/`TypeError` instead.

## Environment

`xstate_statemachine` v0.9.0 (tag `v0.9.0` = `91bd979`).

## Minimal reproduction

Standalone, stdlib + `xstate_statemachine` only, run from a neutral cwd:

```python
"""Malformed v3 chain_trips escapes from_snapshot as a RAW exception
instead of the documented SnapshotCorruptError."""
import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import SnapshotCorruptError

CFG = {"id": "d13", "initial": "a", "states": {"a": {"on": {"P": "a"}}}}


def build():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


async def main() -> int:
    i = Interpreter(build())
    await i.start()
    raw = i.get_persisted_snapshot()
    base = json.loads(raw) if isinstance(raw, str) else raw
    await i.stop()

    bad = 0
    for value in ("NaN", [1, 2], {"a": 1}, "1e3"):
        blob = dict(base)
        blob["chain_trips"] = value
        try:
            Interpreter.from_snapshot(
                json.dumps(blob), build(), verify_machine_hash=False
            )
            print(f"  chain_trips={value!r:12} -> ACCEPTED")
        except SnapshotCorruptError:
            print(f"  chain_trips={value!r:12} -> SnapshotCorruptError (ok)")
        except Exception as exc:  # noqa: BLE001
            bad += 1
            print(f"  chain_trips={value!r:12} -> RAW "
                  f"{type(exc).__name__}: {exc}")

    # control: the same corruption in an OLDER field IS reported properly
    ctl = dict(base)
    ctl["deferred"] = 5
    try:
        Interpreter.from_snapshot(
            json.dumps(ctl), build(), verify_machine_hash=False
        )
        print("  control deferred=5 -> ACCEPTED (unexpected)")
    except SnapshotCorruptError:
        print("  control deferred=5 -> SnapshotCorruptError (the contract)")

    print("\nVERDICT:", "REPRODUCED" if bad else "not reproduced",
          f"({bad} raw leaks)")
    return 1 if bad else 0


raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
chain_trips='NaN'    -> RAW ValueError: invalid literal for int() with base 10: 'NaN'
chain_trips=[1, 2]   -> RAW TypeError: int() argument must be a string, ... not 'list'
chain_trips={'a': 1} -> RAW TypeError: int() argument must be a string, ... not 'dict'
chain_trips='1e3'    -> RAW ValueError: invalid literal for int() with base 10: '1e3'
control deferred=5   -> SnapshotCorruptError (the contract)
```

`base_interpreter.py:1993` does a bare
`interpreter.chain_trips = int(snapshot.get("chain_trips") or 0)`, and
`:1994-1996` `str()`s `last_chain_error` — both after the snapshot validator
in `persistence.py:138-191` has already returned successfully. A
`last_chain_error` that isn't already a message (e.g. `{"not": "a message"}`)
isn't rejected either — it's silently latched as its `str()`.

## Expected behaviour

Every value in the persisted envelope should go through the same shape
check, so a malformed `chain_trips` / `last_chain_error` is reported as
`SnapshotCorruptError`, exactly like a malformed `deferred` or `context` is
today.

## Root cause analysis

`base_interpreter.py:1993-1996` (per `git grep` on the tag) reads and
coerces `chain_trips` / `last_chain_error` unconditionally after
`persistence.py:138-191`'s validator has already passed the blob. Because
the two fields were added by #226 after the validator was written, they were
never wired into its shape checks.

## Impact

The documented restore idiom is `except SnapshotCorruptError:
<quarantine the blob>`. A crash-truncated or partially-written journal
record whose damage happens to land on `chain_trips` is not caught by that
handler — it escapes as an unexpected `ValueError`/`TypeError` and can take
down a restore loop instead of quarantining one bad blob. Two softer
sub-cases ride along: a numeric string like `chain_trips='12'` is silently
coerced rather than validated, and a non-string `last_chain_error` is
latched as its `str()` rather than rejected.

## Proposed fix

Shape-check `chain_trips` (non-negative int) and `last_chain_error`
(`None` or `str`) inside the validator alongside the other envelope fields,
so a malformed value raises `SnapshotCorruptError` before either field is
read by the restore path.

## Acceptance criteria

- [ ] `from_snapshot` raises `SnapshotCorruptError` (not a raw
      `ValueError`/`TypeError`) for a non-integer-coercible `chain_trips`
      (e.g. `"NaN"`, `[1, 2]`, `{"a": 1}`, `"1e3"`).
- [ ] `from_snapshot` raises `SnapshotCorruptError` for a `last_chain_error`
      that is neither `None` nor a `str`.
- [ ] A well-formed `chain_trips` (non-negative int or numeric string) and
      `last_chain_error` (`None`/`str`) continue to restore unchanged
      (non-regression).
- [ ] The above repro script exits reporting `0 raw leaks`.

## Related

`R13-06` (design-constraint, not a defect): a well-formed but forged
`chain_trips` / `last_chain_error` inside the documented trust boundary
(#205) restores verbatim and gates no transition — that is accepted
behaviour and out of scope here. This issue is specifically about
malformed values breaking the validator's error-type contract.
