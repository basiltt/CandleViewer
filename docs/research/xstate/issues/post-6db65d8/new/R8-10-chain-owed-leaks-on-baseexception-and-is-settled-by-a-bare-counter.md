---
r8: R8-10
title: "Bug: `_chain_owed` leaks permanently when a service exits via `BaseException`, and it is settled by a bare counter rather than matched to the debt that opened it"
labels: [bug, severity/medium, area/interpreter]
severity: Medium
engines: async `Interpreter`
service_kinds: `async def`
repro_script: repro/R8-10_chain_owed_leak.py
commit: 6db65d8
python: 3.13.7
verified: true
---

## Summary

`_chain_owed` — the debt counter #179 introduced to keep a step's chain open until its
coroutine service completes — **leaks permanently** when a service exits via
`BaseException` (`CancelledError`, `KeyboardInterrupt`, `SystemExit`), and it is settled by
a **bare counter decrement** rather than matched to the debt that opened it.

## Reproduction (`6db65d8`)

`repro/R8-10_chain_owed_leak.py`: a service cancelled mid-flight leaves `_chain_owed`
permanently above zero. Because the chain-end test includes "owes nothing", the affected
machine's step never reaches chain end again through that path.

The bare-counter half is visible by inspection as much as by test: the decrement in
`_deliver_priority` (`if self._chain_owed: self._chain_owed -= 1`) settles *a* debt, not
*the* debt, so a completion belonging to one invocation can settle the debt opened by
another.

## Suggested fix

Two independent changes:

1. Release the debt in a `finally` that catches `BaseException`, not just `Exception`.
   `CancelledError` derives from `BaseException` in 3.8+, and cancellation is the normal
   way a service ends on `stop()`.
2. Key the debt to the invocation that opened it — a set or a per-invocation token rather
   than a counter — so a completion settles its own debt and a duplicate or foreign
   completion cannot settle someone else's.

## Impact

Regression introduced by #179's new machinery. The counter is on the chain-end path, so a
leak affects whether steps ever complete on the affected machine. We rate it Medium rather
than High because it needs an abnormal service exit to trigger, and because on our side
`stop()` is the main producer of those.

## Verification

2026-09-21, python 3.13.7, commit 6db65d8. Run with `PYTHONPATH` including
`battle-6db65d8/concurrency` so `common2` resolves (repro file unchanged).

`repro/R8-10_chain_owed_leak.py` — exit 1, `"result": "FAIL"`:

```
async def: chain_owed_while_armed=[1] chain_owed_after_state_exit=[0]
           cycle_after_exit_wedged=false cycle_laps=50 cycle_tripped_observably=true
def:       chain_owed_while_armed=[0] chain_owed_after_state_exit=[0]
           cycle_after_exit_wedged=true cycle_laps=0 cycle_tripped_observably=false
failures: ["def", "cycle wedged after exit"], ["def", "cycle trip not observable"]
```

The `async def` lane's debt is released on exit as designed (`chain_owed_after_state_exit`
returns to 0, and the chain-end probe still trips at 50 laps afterward). The `def`-lane
service is the one that leaks: after the owning state is exited the follow-up cycle never
trips (`cycle_after_exit_wedged: true`, `cycle_laps: 0`), consistent with a debt opened for
the `def` lane's exiting service never being released.

Source confirmed at commit 6db65d8: the only cancellation-release path is
`interpreter.py:2678-2679` — `if t.cancelled() and self._chain_owed: self._chain_owed -= 1`,
inside a task's `add_done_callback`, which fires on `asyncio.CancelledError` but not on other
`BaseException` subclasses (`SystemExit`, `KeyboardInterrupt`) surfacing through the task.
The settle path itself (`interpreter.py:2384-2385`, inside `_deliver_priority`) is a bare
`if self._chain_owed: self._chain_owed -= 1` with no per-invocation key, confirming the
counter (not debt-matched) characterisation.
