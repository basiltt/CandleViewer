# -*- coding: utf-8 -*-
"""Verify #149 on main@cec108b: plain-def invoked services run off-loop.

Acceptance criteria (issue #149 + CHANGELOG [Unreleased]):
  1. A 0.3s blocking plain-def service does NOT block the event loop: a
     concurrent 10ms ticker keeps advancing while the service runs.
  2. `await start()` returns promptly (well under the service duration) --
     BUT the #116 ordering guarantee must still hold: a service invoked
     from the machine's INITIAL state must complete (its onDone taken)
     before any event sent immediately after `start()` returns is
     processed, exactly as the sync engine does. This is the "#116
     ordering kept" acceptance bar, not just "start() returns fast".
  3. A raising plain-def service still reports error.platform via
     _report_service_failure (onError taken).
  4. A plain-def service returning an awaitable is still awaited via the
     inspect.isawaitable fallback (onDone taken).
  5. The service executor is released (shut down) on stop().
  6. Concurrent services (invoked from independent machines) actually run
     in parallel off the loop, not serialized.

Exit 0 only if every criterion passes.
"""
from __future__ import annotations

import asyncio
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine

failures: list[str] = []


def check(label: str, cond: bool) -> None:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}")
    if not cond:
        failures.append(label)


CFG_SLOW = {
    "id": "s",
    "initial": "w",
    "states": {"w": {"invoke": {"id": "svc", "src": "slow", "onDone": "d"}}, "d": {}},
}


def slow_factory(seconds: float):
    def slow(interp, ctx, event):
        time.sleep(seconds)
        return 1

    return slow


async def crit_1_loop_not_blocked() -> bool:
    ticks = {"n": 0}

    async def ticker():
        while True:
            ticks["n"] += 1
            await asyncio.sleep(0.01)

    t = asyncio.ensure_future(ticker())
    await asyncio.sleep(0.05)
    base = ticks["n"]
    m = create_machine(CFG_SLOW, logic=MachineLogic(services={"slow": slow_factory(0.3)}))
    interp = await Interpreter(m).start()
    # Wait for completion on a wall-clock deadline (not iteration count).
    deadline = time.monotonic() + 3.0
    while interp.value != "d" and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    during = ticks["n"] - base
    t.cancel()
    await interp.stop()
    return during >= 15  # >=15 of an expected ~30 in 0.3s -- loop was live


async def crit_2_ordering_preserved_from_initial_state() -> bool:
    """The #116 guarantee ('same landing point on both engines') must hold
    even when the invoking state is the machine's INITIAL state, not just
    one entered by a later transition."""
    cfg = {
        "id": "s2",
        "initial": "w",
        "states": {
            "w": {
                "invoke": {"id": "svc", "src": "slow", "onDone": "d"},
                "on": {"X": "x"},
            },
            "d": {},
            "x": {},
        },
    }

    async def async_case() -> str:
        m = create_machine(cfg, logic=MachineLogic(services={"slow": slow_factory(0.05)}))
        interp = await Interpreter(m).start()
        await interp.send("X", wait=True)
        v = interp.value
        await interp.stop()
        return v

    def sync_case() -> str:
        m = create_machine(cfg, logic=MachineLogic(services={"slow": slow_factory(0.05)}))
        i = SyncInterpreter(m).start()
        i.send("X")
        v = i.value
        i.stop()
        return v

    a = await async_case()
    b = sync_case()
    print(f"    async value after start()+immediate send(X): {a!r}")
    print(f"    sync  value after start()+immediate send(X): {b!r}")
    return a == b == "d"


async def crit_3_raising_reports_error() -> bool:
    cfg = {
        "id": "e",
        "initial": "w",
        "states": {
            "w": {"invoke": {"id": "svc", "src": "svc", "onDone": "d", "onError": "e"}},
            "d": {},
            "e": {},
        },
    }

    def raises(i, c, ev):
        raise ValueError("nope")

    m = create_machine(cfg, logic=MachineLogic(services={"svc": raises}))
    interp = await Interpreter(m).start()
    deadline = time.monotonic() + 3.0
    while interp.value not in ("d", "e") and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    v = interp.value
    await interp.stop()
    return v == "e"


async def crit_4_awaitable_returning_service() -> bool:
    cfg = {
        "id": "aw",
        "initial": "w",
        "states": {
            "w": {"invoke": {"id": "svc", "src": "svc", "onDone": "d", "onError": "e"}},
            "d": {},
            "e": {},
        },
    }

    def returns_coro(i, c, ev):
        async def later():
            return 7

        return later()

    m = create_machine(cfg, logic=MachineLogic(services={"svc": returns_coro}))
    interp = await Interpreter(m).start()
    deadline = time.monotonic() + 3.0
    while interp.value not in ("d", "e") and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    v = interp.value
    await interp.stop()
    return v == "d"


async def crit_5_executor_released_on_stop() -> bool:
    m = create_machine(CFG_SLOW, logic=MachineLogic(services={"slow": lambda *a: 1}))
    interp = await Interpreter(m).start()
    await asyncio.sleep(0.05)
    created = interp._service_executor is not None
    await interp.stop()
    return created and interp._service_executor is None


async def crit_6_concurrent_services_parallel(n: int = 4, seconds: float = 0.2) -> bool:
    async def one():
        m = create_machine(CFG_SLOW, logic=MachineLogic(services={"slow": slow_factory(seconds)}))
        interp = await Interpreter(m).start()
        deadline = time.monotonic() + 3.0
        while interp.value != "d" and time.monotonic() < deadline:
            await asyncio.sleep(0.005)
        await interp.stop()

    t0 = time.monotonic()
    await asyncio.gather(*(one() for _ in range(n)))
    elapsed = time.monotonic() - t0
    print(f"    {n} x {seconds}s services elapsed: {elapsed:.3f}s (serial would be {n * seconds:.3f}s)")
    return elapsed < seconds * n * 0.7


async def main() -> int:
    print("Criterion 1: loop not blocked by a 0.3s plain-def service")
    check("ticker advances during slow service", await crit_1_loop_not_blocked())

    print("Criterion 2: #116 ordering preserved for a service on the INITIAL state")
    check(
        "async matches sync landing after start()+immediate send",
        await crit_2_ordering_preserved_from_initial_state(),
    )

    print("Criterion 3: raising service reports error.platform")
    check("raising service takes onError", await crit_3_raising_reports_error())

    print("Criterion 4: awaitable-returning plain-def service is awaited")
    check("returns_coro service takes onDone", await crit_4_awaitable_returning_service())

    print("Criterion 5: executor released on stop()")
    check("service executor torn down", await crit_5_executor_released_on_stop())

    print("Criterion 6: concurrent services run in parallel, not serialized")
    check("N services run concurrently", await crit_6_concurrent_services_parallel())

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} criteria failed)")
        return 1
    print("RESULT: PASS (all criteria satisfied)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
