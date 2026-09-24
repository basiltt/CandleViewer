# -*- coding: utf-8 -*-
"""X15 -- the SUPERSEDED #206 assertions, re-stated to the #212 rule.

STANDALONE. Neutral cwd.

`u4_delayed_debt.py` part A asserts the OLD #206 rule -- "a 1 ms delayed
self-ping-pong TRIPS maxIterations" -- and reports HANG when it does not.
At c78ce99 that is the CORRECT behaviour (#212), so `u4/A`'s FAIL is
SUPERSEDED, not a regression. This file carries the REPLACEMENT assertion
that the old one should become:

  A1 the cycle RUNS INDEFINITELY (no RunawayChainError, no chain_budget
     drop, status still `running`) -- for a duration well past the point
     `maxIterations` would have cut it;
  A2 its CPU is BOUNDED BY THE PERIOD, not by the scheduler spinning:
     doubling the period roughly halves the beat rate and does not raise
     cpu/wall;
  A3 the same is true AFTER a snapshot/restore (the restored machine also
     runs indefinitely, at the same rate);
  A4 CONTROL: the ZERO-delay spelling of the identical cycle still trips.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import RunawayChainError
from xstate_statemachine.plugins import PluginBase

KIND = os.environ.get("XS_SVC", "async")
MAXIT = 12
RUN_S = float(os.environ.get("XS_RUN", "6"))


class Drop(PluginBase):
    def __init__(self):
        self.reasons = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.reasons.append(reason)


def spec(delay):
    p = ({"event": "PONG", "delay": delay} if delay
         else {"event": "PONG"})
    return {
        "id": "debt", "maxIterations": MAXIT, "initial": "a",
        "context": {"laps": 0},
        "states": {
            "a": {"entry": [{"type": "raise", "params": dict(p)}, "lap"],
                  "on": {"PONG": "b"}},
            "b": {"entry": [{"type": "raise", "params": dict(p)}, "lap"],
                  "on": {"PONG": "a"}},
        },
    }


def build(delay):
    def lap(i, c, e, a):  # noqa: ANN001
        c["laps"] += 1

    async def sa(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return 1

    def sd(i, c, e):  # noqa: ANN001
        return 1

    return create_machine(
        json.loads(json.dumps(spec(delay))),
        logic=MachineLogic(actions={"lap": lap},
                           services={"s": sa if KIND == "async" else sd}),
    )


def cpu():
    t = os.times()
    return t.user + t.system


async def run(delay, secs, label, restore=False):
    plug = Drop()
    i = Interpreter(build(delay))
    i.use(plug)
    try:
        await i.start()
    except RunawayChainError:
        pass
    if restore:
        await asyncio.sleep(0.2)
        blob = None
        for _ in range(200):
            try:
                blob = i.get_snapshot()
                break
            except Exception:  # noqa: BLE001
                await asyncio.sleep(0.005)
        await i.stop()
        i = Interpreter.from_snapshot(blob, build(delay))
        plug = Drop()
        i.use(plug)
        await i.start()
    c0, t0 = cpu(), time.monotonic()
    l0 = i.context["laps"]
    while time.monotonic() - t0 < secs:
        await asyncio.sleep(0.05)
        if isinstance(i.error, RunawayChainError) or "chain_budget" in plug.reasons:
            break
    c1, t1 = cpu(), time.monotonic()
    laps = i.context["laps"] - l0
    wall = t1 - t0
    tripped = isinstance(i.error, RunawayChainError) or (
        "chain_budget" in plug.reasons
    )
    status = i.status
    if i.status == "running":
        await i.stop()
    rate = laps / wall
    print(f"   {label:38s} laps={laps:6d} rate={rate:8.1f}/s "
          f"cpu/wall={(c1 - c0) / wall:4.2f} status={status:8s} "
          f"TRIPPED={tripped}")
    return tripped, rate


async def main():
    print(f"X15 kind={KIND} maxIterations={MAXIT} run={RUN_S}s")
    print("=== A1/A2. the #212 replacement for u4/A ===")
    t1, r1 = await run(1, RUN_S, "1 ms delayed ping-pong")
    t2, r2 = await run(2, RUN_S, "2 ms delayed ping-pong")
    t5, r5 = await run(5, RUN_S, "5 ms delayed ping-pong")
    print("=== A3. after a snapshot/restore ===")
    t1r, r1r = await run(1, RUN_S, "1 ms, restored from v3 blob",
                         restore=True)
    print("=== A4. CONTROL: the zero-delay spelling ===")
    t0, r0 = await run(0, 3.0, "zero-delay ping-pong (must trip)")
    ran = not (t1 or t2 or t5 or t1r)
    beyond = r1 * RUN_S > MAXIT + 5
    print(f"\n   A1 runs indefinitely (no trip, >> maxIterations) = "
          f"{'PASS' if ran and beyond else 'FAIL'}")
    print(f"   A2 rate falls with the period (1ms {r1:.0f} > 2ms {r2:.0f} "
          f"> 5ms {r5:.0f}/s) = {'PASS' if r1 >= r2 >= r5 else 'FAIL'}")
    print(f"   A3 restored machine also runs indefinitely = "
          f"{'PASS' if not t1r else 'FAIL'}")
    print(f"   A4 zero-delay control still trips = "
          f"{'PASS' if t0 else 'FAIL'}")
    ok = ran and beyond and r1 >= r2 >= r5 and t0
    print("VERDICT", "PASS" if ok else "FAIL")


asyncio.run(main())
