---
id: R13-07
title: "Docs: RestoredError is outside the RunawayChainError hierarchy after a snapshot round-trip"
labels: [documentation, persistence, area/interpreter]
severity: Medium
repro_script: null
commit: "v0.9.0 (91bd979)"
---

## Summary

Not a defect — filed for tracking/docs so the trust boundary is written where a
reader will find it. `chain_trips` and `last_chain_error` (#226) persist across
a restore and are monotonic over restart hops, which is correct and already
documented. What is undocumented at the point a reader needs it is that
`last_chain_error`'s **type** is not preserved: a live `RunawayChainError`
(`exceptions.py:468`, subclasses `XStateMachineError` directly) becomes a
`RestoredError` (`exceptions.py:212`, also subclasses `XStateMachineError`
directly, **not** `RunawayChainError`) after a snapshot round-trip. JSON cannot
carry a Python type, so this is unavoidable given the wire format, and the
`error` field on a restored-in-`error`-status machine sets the exact same
precedent already. But a supervisor written against the live-machine contract —
`if isinstance(interpreter.last_chain_error, RunawayChainError): page()` — is
correct while the process runs and **silently false** the moment that same
machine is restored from a snapshot, which is precisely the moment (a restart)
a supervisor is most likely to be watching.

## Environment

- `xstate_statemachine` v0.9.0 (91bd979), installed from PyPI (wheel verified
  identical to tag).
- Python 3.x, stdlib + `xstate_statemachine` only.

## Minimal reproduction

Run from a neutral cwd (e.g. `<home>`). Trips the runaway-chain guard
live, persists, restores, and shows the `isinstance` check silently flipping.

```python
"""last_chain_error changes type across a snapshot round-trip."""
import asyncio
import json

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    create_machine,
)
from xstate_statemachine.exceptions import RunawayChainError, RestoredError

CFG = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "maxIterations": 5,
    "states": {
        "a": {
            "on": {
                # Self-re-arming chain: each entry into "a" immediately
                # sends itself again, tripping maxIterations quickly.
                "T": {"target": "a", "actions": ["bump"]},
            },
        },
    },
}


async def main() -> None:
    def bump(interpreter, ctx, event, action):
        ctx["n"] += 1
        interpreter.send_priority("T", wait=False)

    machine = create_machine(
        CFG, logic=MachineLogic(actions={"bump": bump})
    )
    i = Interpreter(machine)
    await i.start()
    await i.send("T")
    await asyncio.sleep(0.1)

    print("chain_trips (live):", i.chain_trips)
    print("last_chain_error (live) type:", type(i.last_chain_error).__name__)
    print(
        "isinstance(..., RunawayChainError) (live):",
        isinstance(i.last_chain_error, RunawayChainError),
    )

    blob = i.get_snapshot()
    await i.stop()

    restored = Interpreter.from_snapshot(json.loads(json.dumps(blob)), machine)
    print("chain_trips (restored):", restored.chain_trips)
    print(
        "last_chain_error (restored) type:", type(restored.last_chain_error).__name__
    )
    print(
        "isinstance(..., RunawayChainError) (restored):",
        isinstance(restored.last_chain_error, RunawayChainError),
    )
    print(
        "isinstance(..., RestoredError) (restored):",
        isinstance(restored.last_chain_error, RestoredError),
    )


asyncio.run(asyncio.wait_for(main(), 25))
```

Expected/observed shape on `v0.9.0`:

```
chain_trips (live): 1
last_chain_error (live) type: RunawayChainError
isinstance(..., RunawayChainError) (live): True
chain_trips (restored): 1
last_chain_error (restored) type: RestoredError
isinstance(..., RunawayChainError) (restored): False
isinstance(..., RestoredError) (restored): True
```

## Current state

`snapshots.md:133` and `:252` document that `last_chain_error` crosses a
restart before documenting that its type changes on the way. A reader who
stops at the first sentence writes an `isinstance` check that is correct for
the live case and wrong for the restored one, with no exception or warning at
the point it goes wrong — `chain_trips > 0` stays true, but the type-based
gate silently never fires.

## Expected behaviour / Requested change

Reorder or amend the `snapshots.md` documentation for `last_chain_error` so
the type-change caveat appears **before or alongside** the "crosses a restart"
claim, not after it, and add the recommended pattern directly:

> `last_chain_error` survives a restore, but as a `RestoredError`, not the
> original exception type (JSON cannot carry a Python class). Never
> `isinstance`-check `last_chain_error` for alerting; check `chain_trips > 0`
> instead, which is stable across restarts.

Optionally (small-fix path, if maintainers want stronger safety instead of
just documentation): make `RestoredError` for the runaway-chain case
specifically subclass `RunawayChainError` — i.e. detect that the persisted
`error` field's message/marker corresponds to a chain-break event and
construct a `RestoredError` that also `isinstance`-satisfies
`RunawayChainError` — so the live and restored contracts match without
requiring callers to change their check. This is optional because it adds
detection logic the docs-only fix avoids, and `chain_trips` is meant to be
the stable signal regardless.

## Root cause analysis

N/A for the docs ask (design choice, not a defect). `exceptions.py:212`
(`RestoredError(XStateMachineError)`), `exceptions.py:468`
(`RunawayChainError(XStateMachineError)`) — siblings, not parent/child.
For the optional fix: wherever `from_snapshot` constructs `RestoredError` from
the persisted `error` string (persistence/restore path) would need to inspect
whether the persisted record marks the chain-break case and pick a subclass
accordingly.

## Impact

Medium-as-adoption-note. No live-path defect; a supervisor that follows the
documented restart-aware pattern (`chain_trips > 0`) is unaffected. Risk is
purely to a supervisor author who reads only the first half of the existing
doc sentence and writes an `isinstance` check that works in every test
(process never restarts during a test run) and silently stops firing in
production the first time it matters.

## Proposed fix

Reorder the `snapshots.md:133`/`:252` documentation as described in "Requested
change"; optional subclassing fix is a nice-to-have, not required to close
this.

## Acceptance criteria

- [ ] `snapshots.md` states the type-change caveat for `last_chain_error`
      before or in the same breath as the "crosses a restart" claim, with the
      `chain_trips > 0` recommendation spelled out verbatim.
- [ ] (Optional) `RestoredError` instances produced for a persisted
      chain-break also satisfy `isinstance(x, RunawayChainError)`.

## Related

`R13-07` / `S-3` in `73-r13-findings-register.md` §2 (DESIGN-CONSTRAINT,
"defensible design, not a defect... Flagged because the doc bullet tells
readers the latch crosses a restart before it tells them the type changes");
#226 (`chain_trips`/`last_chain_error` persistence).
