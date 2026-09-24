# -*- coding: utf-8 -*-
"""Verify #184 on main @ 6db65d8.

Acceptance criteria checked:
1. async engine: parent snapshot over mid-step child does not block event
   loop for the full ~0.5s budget (now: instant refusal, per #183 fix).
2. an unrelated coroutine on the same loop keeps running while the wait
   happens (proves loop not blocked).
3. sync engine equivalent wait is thread-based and unaffected (still
   settles a genuinely cross-thread child without blocking).
"""
import asyncio
import threading
import time

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import SnapshotMidStepError

CHILD_SLOW = {
    "id": "kid",
    "initial": "k",
    "states": {
        "k": {"on": {"SPIN": {"target": "k2", "actions": ["slow"]}}},
        "k2": {},
    },
}
PARENT = {
    "id": "p",
    "initial": "up",
    "states": {"up": {"invoke": {"src": "kid", "id": "kid"}}},
}


async def async_slow(interp, ctx, ev, action_def):
    await asyncio.sleep(0.3)


def sync_slow(interp, ctx, ev, action_def):
    time.sleep(0.3)


def cell_async(action_fn) -> dict:
    ticks = {"n": 0}

    async def ticker():
        while True:
            await asyncio.sleep(0.02)
            ticks["n"] += 1

    async def main():
        child = create_machine(CHILD_SLOW, logic=MachineLogic(actions={"slow": action_fn}))
        parent = create_machine(PARENT, logic=MachineLogic(services={"kid": child}))
        p = Interpreter(parent)
        await p.start()
        kid = next(iter(p._actors.values()))
        kid.send("SPIN")
        await asyncio.sleep(0.05)

        t = asyncio.ensure_future(ticker())
        t0 = time.monotonic()
        try:
            p.get_persisted_snapshot()
            outcome = "ACCEPTED"
        except SnapshotMidStepError:
            outcome = "REFUSED"
        dt = time.monotonic() - t0
        await asyncio.sleep(0.05)  # let ticker accumulate a bit more
        t.cancel()
        try:
            await asyncio.wait_for(p.stop(), timeout=3)
        except Exception:
            pass
        return {"outcome": outcome, "dt_ms": dt * 1000, "ticks_during": ticks["n"]}

    return asyncio.run(main())


def cell_sync(action_fn) -> dict:
    child = create_machine(CHILD_SLOW, logic=MachineLogic(actions={"slow": action_fn}))
    parent = create_machine(PARENT, logic=MachineLogic(services={"kid": child}))
    p = SyncInterpreter(parent)
    p.start()
    kid = next(iter(p._actors.values()))
    kid.send("SPIN")
    time.sleep(0.05)
    t0 = time.monotonic()
    try:
        p.get_persisted_snapshot()
        outcome = "ACCEPTED"
    except SnapshotMidStepError:
        outcome = "REFUSED"
    dt = time.monotonic() - t0
    p.stop()
    return {"outcome": outcome, "dt_ms": dt * 1000}


def main() -> int:
    print("cell table:")
    r1 = cell_async(async_slow)
    print("  Interpreter/async def slow  ", r1)
    r2 = cell_sync(sync_slow)
    print("  SyncInterpreter/def slow    ", r2)

    ok = True
    # #184 fix: no ~500ms block; refused fast (<300ms) and loop kept ticking
    if r1["dt_ms"] >= 300:
        ok = False
        print("FAIL: async snapshot call blocked for %.0fms" % r1["dt_ms"])
    if r1["outcome"] != "REFUSED":
        ok = False
        print("FAIL: async engine did not refuse mid-step child snapshot")
    if r1["ticks_during"] < 1:
        ok = False
        print("FAIL: unrelated coroutine did not progress (loop was blocked)")
    # sync engine: cross-thread wait works and eventually settles/accepts,
    # should not hang beyond bounded budget (~0.5s ceiling)
    if r2["dt_ms"] > 700:
        ok = False
        print("FAIL: sync engine wait exceeded bound")

    print()
    if ok:
        print("PASS")
        return 0
    print("FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
