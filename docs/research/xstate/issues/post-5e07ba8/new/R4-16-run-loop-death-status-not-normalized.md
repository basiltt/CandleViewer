---
r4: R4-16
title: "Bug: run loop death from a manufactured CancelledError leaves status='running' and hangs pending receipts forever"
labels: [bug, severity/medium, area/interpreter, area/plugins]
severity: Medium
repro_script: repro/R4-16_run_loop_death_status_not_normalized.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`_run_event_loop` re-raises `asyncio.CancelledError` unconditionally
(`interpreter.py` ~1246-1247 and the outer handler at ~1285-1299) on the
theory that cancellation always originates from an external supervisor and
`stop()` should own the `status` transition. That reasoning breaks when a
plugin hook — ordinary, synchronous user code running inside the loop —
raises `asyncio.CancelledError` itself (a real shape: `concurrent.futures.
CancelledError` has been `asyncio.CancelledError` since Python 3.8, and any
hook wrapping cancellable work can surface one). The loop task dies, nobody
cancelled anything, but the code path is indistinguishable from a real
external cancellation, so `status` is never normalized away from
`"running"`. A second, independent path to the same symptom: the plugin
hook call at `interpreter.py:1206-1208` sits outside the per-event
`try/except Exception` that resolves receipts, and the outer `except
BaseException` (`interpreter.py:1300-1319`) sets `status="stopped"` but
never calls `_fail_all_receipts()` (only called from `_teardown()`, i.e.
only on an orderly `stop()`). Either way, an interpreter that can no longer
process events reports itself healthy (or simply forgets to fail
receipts), and any `send(..., wait=True)` awaiter hangs forever with no
error and no timeout raised by the library.

## Environment

- Commit: `5e07ba8` (post-0.8.0, pre-0.8.1 tag; `__version__` reports `0.8.0`)
- Python: 3.13.7
- Install: editable (`pip install -e .`) against
  `C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine`

## Minimal reproduction

```python
"""R4-16: when a plugin hook manufactures asyncio.CancelledError (not from an
external cancellation), the run loop's `except asyncio.CancelledError: raise`
(interpreter.py ~1246-1247, re-entering the outer handler at ~1285-1299)
propagates without normalizing `status`. The loop task dies, `status` stays
"running", and any `wait=True` receipt already pending or submitted after is
never resolved (`_fail_all_receipts()` is only called from `_teardown()`,
reached only via an orderly `stop()`).

EXPECTED: a dead run loop must not leave `status == "running"`, and it must
fail every outstanding/subsequent receipt rather than hang it forever.
OBSERVED: status stays "running", the run-loop task is done with
CancelledError, and send(..., wait=True) hangs indefinitely (no receipt, no
error, no timeout raised by the library itself).

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

CFG = {
    "id": "px",
    "initial": "a",
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {"on": {"BACK": "a"}},
    },
}


class CancellingPlugin(PluginBase):
    """Models an observer whose async transport surfaced a cancellation."""

    def on_transition(self, interpreter, from_states, to_states, transition):  # noqa: ANN001
        raise asyncio.CancelledError("metrics push was cancelled")


async def main() -> int:
    interp = Interpreter(create_machine(CFG, logic=MachineLogic()))
    interp.use(CancellingPlugin())
    await interp.start()

    await interp.send("GO")  # fire-and-forget; the hook raises during this
    await asyncio.sleep(0.1)

    status_after_kill = interp.status
    task = interp._event_loop_task
    loop_done = task.done() if task else None

    try:
        await asyncio.wait_for(interp.send("BACK", wait=True), 3)
        hung = False
    except asyncio.TimeoutError:
        hung = True

    print(f"status after loop death : {status_after_kill}")
    print(f"run loop task done      : {loop_done}")
    print(f"send(..., wait=True) hung: {hung}")

    defect_present = hung and status_after_kill == "running"
    print(
        "\nOBSERVED:",
        "run loop dead, status still 'running', receipt hangs forever"
        if defect_present
        else "loop death was reported/receipts failed correctly",
    )
    print(
        "EXPECTED: status normalized away from 'running' when the loop "
        "dies, and pending/subsequent receipts fail rather than hang"
    )
    print("RESULT:", "FAIL - defect present" if defect_present else "PASS")

    await interp.stop()
    return 1 if defect_present else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
status after loop death : running
run loop task done      : True
send(..., wait=True) hung: True

OBSERVED: run loop dead, status still 'running', receipt hangs forever
EXPECTED: status normalized away from 'running' when the loop dies, and pending/subsequent receipts fail rather than hang
RESULT: FAIL - defect present
```

(exit code 1)

## Expected behaviour

