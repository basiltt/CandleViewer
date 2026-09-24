---
r4: R4-27
title: "Bug: SyncInterpreter.tick() delivers only one due `after` deadline per call on chained deadlines"
labels: [bug, severity/medium, area/timers, area/sync-interpreter]
severity: Medium
repro_script: repro/R4-27_sync_tick_chained_deadlines.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`SyncInterpreter.tick()` pumps due timers only while its internal event
queues are non-empty for that call, and exits as soon as they drain for the
current step. When several `after` deadlines chain (state A's deadline fires
a transition into state B, whose own `after` deadline is *also* already due
by wall-clock time), a single `tick()` call advances only one link of the
chain instead of settling all the way to the terminal state a caller
expects, because the newly-armed deadline from the transition it just took
is never re-checked before `tick()` returns. `Interpreter`'s async settle
loop keeps draining until quiescent, so it reaches the terminal state in one
wall-clock wait. A caller polling `tick()` once per interval (a realistic,
common pattern) silently lags one or more rungs behind where wall-clock time
says it should be.

## Environment

- Commit: `5e07ba8` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- Install: editable clone at `_ref/xstate-statemachine`, run via its
  `.venv-main` interpreter

## Minimal reproduction

```python
"""R4-27: SyncInterpreter.tick() delivers only ONE due `after` deadline per
call when deadlines chain (a->b->c->d, each `after: 0`/short). Its while-loop
pumps timers only while the internal queues are non-empty and exits as soon
as the queue drains for that step, so a newly-armed already-due timer from
the just-completed transition is never observed before tick() returns. The
async engine's settle loop keeps draining until quiescent, so it walks the
whole chain in one wall-clock settle.

Realistic shape: an ack-timeout -> retry -> escalate ladder, all already due
after a stall. A caller ticking once per poll lands one rung below where
wall-clock says it should be.

Exits 1 while a single tick() after all deadlines are already due leaves the
sync engine short of the terminal state that the async engine reaches in one
settle.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time

sys.path.insert(
    0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

CFG = {
    "id": "order",
    "initial": "submitted",
    "states": {
        "submitted": {"after": {50: "ack_timeout"}},
        "ack_timeout": {"after": {50: "retry"}},
        "retry": {"after": {50: "escalated"}},
        "escalated": {},
    },
}


def sync_run():
    s = SyncInterpreter(create_machine(CFG, logic=MachineLogic())).start()
    time.sleep(0.25)  # all three deadlines are now due
    s.tick()  # a single tick, as a poll-based caller would do
    result = sorted(s.current_state_ids)
    s.stop()
    return result


async def async_run():
    i = await Interpreter(create_machine(CFG, logic=MachineLogic())).start()
    await asyncio.sleep(0.25)
    result = sorted(i.current_state_ids)
    await i.stop()
    return result


if __name__ == "__main__":
    sync_result = sync_run()
    async_result = asyncio.run(async_run())
    print(f"OBSERVED: sync (1 tick after 0.25s)={sync_result}  async (0.25s settle)={async_result}")
    print("EXPECTED: sync == ['order.escalated'] == async; every due deadline drains in one tick()")
    if sync_result == async_result:
        print("PASS")
        sys.exit(0)
    print("FAIL: sync tick() lags behind the fully-settled async state")
    sys.exit(1)
```

## Observed behaviour

```
OBSERVED: sync (1 tick after 0.25s)=['order.ack_timeout']  async (0.25s settle)=['order.escalated']
EXPECTED: sync == ['order.escalated'] == async; every due deadline drains in one tick()
FAIL: sync tick() lags behind the fully-settled async state
```

The battle-track scripts (`battle-5e07ba8/semantics/repro/d1_sync_after0_chain.py`,
`d1d_realistic.py`) additionally show that a 4-link `after: 0` chain
(`a->b->c->d`) needs **three** `tick()` calls to walk from `a` to `d` on the
sync engine, while the async engine reaches `d` in a single 0.25s settle.

## Expected behaviour

