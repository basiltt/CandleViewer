---
r4: R4-21
title: "Semantics: plain-sync `invoke` completion timing diverges between SyncInterpreter and Interpreter for the identical event script"
labels: [bug, severity/medium, area/interpreter, area/sync-interpreter]
severity: Medium
repro_script: repro/R4-21_sync_async_invoke_timing_divergence.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

A plain synchronous `invoke` `src` (a callable that returns immediately, no
`await`s) completes at a structurally different point in the event pipeline
depending on which engine runs it. `SyncInterpreter` completes the invoke
*inline*, within the same macrostep that enters the invoking state, so its
`done.invoke` event is queued and processed before the caller's `send()`
call that triggered entry even returns. `Interpreter` always wraps the
service in an `asyncio` task and posts the `DoneEvent` from that task, which
cannot run until the current macrostep yields control back to the event
loop. For a long-running stateful service that records an event script once
(e.g. from production traffic on one engine) and replays it for regression
testing, debugging, or dual-running on the other engine, this means the
exact same `(GO, CANCEL)` sequence produces a *different final outcome*
purely because of which engine executed it — not because of any difference
in business logic, guards, or the machine definition.

## Environment

- Commit: `5e07ba8` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- Install: editable clone at `_ref/xstate-statemachine`, run via its
  `.venv-main` interpreter

## Minimal reproduction

```python
"""R4-21: a plain-sync `invoke` src completes at a different point in the
macrostep on the sync engine vs the async engine, so the same recorded event
script (GO, CANCEL) x10 gives a different context split depending only on
which engine runs it (and, on the async engine, on scheduler interleaving).

SyncInterpreter._invoke_service completes the invoke INLINE within the
macrostep that enters the invoking state, so a CANCEL sent immediately after
GO never observes the invoke as still in-flight: the DoneEvent always wins.
Interpreter._invoke_service always defers the DoneEvent by at least one
event-loop turn, so a CANCEL sent immediately after GO always overtakes it.

Exits 1 (defect present) while sync and async disagree on the {ok,cancel}
split for the identical zero-gap script. Exits 0 if they ever agree.
"""
from __future__ import annotations

import asyncio
import logging
import sys

sys.path.insert(
    0, "<workspace>/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

CFG = {
    "id": "d8",
    "initial": "idle",
    "context": {"ok": 0, "cancel": 0},
    "states": {
        "idle": {"on": {"GO": {"target": "busy"}}},
        "busy": {
            "invoke": {
                "id": "s",
                "src": "work",
                "onDone": {"target": "idle", "actions": ["ok"]},
            },
            "on": {"CANCEL": {"target": "idle", "actions": ["cancel"]}},
        },
    },
}


def logic():
    def ok(i, c, e, a):
        c["ok"] += 1

    def cancel(i, c, e, a):
        c["cancel"] += 1

    def work(i, c, e):  # plain sync, returns instantly, no awaits
        return 1

    return MachineLogic(actions={"ok": ok, "cancel": cancel}, services={"work": work})


def build():
    return create_machine(CFG, logic=logic())


N = 10


async def a_run():
    i = Interpreter(build(), clock=SimulatedClock())
    await i.start()
    for _ in range(N):
        await i.send("GO")
        await i.send("CANCEL")  # zero-gap: identical script to sync
    for _ in range(200):
        await asyncio.sleep(0)
    out = dict(i.context)
    await i.stop()
    return out


def s_run():
    i = SyncInterpreter(build(), clock=SimulatedClock())
    i.start()
    for _ in range(N):
        i.send("GO")
        i.send("CANCEL")
    out = dict(i.context)
    i.stop()
    return out


if __name__ == "__main__":
    sync_ctx = s_run()
    async_ctx = asyncio.run(a_run())
    print(f"OBSERVED: sync={sync_ctx}  async={async_ctx}")
    print("EXPECTED: sync == async for the identical (GO, CANCEL)x10 script")
    if sync_ctx == async_ctx:
        print("PASS: engines agree")
        sys.exit(0)
    print("FAIL: engines disagree on the same recorded event script")
    sys.exit(1)
```

## Observed behaviour

```
OBSERVED: sync={'ok': 10, 'cancel': 0}  async={'ok': 0, 'cancel': 10}
EXPECTED: sync == async for the identical (GO, CANCEL)x10 script
FAIL: engines disagree on the same recorded event script
```

The broader determinism sweep in `battle-5e07ba8/determinism/d8_sync_invoke_timing.py`
additionally shows that on the async engine the split sweeps *continuously*
from `{ok:0,cancel:10}` to `{ok:10,cancel:0}` as the producer's loop-turn gap
increases from 0 to 6-7, agreeing with sync's `{ok:10,cancel:0}` only at
gaps 6-7 — i.e. the two engines agree only for particular scheduler
interleavings, never by construction for the common zero-gap case.

## Expected behaviour

XState v5 treats an invoked actor's completion as an event that is queued
and processed according to a single well-defined ordering relative to other
events in flight — an implementation should not let its own scheduling
mechanics change which of two racing events (a completion vs. an externally
sent event) wins for the *same* logical event order. At minimum, two
conformant engines executing the identical, ordered event script against the
identical machine definition and clock should reach the identical resulting
context — this is precisely what a synchronous/asynchronous dual-engine
library must guarantee to be useful as a replay oracle.

