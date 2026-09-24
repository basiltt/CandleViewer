---
r7: R7-03
title: "Bug: `await start()` hangs unboundedly on a slow invoked child — `_await_actor_bringups` gathers with no timeout and awaits user entry actions; `status` reads `running` throughout"
labels: [bug, severity/high, area/interpreter, area/actors]
severity: High
engines: async `Interpreter`
repro_script: repro/R7-03_start_hangs_on_slow_invoked_child.py
commit: 221ce7c
python: 3.13.7
verified: true
---

## Summary

`await start()` does not return for 30 s while an invoked child's `async def` entry
action sleeps. `_await_actor_bringups` (`interpreter.py:561`, `:2586`) gathers the
bring-up tasks with **no timeout**, and a bring-up awaits `child.start()` — i.e.
arbitrary user entry actions. `status` reads `"running"` for the whole wait.

This is a regression introduced by the fix that made `start()` await actor
bring-ups so children are addressable on return. That fix is good and we verified
it; this is the unbounded-wait side of it.

## Severity — deliberately not Blocker

We filed this as Blocker initially and downgraded it ourselves after testing. The
run loop is **spawned before the await**, so with a bounded call
(`asyncio.wait_for(interp.start(), 1.0)`) the interpreter is live and unharmed:
a `POKE` sent during the window is accepted and processed, the child completes
bring-up afterwards, and `stop()` returns cleanly. No deadlock, no corruption, no
lost events, no leak — a misleading unbounded await, fully contained by a one-line
caller-side bound.

It is still a defect because there is **no timeout knob anywhere in `src/`**, the
CHANGELOG describes children only as "registered", and an `async def` entry action
is fully supported usage. A caller has no way to express "start, but do not wait
forever on a dependency".

## Suggested fix

A timeout parameter on `_await_actor_bringups` (and a corresponding
`Interpreter(...)` or `start(timeout=...)` knob), with the timeout logged as a
warning and the interpreter left running — which is what it already does in
practice.

## Environment

- `xstate-statemachine` @ `221ce7c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- CPython 3.13.7, Windows 11
- async `Interpreter`; parent invokes one child machine whose initial state has an
  `async def` entry action

## Minimal reproduction

`repro/R7-03_start_hangs_on_slow_invoked_child.py` — standalone, library only.
The child's entry action awaits 30 s; the script bounds its own `start()` at 5 s
with `asyncio.wait_for` and carries a 60 s watchdog so it can never hang a runner.
**Exit code 1** means `start()` was still outstanding at the bound; it exits 0
once bring-up is bounded.

## Observed

```
child entry action awaits 30s; caller bound 5.0s.

start() STILL not returned after 5.0s (child entry action sleeps 30s)
status during the wait = 'running'
POKE inside the window: accepted, ctx poked=1
```

## Root cause

`Interpreter.start()` ends with `await self._await_actor_bringups()`
(`interpreter.py:561`). That method (`interpreter.py:2586-2594`) is:

```python
while self._actor_bringups:
    pending, self._actor_bringups = self._actor_bringups, []
    await asyncio.gather(*pending, return_exceptions=True)
```

`asyncio.gather` **takes no timeout parameter** (see
<https://docs.python.org/3/library/asyncio-task.html> — timeouts require
`asyncio.timeout()` / `wait_for`, which are not used here), and each pending
bring-up awaits `child.start()`, i.e. arbitrary user entry actions. There is no
timeout knob anywhere in `src/`.

## Expected

`start()` returns within a bounded time, or exposes a timeout.

- **XState v5.** `createActor(machine).start()` is synchronous and returns
  immediately; invoked actors are started as part of that call and a promise
  actor's pending work never holds `start()` open
  (<https://stately.ai/docs/actors>). There is no v5 shape in which starting the
  root blocks on a child's asynchronous work.
- **asyncio docs.** The library's own await is unbounded by construction; the
  documented way to bound an awaitable is `asyncio.wait_for(aw, timeout)`
  (<https://docs.python.org/3/library/asyncio-task.html>), which `start()` neither
  uses nor offers.

## Impact

**General.** Any machine that invokes a child whose entry action awaits a lock, a
socket, a slow resolver or a remote handshake has an `await start()` whose
duration is set by that dependency, with `status` reading `"running"` throughout
and no timeout knob. Bounded by the caller-side workaround, which is why this is
High and not Blocker.

**Order-management scenario.** A venue-session child whose entry action opens a
socket holds the whole strategy's `start()` open for the venue's timeout, during
which the process looks healthy and a supervisor cannot tell "starting" from
"wedged". Start-up ordering across several venues becomes coupled to the slowest.

## Proposed fix

A timeout parameter on `_await_actor_bringups`, surfaced as
`Interpreter(..., bringup_timeout=...)` or `start(timeout=...)`, with the expiry
logged as a warning and the interpreter left running — which is exactly what it
already does in practice once the caller bounds the call.

## Acceptance criteria

- `test_start_returns_within_bringup_timeout` — a child whose entry action awaits
  longer than the timeout does not hold `start()` past it; **parametrised over
  `def` / `async def` entry-action kinds and over both `Interpreter` and
  `SyncInterpreter`**.
- `test_start_timeout_leaves_interpreter_running` — after the bound expires,
  `status == "running"`, an event sent afterwards is processed, and `stop()`
  returns cleanly.
- `test_bringup_timeout_is_observable` — the expiry is reported (log/warning or
  hook), not silent.
- `test_fast_child_still_addressable_after_start` — #171's guarantee is not
  regressed: a normal child is registered and addressable when `start()` returns.

## Related

This is the unbounded-wait side of **#171** (`start()` awaits invoked-child
bring-up so children are addressable on return), closed against this commit — the
fix itself is correct and we verified it; this deepens it. #171's change also
widened the window that **R7-05** exploits. Register source id: `L-2` /
`probes/main-221ce7c/p2_start_awaits_child_bringup.py`.

## Verification

- Date: 2026-09-20
- Python: 3.13.7 (CPython, Windows 11)
- Library: `221ce7c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- Command: `python repro/R7-03_start_hangs_on_slow_invoked_child.py`
- Exit code: **1** (reproduced)
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 220 --search "start actor bringup"` — no results; #171 is the closest
  and is CLOSED. No open duplicate.