A single call that is documented as "advance the sync interpreter's clock
and process all currently-due work" should drain every deadline that is due
at the moment it is called, including deadlines newly armed by transitions
taken during that same call — matching XState's own macrostep semantics,
where a macrostep runs to completion (processing all eventless/timer-driven
transitions) before control returns to the caller, and matching the async
engine's observable behavior for the identical wall-clock wait.

## Root cause analysis

`sync_interpreter.py`'s `tick()` implementation pumps due timers in a
while-loop that continues only while its internal event queues are
non-empty for the current step; it does not re-check the timer heap after
draining that step's queue, so a timer that becomes due only as a
*consequence* of the transition just taken (i.e. armed by entering the new
state) is left unprocessed until the *next* `tick()` call. `SimulatedClock`
usage elsewhere is unaffected because `_advance_to` re-reads the heap
directly rather than relying on the queue-draining loop.

## Impact

For a retry/escalation ladder (ack-timeout → retry → escalate, all already
due after a stall — a realistic shape for an order acknowledgment timeout
chain), a caller polling `tick()` once per interval systematically
undercounts how far the state machine should have progressed by wall-clock
time. In an order-management context this means an order can sit at
"ack_timeout" when wall-clock time says it should already be "escalated",
delaying whatever escalation/alerting action depends on reaching that state.

## Proposed fix

Have `tick()` re-check the timer heap after each settle/transition rather
than only while the initial queues are non-empty — i.e. loop until neither
the event queue nor the timer heap has anything due, not just until the
queue empties once. This matches `SimulatedClock._advance_to`'s existing
re-read-the-heap behavior and the async engine's settle-to-quiescence
semantics.

## Acceptance criteria

- [ ] `SyncInterpreter.tick()`, called once after all deadlines in a chain
      are due, reaches the same terminal state the async engine reaches
      after an equivalent wall-clock wait.
- [ ] A test named `test_sync_tick_drains_chained_after_deadlines` (or
      equivalent) exists under `tests/` covering the 3-stage ack/retry/
      escalate ladder shape.
- [ ] `repro/R4-27_sync_tick_chained_deadlines.py` exits 0 once fixed.

## Related

- Register row R4-27 (filed Medium, stands as filed on re-triage).
- Source: `battle-5e07ba8/semantics/repro/d1_sync_after0_chain.py`,
  `d1d_realistic.py`.

## Verification

- Date: 2026-09-19
- Python: `.venv-main` interpreter, version 3.13.7
- Commit: `5e07ba8` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Ran `repro/R4-27_sync_tick_chained_deadlines.py` fresh, standalone: exit
  code `1`, output matched the Observed section verbatim
  (`sync (1 tick after 0.25s)=['order.ack_timeout']  async (0.25s
  settle)=['order.escalated']`).
- Confirmed root cause: `SyncInterpreter.tick()` (`sync_interpreter.py:1265-
  1277`) calls `self._pump_timers()` once, then — only if the resulting
  event queue is non-empty — `self._process_event_queue()` and
  `self._process_transient_transitions()` once each, and returns. There is
  no loop back to re-check the timer heap for a deadline that becomes due
  only as a consequence of the transition just processed (e.g. entering a
  new state whose own `after` is already past-due by wall-clock time), so a
  chain of already-due deadlines advances exactly one link per `tick()`
  call.
- Checked the XState/SCXML claim: confirmed (same macrostep run-to-
  completion sources as R4-21's verification — XState v5's macrostep loop
  draining `_internalQueue` and SCXML's run-to-completion semantics) that a
  single macrostep is expected to settle all eventless/timer-driven
  transitions before returning control to the caller; `tick()`'s doc
  comment itself ("fires due deadlines onto the queue and processes them")
  implies full settlement, which the code does not deliver for chained
  already-due deadlines.
- No project name/label leak found. No duplicate found; `gh issue list`
  search for "after deadline" surfaced #76 (a different defect: `tick()`
  timers unreachable when constructed inside a running asyncio loop) and
  #50 (threading model for timers) — neither addresses single-tick chain
  lag.
