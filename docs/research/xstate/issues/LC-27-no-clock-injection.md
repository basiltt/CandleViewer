---
lc: LC-27
title: "Feature: no clock injection / virtual time — `after` transitions cannot be made deterministic in tests"
labels: [enhancement, severity/high, area/timers, candleviewer]
severity: High
blocks_adoption: true
repro_script: repro/LC-27_no-clock-injection.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
verified_date: 2026-09-15
---

## Summary

There is no `Clock` abstraction anywhere in the library. Both engines call the OS clock directly — `Interpreter._after_timer_task` does `await asyncio.sleep(delay_sec)` (`interpreter.py:1011`), `SyncInterpreter` blocks on `threading.Event.wait`, and `helpers.wait_for` polls on a 5 ms loop. `Interpreter.__init__` accepts only `(machine, input)`, so there is no seam to substitute a simulated clock. The consequence is that any behaviour expressed with `after` can only be tested by sleeping for the real delay: a machine with a 30-second order timeout needs a 30-second test, and a test that asserts *ordering* between two timers is inherently flaky because it depends on real scheduler jitter.

XState v5 solves exactly this with `createActor(machine, { clock })` and a `SimulatedClock` whose `increment(ms)` advances virtual time synchronously. Without an equivalent, timing must be pulled out of the machine and re-implemented in application code, which defeats the main reason to model it as a state machine at all.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7 (also confirmed on 3.12.3)
- OS: Windows 11 (x64)

## Minimal reproduction

```python
"""LC-27 repro: no clock injection / virtual time for `after` transitions.

An `after` transition is driven by a hard-coded `asyncio.sleep`. There is no
`clock` argument on `Interpreter` and no way to advance time, so a test of a
5-second timeout must burn 5 real seconds of wall clock.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

DELAY_MS = 600

CFG = {
    "id": "order",
    "initial": "submitting",
    "states": {
        "submitting": {"after": {DELAY_MS: {"target": "timed_out"}}},
        "timed_out": {"type": "final"},
    },
}


class SimulatedClock:
    """What XState v5 lets you pass as `clock`. Nothing consumes it here."""

    def __init__(self) -> None:
        self.now = 0.0

    def advance(self, ms: int) -> None:
        self.now += ms / 1000.0


async def main() -> int:
    ok = True

    # 1) No `clock` parameter exists on the Interpreter constructor.
    params = list(inspect.signature(Interpreter.__init__).parameters)
    print(f"OBSERVED Interpreter.__init__ params = {params}")
    print("EXPECTED a 'clock' parameter (XState v5 `createActor(m, {clock})`)")
    if "clock" not in params:
        ok = False

    # 2) Passing one is a hard TypeError.
    machine = create_machine(CFG, logic=MachineLogic())
    clock = SimulatedClock()
    try:
        Interpreter(machine, clock=clock)
        print("OBSERVED Interpreter(machine, clock=...) accepted")
    except TypeError as exc:
        print(f"OBSERVED Interpreter(machine, clock=...) -> TypeError: {exc}")
        ok = False

    # 3) Advancing the simulated clock does nothing; only wall time fires it.
    interp = await Interpreter(create_machine(CFG, logic=MachineLogic())).start()
    started = time.monotonic()
    clock.advance(10_000)
    await asyncio.sleep(0)
    fired_after_virtual_advance = "order.timed_out" in interp.current_state_ids
    print(
        "OBSERVED after advancing simulated clock by 10000ms: "
        f"timer fired = {fired_after_virtual_advance}"
    )
    print("EXPECTED timer fired = True (virtual time should drive `after`)")
    if not fired_after_virtual_advance:
        ok = False

    while "order.timed_out" not in interp.current_state_ids:
        await asyncio.sleep(0.01)
    elapsed_ms = (time.monotonic() - started) * 1000
    print(f"OBSERVED real wall-clock time to reach 'timed_out' = {elapsed_ms:.0f} ms")
    print(f"EXPECTED ~0 ms under a simulated clock (real delay is {DELAY_MS} ms)")
    if elapsed_ms >= DELAY_MS * 0.8:
        ok = False
    await interp.stop()

    print("RESULT:", "REPRODUCED (no clock injection)" if not ok else "NOT REPRODUCED")
    return 1 if not ok else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED Interpreter.__init__ params = ['self', 'machine', 'input']
EXPECTED a 'clock' parameter (XState v5 `createActor(m, {clock})`)
OBSERVED Interpreter(machine, clock=...) -> TypeError: Interpreter.__init__() got an unexpected keyword argument 'clock'
OBSERVED after advancing simulated clock by 10000ms: timer fired = False
EXPECTED timer fired = True (virtual time should drive `after`)
OBSERVED real wall-clock time to reach 'timed_out' = 618 ms
EXPECTED ~0 ms under a simulated clock (real delay is 600 ms)
RESULT: REPRODUCED (no clock injection)
```

(exit code 1. The wall-clock figure varies by a few ms per run — it is always ≳ the 600 ms real delay, which is the point.)

## Expected behaviour