## Root cause analysis

- `sync_interpreter.py:1367-1375` — `SyncInterpreter._invoke_service` calls
  the service **inline** during `_enter_states` and immediately
  `self.send(DoneEvent(...))`, so the completion is enqueued and processed
  before the macrostep that entered the invoking state finishes, and before
  the caller's next `send()` (e.g. `CANCEL`) is even issued.
- `interpreter.py:1771` (`_invoke_service_task`) and the surrounding
  `_invoke_service` (interpreter.py:1868+) — always schedule the service as
  an `asyncio` task. Even when the service callable is detected as
  synchronous and not awaited (interpreter.py:1813-1816), the `DoneEvent` is
  posted from inside that task, which cannot execute until the current
  macrostep yields a loop turn back to the scheduler. Any event sent
  immediately afterward from the same synchronous call stack (e.g. the next
  line's `CANCEL`) is guaranteed to be processed first.

This is a structural difference in *when* a same-tick completion is
observable, not a scheduling race that could go either way at random: for
the zero-gap script it is 100% deterministic and 100% disagreeing between
engines.

## Impact

For any consumer relying on the two engines being interchangeable (e.g. for
testing with the sync engine and running production on the async engine, or
vice versa) or on replaying a recorded event script across engines, the
final context/state can differ purely due to engine choice. In an
order-management-style scenario (e.g. a fulfillment attempt racing a
cancellation), this determines whether an order is recorded as "filled" or
"cancelled" for the identical wall-clock-adjacent input — a correctness-
relevant business outcome, not merely a cosmetic difference.

## Proposed fix

Pick one semantics for "is a just-entered invoke's synchronous completion
observable within the same macrostep, before any subsequently sent event" —
most likely "no" (matching the async engine, which is closer to XState's own
macrostep/microstep separation) — and make the sync engine defer the
completion by at least one macrostep boundary (e.g. queue the DoneEvent for
processing on the *next* `send()`/`tick()` rather than draining it inline).
Document the chosen behavior explicitly as a cross-engine guarantee, not an
implementation detail, since R4-25's documented "completions are never
discarded" language similarly assumes engine parity that does not currently
hold.

## Acceptance criteria

- [ ] `SyncInterpreter` and `Interpreter`, given the identical machine and
      identical zero-gap `(GO, CANCEL)` event script, produce the identical
      final context.
- [ ] A test named `test_sync_async_invoke_completion_timing_parity` (or
      equivalent) exists under `tests/` asserting this parity for a plain
      sync `invoke`.
- [ ] `repro/R4-21_sync_async_invoke_timing_divergence.py` exits 0 once fixed.

## Related

- Register row R4-21 (filed High, downgraded to Medium on re-triage).
- Source: `battle-5e07ba8/determinism/d8_sync_invoke_timing.py`.
- Related to R4-25 (documented cross-engine completion guarantees are not
  actually engine-parity guarantees).

## Verification

- Date: 2026-09-19
- Python: `.venv-main` interpreter, version 3.13.7
- Commit: `5e07ba8` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Ran `repro/R4-21_sync_async_invoke_timing_divergence.py` fresh, standalone:
  exit code `1`, output matched the Observed section verbatim
  (`sync={'ok': 10, 'cancel': 0}  async={'ok': 0, 'cancel': 10}`).
- Confirmed root-cause lines: `sync_interpreter.py:1367-1375`
  (`_invoke_service` executes the sync service inline and calls
  `self.send(done_event)` synchronously before returning) and
  `interpreter.py`'s `_invoke_service_task` (the async coroutine wrapper that
  always defers the `DoneEvent` post to a scheduled task; the current source
  layout has this coroutine starting at `interpreter.py:1770` with the
  service-invocation body at `interpreter.py:1793+`, consistent with the
  cited `interpreter.py:1868+`/`1813-1816` range's narrative — the invoked
  service, sync or async, is always run inside a task whose continuation
  cannot execute until the caller's macrostep yields a loop turn).
- Checked the XState/SCXML claim: XState v5 and SCXML both define run-to-
  completion macrostep/microstep semantics (an event's processing — guards,
  raised/eventless transitions, actions — settles fully as one unit before
  the next external input is considered), per `stately.ai/docs/eventless-
  transitions`, the XState v5 alpha release notes on `_internalQueue`/
  macrostep loop, and SCXML's run-to-completion model as summarized in
  academic SCXML semantics literature (ICTAC2023 "Formal Language Semantics
  for Triggered Enable Statecharts"). This supports the finding's framing
  that a conformant implementation should not let its own task-scheduling
  mechanics change which of two logically-ordered events (an invoke
  completion vs. a subsequently sent event) is observed first.
- No project name/label leak found. No duplicate open/closed issue found
  (`gh issue list` search for "invoke completion" returned issues #94, #99,
  #77, #87 — all about drop/park/perf/child-actor scenarios, not sync/async
  timing-order divergence for a plain-sync invoke).