The library's own architecture comments state the intended invariant
directly. `base_interpreter.py`'s failure-mode note (quoted by the battle
report as "permanently dead and reporting itself healthy") is precisely the
condition `is_running` (`interpreter.py:296-299`) was added to detect for —
but `status`, the attribute `stop()`, `_refuse_if_not_running()`, and every
documented example switch on, is not covered by that same protection here.
XState v5's actor lifecycle model treats a stopped/errored actor as
observably distinct from a running one via its snapshot `status`
(https://stately.ai/docs/actors#actor-status); an actor whose processing
loop has permanently exited must not continue to report `status: "running"`
to callers, and any outstanding requests against it must settle (reject),
not hang indefinitely.

## Root cause analysis

Two independent gaps that share one symptom:

1. `interpreter.py:1246-1247`:
   ```python
   except asyncio.CancelledError:
       raise
   ```
   inside the per-event try, and the outer handler at `interpreter.py:1285-1299`
   which explicitly does **not** touch `status` for `CancelledError`,
   reasoning (correctly, for a *real* external cancellation) that `stop()`
   owns the transition. The loop has no way to distinguish "an enclosing
   TaskGroup/supervisor cancelled my task" from "a plugin hook running
   inside the loop raised `CancelledError` itself" — both look identical at
   this catch site. Only the first case should skip normalizing `status`.

2. `interpreter.py:1206-1208`:
   ```python
   for plugin in self._plugins:
       plugin.on_event_received(self, event)
   ```
   runs *outside* the per-event `try/except Exception` block that resolves
   receipts (`interpreter.py:1239-1280`). A plugin raising here escapes
   straight to the outer `except BaseException` at `interpreter.py:1300-1319`,
   which sets `status = "stopped"` and re-raises, but never calls
   `self._fail_all_receipts()` — that method (`interpreter.py:774-...`) is
   only invoked from `_teardown()` (`interpreter.py:979-996`), which only
   `stop()`'s orderly path reaches.

Confirmed by `battle-5e07ba8/concurrency/d4_plugin_cancellederror.py`
(case 1) and `battle-5e07ba8/soak/repro_d_soak_1.py` (case 2, merged here
per the register as `D-concurrency-4` + `D-soak-1`: both are "the run loop
terminated abnormally and neither normalized `status` nor failed the
outstanding receipts").

## Impact

**General users:** any plugin/observer hook is user code running inside the
interpreter's own loop; the library's documented containment story
(`_SafePlugin._guarded`, `base_interpreter.py:239-251`) only covers
`Exception`, deliberately not `BaseException`/`CancelledError` — but nothing
tells the loop the difference between an internally-manufactured one and a
real external cancel. Any transport/metrics/observability plugin whose
`await`-based work uses `task.cancel()` semantics, or that wraps
`concurrent.futures`, can trigger this.

**Order-management scenario:** an order-processing interpreter with a
metrics-export plugin hits this the moment the plugin's async transport
surfaces a cancellation (e.g. an internal timeout using
`asyncio.wait_for` around a metrics push). The interpreter now silently
stops processing orders while `status` still reads `"running"` — nothing
alerts on it, `queue_depth` grows unbounded as later events queue instead
of being refused, and any caller awaiting `send(..., wait=True)` to confirm
an order state change hangs forever unless it independently wraps every
call in its own timeout.

## Proposed fix

- In the inner per-event handler, only re-raise `CancelledError` without
  touching `status` when it is verified to correspond to the loop's own
  task being cancelled (e.g. check `asyncio.current_task().cancelled()`
  after catching, or track a `self._external_cancel_requested` flag set
  only by `stop()`/task cancellation, and default to normalizing `status`
  to `"error"` when that flag is not set).
- In the outer `except BaseException` handler (`interpreter.py:1300-1319`),
  call `self._fail_all_receipts()` before/alongside `self.status =
  "stopped"`, so no receipt is ever silently orphaned regardless of which
  exception path killed the loop.
- Move the `plugin.on_event_received(...)` call (`interpreter.py:1206-1208`)
  inside the same per-event `try` that already resolves receipts, so a
  raising hook there follows the existing "log and carry on" containment
  path instead of escaping to the loop-level handler.

Compatibility: additive; the only observable change is that `status` no
longer misreports a dead loop as `"running"`, and receipts fail instead of
hanging — both align with the documented intent already stated in the
surrounding comments.

## Acceptance criteria

- [ ] `repro/R4-16_run_loop_death_status_not_normalized.py` exits 0
- [ ] New test `tests/test_interpreter.py::test_manufactured_cancelled_error_normalizes_status`
      covers the `CancelledError`-from-plugin-hook case
- [ ] New test `tests/test_interpreter.py::test_run_loop_death_fails_pending_receipts`
      covers the `on_event_received`-raises case (merged `D-soak-1`)
- [ ] Both tests assert `status != "running"` after loop death and that a
      pending/subsequent `wait=True` receipt raises/rejects within a bounded
      time rather than hanging

## Related

- Merges register rows for `D-concurrency-4` and `D-soak-1` (register:
  "Both are 'run loop died abnormally; status not normalized, receipts not
  failed'")
- R4-32 (same track, noted in the register as sharing the caveat that
  these are non-vanilla-usage shapes — still a fair containment
  expectation per the library's own documentation)
- Register source ids: `battle-5e07ba8/concurrency/d4_plugin_cancellederror.py`,
  `battle-5e07ba8/soak/repro_d_soak_1.py`

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (venv: `xstate-statemachine/.venv-main`)
- Commit: `5e07ba8`
- Ran `repro/R4-16_run_loop_death_status_not_normalized.py` in a fresh
  process (60 s cap): output matched the Observed block verbatim; exit code
  `1`.
- Confirmed root cause at `src/xstate_statemachine/interpreter.py:1206-1208`
  (`plugin.on_event_received(self, event)` outside the per-event `try`),
  `:1246-1247` (`except asyncio.CancelledError: raise` inside the per-event
  try), `:1285-1299` (outer `except asyncio.CancelledError` that
  deliberately does not touch `status`), and `:774`/`:996`
  (`_fail_all_receipts` only invoked from `_teardown()`) — all line ranges
  and code exactly as cited.
- Fetched `https://stately.ai/docs/actors#actor-status`: confirmed actor
  snapshots/status are the documented mechanism for observing a
  running/stopped/errored actor, supporting the "a dead run loop must not
  keep reporting itself as running" claim.
- Searched `gh issue list -R basiltt/xstate-statemachine --state all --limit
  120 --search "CancelledError status"`: no matching open/closed issue; no
  duplicate found.
- No project name/label leakage found in the file.