XState v5 makes the clock a first-class, injectable actor-system dependency. The `Clock` interface is defined in `packages/core/src/system.ts`:

```ts
export interface Clock {
  setTimeout(fn: (...args: any[]) => void, timeout: number): any;
  clearTimeout(id: any): void;
}
```

`createActor(logic, options)` takes it as the `clock` actor option — `createActor.ts` defaults it to the real `setTimeout`/`clearTimeout` pair and then does `this.clock = options?.clock ?? this.system._clock`, with the system-level clock created once at the root (`createSystem(this, { clock, logger })`) and **inherited by every child actor** via `parent ? parent.system : createSystem(...)`. The actor documents the field as "the clock that is responsible for setting and clearing timeouts, such as delayed events and transitions".

The test double is `SimulatedClock` (`packages/core/src/SimulatedClock.ts`), exported from `xstate`:

```ts
export class SimulatedClock implements SimulatedClock {
  now(): number
  setTimeout(fn, timeout): number
  clearTimeout(id): void
  set(ms: number): void        // throws "Unable to travel back in time" if ms < now
  increment(ms: number): void  // _now += ms, then flush
}
```

`increment`/`set` advance virtual time and then `flushTimeouts()`, which sorts pending timeouts by due time (`start + timeout`) and synchronously calls every `fn` whose `now() - start >= timeout`. The delayed-transitions docs list "Simulated clock" under their Testing section for exactly this purpose.

So the expected shape is: pass a clock at actor creation; the interpreter routes every `after` delay, every `send`-with-`delay`, and every internal timeout through that clock; `clock.increment(ms)` advances virtual time and fires all timers due at or before the new virtual now, in due-time order, synchronously and deterministically; child actors share the parent's clock. The default clock remains the real one, so production behaviour is unchanged.

## Root cause analysis

- `src/xstate_statemachine/interpreter.py:109-122` — `Interpreter.__init__(self, machine, input=None)`. No `clock` parameter, and `base_interpreter.py:268-273` likewise takes only `(machine, interpreter_class, input)`. There is no place to store a clock even if one were supplied.
- `src/xstate_statemachine/interpreter.py:999-1040` — `_after_timer_task(delay_sec, event)` calls `await asyncio.sleep(delay_sec)` (`:1011`), then `await self.send(event)`; `_after_timer` (`:1027-1040`) wraps it in `asyncio.create_task` and registers it with the `TaskManager` for cancel-on-exit. The delay is baked into the coroutine at creation, so nothing outside the event loop's real timer wheel can influence when it resolves.
- `src/xstate_statemachine/sync_interpreter.py:1257-1327` — the synchronous engine has the same shape: `_after_timer` spawns a `timer_thread` (`:1285`) that blocks in `cancel_event.wait(timeout=delay_sec)`.
- `src/xstate_statemachine/helpers.py:54-98` — `wait_for` polls on a `poll_interval=0.005` loop against the loop's own clock (`loop.time()`), and `wait_for_sync` (`:101-131`) polls `time.monotonic()`; both are bound to real time and cannot be made virtual.
- A grep for `clock`/`Clock` across `src/xstate_statemachine/*.py` returns nothing: the abstraction simply does not exist.

## Impact

**General users.** Every test of a delayed transition costs its real delay. Suites that model realistic timeouts (seconds to minutes) become unrunnable in CI, so authors are pushed to shrink delays in test-only machine variants — which means the config under test is not the config that ships. Ordering assertions between two timers, and any attempt at deterministic replay of a recorded run, are impossible: replaying a log of events cannot reproduce the timer interleaving, because timers are driven by wall time rather than by the replayed timeline.

**CandleViewer (trading OMS).** This is the application that prompted the report: an order-management system whose order machine models `submitting → after 30_000 → timed_out`, and whose execution algorithms (TWAP/VWAP-style slicing, quote-driven pegging) express their entire pacing — slice intervals, quote-refresh windows, peg re-price timers — as `after`. With no injectable clock:
- verifying "a `FILLED` arriving at t=29.9 s wins over the timeout" requires a ~30 s test, and is still racy;
- the backtest/replay harness cannot fast-forward a trading day, because the machine insists on real seconds per slice;
- the mitigation actually forced on us is to move all timing *out* of the machines into an external scheduler, which removes the main benefit of modelling the algos as statecharts and re-introduces exactly the hand-rolled timing code the statechart was meant to eliminate.

## Proposed fix

Introduce a small `Clock` protocol and thread it through both engines.

```python
# src/xstate_statemachine/clock.py  (new)
class Clock(Protocol):
    """Mirrors XState's `Clock` interface (setTimeout/clearTimeout)."""
    def now(self) -> float: ...                       # seconds, monotonic
    def set_timeout(self, fn: Callable[[], Any], delay_sec: float) -> Any: ...
    def clear_timeout(self, handle: Any) -> None: ...


class RealClock(Clock):
    """Default. Wraps asyncio (async engine) / threading.Timer (sync engine)."""


class SimulatedClock(Clock):
    """Virtual time, mirroring XState's `SimulatedClock`. `increment(ms)`
    advances virtual now and then flushes every timer whose
    `now - start >= timeout`, in due-time order. `set(ms)` jumps to an
    absolute virtual time and raises if asked to travel backwards."""
    def increment(self, ms: float) -> None: ...
    def set(self, ms: float) -> None: ...
```

