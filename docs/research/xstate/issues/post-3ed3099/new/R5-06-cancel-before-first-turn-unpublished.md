---
r5: R5-06
title: "Bug: an external cancel landing before the run loop's first scheduling turn is never published — `status` stays `running`, `is_running` is False, and `send(wait=True)` hangs forever"
labels: [bug, severity/high, area/interpreter, area/events]
severity: High
repro_script: repro/R5-06_cancel_before_first_turn_unpublished.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

`#114` closed the "dead run loop reports healthy" hole by publishing an
external cancel: `status` flips to `"error"`, `.error` carries a `RuntimeError`,
`on_error` fires and pending receipts are failed. The fix lives in the
`except asyncio.CancelledError:` handler *inside* `_run_event_loop`. But
`start()` only `create_task`s the loop and returns without awaiting a turn for
it, so a cancel arriving between `await start()` returning and the task's
first scheduling turn cancels a coroutine that **never began** — the handler
body never runs, `_die()` is never called, and the pre-#114 state is back
verbatim: `status="running"`, `is_running=False`, `error=None`, and
`send(..., wait=True)` hangs forever with no receipt and no exception. One
`await asyncio.sleep(0)` before the cancel moves the landing into the fixed
path, which makes this fully deterministic and demonstrable side by side.

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
"""R5-06: an external cancel landing before the run loop's first scheduling
turn is never published (#114 residual).

#114 makes an externally cancelled run loop flip `status` to "error", fail
pending receipts and fire `on_error`, via the `except asyncio.CancelledError`
handler INSIDE `_run_event_loop`. But `start()` only `create_task`s the loop
and returns. Cancelling in the window between `await start()` returning and
the task's first turn cancels a coroutine that never began, so the handler
never executes: the machine stays `status="running"` with `is_running=False`,
`error=None`, and `send(..., wait=True)` hangs forever.

A single `await asyncio.sleep(0)` before the cancel gives the loop its first
turn and #114 then works perfectly -- the control arm below.

Standalone: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "c114",
    "initial": "a",
    "states": {"a": {"on": {"GO": {"target": "b"}}}, "b": {}},
}


def mk():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


async def case(yield_first: bool) -> dict:
    interp = Interpreter(mk())
    await interp.start()
    if yield_first:
        await asyncio.sleep(0)  # give the run-loop task its first turn
    interp._event_loop_task.cancel()  # noqa: SLF001 -- simulating a supervisor
    await asyncio.sleep(0.15)

    out = {
        "yield_before_cancel": yield_first,
        "status": interp.status,
        "is_running": interp.is_running,
        "error": repr(interp.error),
    }
    try:
        receipt = await asyncio.wait_for(interp.send("GO", wait=True), 2)
        out["send_wait_true"] = f"resolved: error={receipt.error!r}"
    except asyncio.TimeoutError:
        out["send_wait_true"] = "HUNG (no receipt, no exception)"
    except Exception as exc:  # noqa: BLE001
        out["send_wait_true"] = f"raised {type(exc).__name__}"
    try:
        await interp.stop()
    except Exception:  # noqa: BLE001
        pass
    out["publishes_114"] = out["status"] == "error"
    return out


async def main() -> int:
    no_yield = [await case(False) for _ in range(3)]
    with_yield = [await case(True) for _ in range(3)]
    print("cancel BEFORE first scheduling turn:")
    for row in no_yield:
        print("  ", row)
    print("control -- cancel AFTER first scheduling turn:")
    for row in with_yield:
        print("  ", row)
    deterministic = all(not r["publishes_114"] for r in no_yield) and all(
        r["publishes_114"] for r in with_yield
    )
    ok = all(r["publishes_114"] for r in no_yield + with_yield)
    print()
    print(f"OBSERVED: cancel-before-first-turn never publishes the #114 landing "
          f"(3/3 report status='running', is_running=False, error=None and hang "
          f"on send(wait=True)); the control arm publishes 3/3. "
          f"deterministic={deterministic}")
    print("EXPECTED: an externally cancelled run loop publishes the same "
          "terminal landing regardless of whether the task had begun -- "
          "status='error', a cancellation error on .error, on_error fired, "
          "and pending/late receipts failed rather than hung.")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
cancel BEFORE first scheduling turn:
   {'yield_before_cancel': False, 'status': 'running', 'is_running': False, 'error': 'None', 'send_wait_true': 'HUNG (no receipt, no exception)', 'publishes_114': False}
   {'yield_before_cancel': False, 'status': 'running', 'is_running': False, 'error': 'None', 'send_wait_true': 'HUNG (no receipt, no exception)', 'publishes_114': False}
   {'yield_before_cancel': False, 'status': 'running', 'is_running': False, 'error': 'None', 'send_wait_true': 'HUNG (no receipt, no exception)', 'publishes_114': False}
control -- cancel AFTER first scheduling turn:
   {'yield_before_cancel': True, 'status': 'error', 'is_running': False, 'error': 'RuntimeError("Interpreter \'c114\' run loop was cancelled while running; the machine is no longer processing events.")', 'send_wait_true': 'resolved: error=InterpreterStoppedError("Interpreter \'c114\' is error; event \'GO\' was dropped.")', 'publishes_114': True}
   {'yield_before_cancel': True, 'status': 'error', 'is_running': False, 'error': 'RuntimeError("Interpreter \'c114\' run loop was cancelled while running; the machine is no longer processing events.")', 'send_wait_true': 'resolved: error=InterpreterStoppedError("Interpreter \'c114\' is error; event \'GO\' was dropped.")', 'publishes_114': True}
   {'yield_before_cancel': True, 'status': 'error', 'is_running': False, 'error': 'RuntimeError("Interpreter \'c114\' run loop was cancelled while running; the machine is no longer processing events.")', 'send_wait_true': 'resolved: error=InterpreterStoppedError("Interpreter \'c114\' is error; event \'GO\' was dropped.")', 'publishes_114': True}

OBSERVED: cancel-before-first-turn never publishes the #114 landing (3/3 report status='running', is_running=False, error=None and hang on send(wait=True)); the control arm publishes 3/3. deterministic=True
EXPECTED: an externally cancelled run loop publishes the same terminal landing regardless of whether the task had begun -- status='error', a cancellation error on .error, on_error fired, and pending/late receipts failed rather than hung.
RESULT: FAIL
```

Exit code `1`. The split is deterministic across 3/3 in each arm: the *only*
difference between the two arms is a single `await asyncio.sleep(0)`.

## Expected behaviour

**The library's own contract**, quoted from `interpreter.py:1446-1454` — the
`#114` handler:

> 🏛️ #114: cancellation reaching here is EITHER an orderly `stop()` (status
> already "stopped"/"done"/"error") OR something killed the loop task from
> outside while the machine believed it was running. In the second case the
> machine is dead but every probe says healthy and every pending receipt
> hangs forever. [...] what remains here is a genuine external cancel:
> publish it.

The defect is precisely the state that comment describes as the thing `#114`
exists to prevent — "the machine is dead but every probe says healthy and
every pending receipt hangs forever" — reachable through a window the handler
cannot see. The contract must hold for *any* external cancel of the loop task,
not only for one that arrives after the task has had a scheduling turn, since
the caller has no way to observe or control which side of that window their
cancel lands on.

This also matches asyncio's own documented model: `Task.cancel()` on a task
that has not started running still transitions it to cancelled
(https://docs.python.org/3/library/asyncio-task.html#asyncio.Task.cancel —
"the coroutine [...] is not given a chance to clean up" when it has not yet
begun). A library that attaches its cleanup exclusively to an in-coroutine
`except` clause has, by construction, no coverage of that case; the cleanup
must be attached to the task, not inside it.

## Root cause analysis

The `#114` publication is implemented **only** as an in-coroutine handler:

- `src/xstate_statemachine/interpreter.py:444` — `start()` does
  `self._event_loop_task = asyncio.create_task(self._run_event_loop())` and
  then proceeds to plugin notification and returns. Nothing awaits a turn for
  the new task, and nothing is attached to it.
- `src/xstate_statemachine/interpreter.py:1446-1462` — the sole publication
  site:

  ```python
  except asyncio.CancelledError:
      # 🏛️ #114: ...
      if self.status == "running":
          self._die(
              RuntimeError(
                  f"Interpreter '{self.id}' run loop was cancelled "
                  f"while running; ..."
              )
          )
  ```

When `Task.cancel()` is called before the task's first step, asyncio cancels
the *task object* and the coroutine is closed without ever being entered — so
`_run_event_loop`'s `try` block is never established and its `except
CancelledError` cannot fire. `_die()` (`interpreter.py:1605`) is therefore
never called: `status` is left at `"running"` (set eagerly by `start()` at
`interpreter.py:441`, before the task is created), `.error` stays `None`, and
no `on_error` hook fires.

The hang in `send(wait=True)` is the downstream consequence: the receipt
future is created and enqueued, but there is no loop alive to dequeue and
resolve it, and no `_die()` to fail it. There is no timeout on the future, so
the caller blocks indefinitely.

The window is small in wall-clock terms but is not a race in the usual sense:
it is *exactly* the window a supervisor pattern occupies. `asyncio.timeout()`
around a startup sequence, a `TaskGroup` whose sibling fails during bring-up,
or a `KeyboardInterrupt`-driven shutdown during boot all cancel in this
window by construction, because the canceller and `start()` are in the same
task and no `await` that yields has occurred between them.

## Impact

**General users.** Any supervisor that wraps startup in a cancellation scope
can leave an interpreter permanently in the zombie state `#114` was written
to eliminate. The failure is maximally deceptive: the object reports
`status="running"`, so a health check passes, while `is_running` is `False`
and every `send(wait=True)` blocks the calling coroutine forever without
raising. In an `asyncio.TaskGroup`, one such hung `send` prevents the group
from ever exiting, so the hang propagates out of the machine into the
application's shutdown path.

**Concrete order-management scenario.** The order service brings up its
per-symbol machines inside
`async with asyncio.timeout(2.0): await interp.start()`, then registers the
machine in the router. A slow first boot (cold cache, a DNS stall in a sibling
bring-up) trips the timeout in exactly this window. The interpreter is
registered as healthy by the supervisor's own `status == "running"` check but
is dead. Inbound `NEW_ORDER` and `CANCEL` events for that symbol are accepted
by the router and delivered with `wait=True` for the ack; each one hangs the
handling coroutine instead of raising, so the venue receives neither the order
nor an error, and the desk sees requests that never complete rather than
requests that fail. Because `status` never flips, no restart is triggered —
the symbol is silently dark until someone notices the absence of fills.

## Proposed fix

**Design.** Attach the publication to the *task*, not to the inside of the
coroutine, so it is independent of whether the coroutine body ever ran.

1. In `start()`, immediately after
   `self._event_loop_task = asyncio.create_task(self._run_event_loop())`
   (`interpreter.py:444`), attach a done-callback:

   ```python
   self._event_loop_task.add_done_callback(self._on_loop_task_done)
   ```

   with:

   ```python
   def _on_loop_task_done(self, task: "asyncio.Task[Any]") -> None:
       # 🏛️ #114 residual: a cancel landing before the task's first
       #    scheduling turn never enters `_run_event_loop`, so its
       #    `except CancelledError` cannot publish. The done-callback
       #    fires either way and is idempotent with it.
       if self.status != "running":
           return  # orderly stop(), or the in-coroutine handler already published
       if task.cancelled():
           self._die(RuntimeError(
               f"Interpreter '{self.id}' run loop was cancelled while "
               f"running; the machine is no longer processing events."
           ))
           return
       exc = task.exception()
       if exc is not None:
           self._die(exc)
   ```

   The `self.status != "running"` guard makes this idempotent with the
   existing in-coroutine handler: whichever fires first publishes, the second
   is a no-op. It also picks up a second latent case for free — a loop task
   that dies from a non-`CancelledError` exception raised before its own
   handlers are established.

2. **Belt and braces for the hang.** Independently of (1), a receipt future
   created while `is_running` is `False` should be failed immediately with
   `InterpreterStoppedError` rather than enqueued, matching what the control
   arm already returns. `send()` already has the `status`-based guard that
   produces that error in the control arm; extend the predicate from
   `status`-only to `status or not is_running`, so a caller is never blocked
   by a machine with no live loop even if some future path re-opens a
   publication gap.

3. **Consider giving `start()` the first turn.** A single
   `await asyncio.sleep(0)` at the end of `start()` would close *this*
   window by making the loop task always have begun before `start()` returns.
   This is attractive as a defence in depth but is not sufficient on its own —
   it narrows the window rather than removing the structural gap, and it
   changes `start()`'s scheduling behaviour for every caller. Recommended
   only in addition to (1), if at all.

**Compatibility.** Additive. (1) changes behaviour only in cases that are
currently silent zombies. (2) converts a hang into the `InterpreterStoppedError`
receipt that the equivalent post-first-turn case already returns, so it makes
the two paths agree rather than introducing a new outcome.

**Alternatives considered.** Documenting "do not cancel the loop task before
it has run" was rejected: the caller cannot observe which side of the window
their cancel lands on, and the pattern that hits it (a cancellation scope
around startup) is idiomatic asyncio, not an abuse.

## Acceptance criteria

- [ ] `repro/R5-06_cancel_before_first_turn_unpublished.py` exits `0`.
- [ ] `tests/test_interpreter_cancel.py::test_cancel_before_first_turn_publishes`
      — `await start()`, cancel `_event_loop_task` with **no** intervening
      `await`, then assert `status == "error"`, `.error` is a `RuntimeError`
      naming cancellation, and `on_error` fired exactly once.
- [ ] `tests/test_interpreter_cancel.py::test_cancel_after_first_turn_still_publishes`
      — the existing `#114` control path is unchanged and does not
      double-publish (`on_error` fires exactly once, not twice).
- [ ] `tests/test_interpreter_cancel.py::test_send_wait_true_never_hangs_on_dead_loop`
      — after a cancel in either window, `await asyncio.wait_for(send("GO",
      wait=True), 1)` resolves with an `InterpreterStoppedError` receipt
      rather than raising `TimeoutError`.
- [ ] `tests/test_interpreter_cancel.py::test_timeout_scope_around_start_is_observable`
      — the realistic shape: `async with asyncio.timeout(...)` around a
      deliberately delayed `start()`; after the timeout the interpreter
      reports a terminal status.
- [ ] `tests/test_interpreter_cancel.py::test_loop_task_exception_before_handlers_publishes`
      — the free case from the same callback: a loop task raising a
      non-`CancelledError` exception publishes via `_die` rather than being
      swallowed as a never-retrieved task exception.

## Related

- Round 4: **#114** (the fix this sits under — `#114` closed its reproducer,
  which cancels after the loop has begun; the invariant "an externally
  cancelled loop is always published" is still unenforced for the
  before-first-turn window).
- **R5-11** — the receipt surface cannot distinguish outcomes; here the
  receipt does not arrive at all, which is the degenerate case of the same
  weakness.
- Register source id: `D5-concurrency-3` (unmerged 1:1 for this row).
- Evidence: `battle-3ed3099/concurrency/n6b_cancel_before_first_turn.py`
  (`deterministic: true`, `result: FAIL`).
- Meta: our adoption audit **#26**.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: `3ed3099`
- Ran `repro/R5-06_cancel_before_first_turn_unpublished.py` in a fresh
  process: exit code `1`, output pasted verbatim above; 3/3 in each arm, the
  split fully deterministic.
- Root cause confirmed by reading `src/xstate_statemachine/interpreter.py` at
  `:441-444` (eager `status = "running"`, then bare `create_task` with no
  callback) and `:1446-1462` (the sole `#114` publication site, inside the
  coroutine).

## Verification (independent re-run)

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: `3ed3099`
- Fresh-process re-run of `repro/R5-06_cancel_before_first_turn_unpublished.py`:
  exit code `1`, output byte-identical to the pasted transcript above; 3/3
  deterministic in both arms.
- Root-cause line citations re-checked against source and confirmed exact:
  `interpreter.py:444` (`self._event_loop_task = asyncio.create_task(...)`,
  no done-callback attached) and `:1446` (`except asyncio.CancelledError:`,
  the sole `#114` publication site inside `_run_event_loop`).
- Cited asyncio documentation re-verified against the current Python docs
  (`asyncio-task.html`): `Task.cancel()` on a task raises
  `asyncio.CancelledError` "at the next opportunity" inside the coroutine —
  confirming that a cancel delivered before the coroutine has been entered
  cannot be observed by an in-coroutine `except CancelledError` handler,
  which is exactly the gap this finding documents.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 150 --search "cancel before first turn"` and `--search "114"`
  return only round-4 `#114` (the parent this deepens — a residual window
  `#114`'s own fix does not cover, stated explicitly in Summary/Related),
  plus unrelated `#116`, `#32`, `#106`, `#107`, `#28`, `#111`, `#138`, `#26`.
  No duplicate.
