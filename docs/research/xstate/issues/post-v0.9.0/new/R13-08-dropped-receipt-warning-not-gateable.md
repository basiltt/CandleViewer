---
id: R13-08
title: "Enhancement: expose a deterministic signal for the #232 dropped-receipt RuntimeWarning (currently emitted from __del__, invisible to -W error)"
labels: [enhancement, actors, receipts]
severity: Low
repro_script: battle-v0.9.0/persistence/n5_runtimewarning_werror.py
commit: "v0.9.0 (91bd979)"
---

## Summary

Not a defect — filed for tracking/docs so the trust boundary is written
where a reader will find it. #232 added a `RuntimeWarning` when a `def`
action's dropped `send(wait=True)` result (a future nobody awaits) is
garbage-collected, and it works well as a best-effort diagnostic. But
because CPython raises the warning from inside `__del__`, it's routed to
`sys.unraisablehook` rather than the normal warnings machinery, so a project
running `-W error` / `filterwarnings = error` in CI cannot turn a dropped
receipt into a build failure the way it can for an ordinary warning.

## Environment

`xstate_statemachine` v0.9.0 (tag `v0.9.0` = `91bd979`).

## Current state

## Minimal reproduction

Standalone, stdlib + `xstate_statemachine` only, run under `-W error` from a
neutral cwd:

```python
"""#232 under -W error: where does the RuntimeWarning land -- in the
action (breaking the step), in the run loop (killing the interpreter),
or in a GC finaliser (unraisable, harmless)?"""
import asyncio, gc, json, sys
from xstate_statemachine import Interpreter, MachineLogic, create_machine

UNRAISABLE = []
sys.unraisablehook = lambda a: UNRAISABLE.append(
    f"{type(a.exc_value).__name__}: {a.exc_value}")

CFG = {"id": "rw", "initial": "a", "context": {"log": [], "action_exc": None},
       "states": {"a": {"entry": ["probe"],
                        "on": {"B": {"actions": ["note"]}}}}}

def build():
    def note(i, c, e, a):
        c["log"].append(e.type)

    def probe(i, c, e, a):
        try:
            i.send("B", wait=True)          # receipt dropped
        except BaseException as ex:         # noqa: BLE001
            c["action_exc"] = f"{type(ex).__name__}: {ex}"
    return create_machine(CFG, logic=MachineLogic(actions={"probe": probe,
                                                           "note": note}))

async def main():
    loop_errors = []
    asyncio.get_running_loop().set_exception_handler(
        lambda l, ctx: loop_errors.append(str(ctx.get("exception") or
                                              ctx.get("message"))))
    i = Interpreter(build())
    start_exc = None
    try:
        await i.start()
        await asyncio.sleep(0.2)
    except BaseException as ex:                # noqa: BLE001
        start_exc = f"{type(ex).__name__}: {ex}"
    log = list(i.context["log"])
    action_exc = i.context["action_exc"]
    status = i.status
    try:
        await i.stop()
    except BaseException as ex:                # noqa: BLE001
        loop_errors.append(f"stop: {type(ex).__name__}: {ex}")
    del i
    for _ in range(3):
        gc.collect()
        await asyncio.sleep(0.02)
    print(json.dumps({"W": sys.warnoptions,
                      "start_exc": start_exc,
                      "action_saw": action_exc,
                      "log": log, "status_after": status,
                      "loop_exception_handler": loop_errors,
                      "unraisable": UNRAISABLE,
                      "machine_still_worked": log == ["B"]}, indent=1))

asyncio.run(main())
```

## Observed behaviour

Run with `python -W error n5_runtimewarning_werror.py`: the machine
completes normally (`log == ["B"]`, `status_after == "running"`,
`start_exc: null`, `loop_exception_handler: []`), and the `RuntimeWarning`
shows up only in `unraisable` (CPython prints `Exception ignored in:` to
stderr) — never as a raised exception in the action, the run loop, or
`stop()`. `-W error` has no effect on it because `__del__` exceptions never
reach the normal warnings filter path; they go to
`sys.unraisablehook`/`sys.excepthook` at GC time instead. The same applies
to `pytest.warns`, which can't observe it unless the dropped object is
forced to finalise (`del` + `gc.collect()`) inside the `with` block.

This is deterministic on CPython — it fires reliably at refcount drop, one
warning per dropped receipt, no duplicates, and no false positive on the
legitimate store-and-await-later shape — so the signal is trustworthy, it's
just structurally unreachable by a build gate.

## Expected behaviour

## Requested change

Either of these would let a caller turn a dropped receipt into a
deterministic, gateable signal instead of a best-effort console diagnostic:

1. Raise/warn at a deterministic point in the code path that drops the
   receipt (e.g. when `send(wait=True)`'s future is superseded or the
   interpreter tears down with outstanding un-awaited receipts), rather
   than relying on `__del__`/GC timing; or
2. Expose a queryable counter (e.g. `interpreter.dropped_receipts`) that
   increments whenever a `send(wait=True)` result is discarded without
   being awaited, so a caller can assert on it directly in a test or health
   check without depending on GC timing at all.

Either would coexist with the current `__del__` warning rather than
replacing it outright, since the warning is still useful as an
interactive/console diagnostic.

## Root cause analysis

N/A (enhancement request, not a defect). For context: the `RuntimeWarning`
is raised inside the future/receipt wrapper's `__del__`, which is the only
hook CPython offers for "this object was never awaited" — and per the
language's own rules, an exception raised inside `__del__` is always routed
to `sys.unraisablehook`, never re-raised into the caller or the run loop.
That is why no amount of `-W error` / `filterwarnings` configuration in the
*caller's* project can change the outcome; the fix has to live on the
library's side of the boundary, as either of the two options above.

## Impact

A project that wants "no receipt is ever silently dropped" as a CI-enforced
invariant currently cannot express that as a warnings-filter gate against
this library; the check has to live in a runtime/soak test instead
(`del` + `gc.collect()` under `pytest.warns`), or as a static lint over the
call sites that use `send(wait=True)` and discard the result. Neither is a
production defect: the machine's own transition logic is unaffected either
way (confirmed: `status == running`, `raised_to_caller: []`,
`loop_exception_handler: []` across the 5/5 matrix in the #232 fix).

## Proposed fix

See "Requested change" above — a deterministic raise point and/or a
`dropped_receipts` counter.

## Acceptance criteria

- [ ] A dropped `send(wait=True)` receipt is observable through a route
      other than a `__del__`-emitted `RuntimeWarning` — either a
      deterministic exception/warning raised at the point of drop, or a
      queryable counter on the interpreter.
- [ ] The new signal does not change the machine's transition behaviour
      (still `status == running`, no exception raised to the caller or the
      run loop, on the existing 5/5 matrix: `wait=False`, awaited
      `ensure_future`, `.result()`, in-step await, and the dropped-receipt
      case itself).
- [ ] `docs/_guide/plugins.md` / `docs/_guide/snapshots.md` (or wherever
      #232 is documented) states plainly that the `__del__` warning is
      best-effort and not gateable via `-W error`, and points at the new
      counter/deterministic signal as the supported way to assert on it in
      CI.

## Related

`R13-04` / `R13-06` — the sibling documentation issue about the
`chain_trips` / `last_chain_error` trust boundary; both are filed in the
same spirit of writing an existing, correct design decision down where a
reader will find it.