Wiring:

1. `BaseInterpreter.__init__(..., clock: Optional[Clock] = None)` stores `self.clock = clock or RealClock()`; `Interpreter.__init__` and `SyncInterpreter.__init__` forward the kwarg. Children spawned via `invoke` **inherit the parent's clock** (`_spawn_and_manage_actor`, `interpreter.py:1190`) so a whole actor tree runs on one virtual timeline — this mirrors XState, where the clock lives on the actor *system* and a child reuses `parent.system`.
2. Rewrite `interpreter.py:_after_timer` (`:1027-1040`) to `handle = self.clock.set_timeout(lambda: self.send(event), delay_sec)` and register `handle` with the `TaskManager` so `_cancel_state_tasks` calls `clock.clear_timeout(handle)`. Same for `sync_interpreter.py:1257-1327`.
3. Route `send(..., delay=…)`/`sendTo` delays and `helpers.wait_for`'s polling through `interpreter.clock` too, so no timing path bypasses the injected clock.
4. `SimulatedClock.increment` must drain timers *and* let the interpreter's macrostep run to quiescence before returning (an `await clock.increment(ms)` variant for the async engine), otherwise the assertion after `increment` races the event loop.

**Backwards compatibility.** Purely additive: `clock` is keyword-only with a `RealClock` default, so existing code and existing timing behaviour are untouched. No deprecation needed. `_ACTOR_POLL_INTERVAL` and `helpers.wait_for`'s 5 ms poll become clock-driven, which is the only observable change for existing tests, and only in that they become schedulable rather than wall-bound.

## Acceptance criteria

- [ ] `Clock` protocol, `RealClock` and `SimulatedClock` exported from `xstate_statemachine`.
- [ ] `Interpreter(machine, clock=…)` and `SyncInterpreter(machine, clock=…)` accepted; `inspect.signature(Interpreter.__init__)` contains `clock`.
- [ ] Invoked child actors inherit the parent's clock.
- [ ] `tests/test_clock.py::test_after_fires_on_simulated_clock_increment` — machine with `after: {30000: "timed_out"}`; `clock.increment(29_999)` leaves it in `submitting`, `clock.increment(1)` moves it to `timed_out`; the test's own wall-clock duration is < 100 ms.
- [ ] `tests/test_clock.py::test_two_timers_fire_in_delay_order_under_simulated_clock` — parallel regions with 100 ms and 200 ms timers; a single `increment(250)` fires them in delay order, deterministically over 100 repetitions.
- [ ] `tests/test_clock.py::test_after_timer_cancelled_on_state_exit_clears_clock_handle` — exiting the state before the delay leaves no pending timer on the `SimulatedClock`.
- [ ] `tests/test_clock.py::test_child_actor_inherits_parent_clock` — a child machine's `after` fires from the parent's `SimulatedClock`.
- [ ] `tests/test_clock_sync.py` — the same `after`/cancel assertions for `SyncInterpreter`.
- [ ] `tests/test_clock.py::test_default_clock_is_real` — with no `clock` argument, an `after: {50: …}` still fires against wall time (no regression).
- [ ] `docs/` gains a "Testing delayed transitions" section showing `SimulatedClock`.
- [ ] `repro/LC-27_no-clock-injection.py` exits 0.

## Related

- LC-26 (timer starvation under load) — both are symptoms of timers being bound to the real event loop; a clock seam also makes LC-26 testable.
- LC-19 (restore does not restart invokes/timers) — a `Clock` gives snapshot restore a well-defined "virtual now" to re-arm timers against.
- LC-28 (invoked-actor completion is polled at 5 ms) — shares the "hard-coded real-time sleep" smell in `interpreter.py`, and `helpers.wait_for`'s 5 ms poll is the same root problem in the test helpers.

## Verification

Independently verified on 2026-09-15.

- **Date:** 2026-09-15
- **Python:** 3.13.7 (venv `.venv-cv`, `xstate-statemachine` 0.7.0 installed with `pip install -e .`)
- **Library commit:** `42612cf41d9750a5982fe75d5bb539d82f1df4a9` (`main`)
- **Repro exit code:** 1 (fails against the library today, as claimed)

Checks performed: (1) the repro script was run in a fresh process and its output matches the Observed section; (2) the embedded code block is byte-identical to the repro file; (3) the Expected section was checked against XState v5 — the doc pages plus the v5 source in `packages/core/src` (`system.ts`, `createActor.ts`, `SimulatedClock.ts`, `eventUtils.ts`); (4) every `file:line` in the Root cause section was opened in the library source and confirmed to say what is claimed; (5) no duplicate exists in the upstream issue tracker (only issue #17, an unrelated closed camelCase/snake_case auto-discovery bug).
