# -*- coding: utf-8 -*-
"""X9 -- concurrency under restore + start()-descent-settle (#215).

STANDALONE. Neutral cwd.

  A  100 CONCURRENT start()s of a chart with an `always` cycle + a
     zero-delay `raise` in the initial descent (#215: the run loop waits
     for the descent to settle, descent raises get seed standing). Is the
     start bounded? Watchdog; a start that never returns IS the result.
     Lap counts must agree machine-to-machine (determinism under load).
  B  200 v3 snapshots WITH scheduled_sends restored CONCURRENTLY: every
     one re-arms, none fires early, all fire.
  C  #215 lap parity: async vs sync on the `always` + zero-delay `raise`
     chart at limits 1..25.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock

KIND = os.environ.get("XS_SVC", "async")
NM = int(os.environ.get("XS_NM", "100"))
NR = int(os.environ.get("XS_NR", "200"))


def attach_clock(interp, clock):
    from xstate_statemachine.base_interpreter import _accepts_kwarg

    interp.clock = clock
    interp._clock_accepts_sync = _accepts_kwarg(clock.set_timeout, "sync")
    clock._attach(interp._settle_for_clock)


ALWAYS_SPEC = {
    "id": "aw",
    "maxIterations": 10,
    "initial": "a",
    "context": {"laps": 0},
    "states": {
        "a": {"entry": [{"type": "raise", "params": {"event": "Z"}}, "lap"],
              "always": [{"target": "b"}]},
        "b": {"entry": ["lap"], "on": {"Z": "a"}, "always": [{"target": "a"}]},
    },
}


def build_always(limit=10):
    s = json.loads(json.dumps(ALWAYS_SPEC))
    s["maxIterations"] = limit

    def lap(i, c, e, a):  # noqa: ANN001
        c["laps"] += 1

    async def sa(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return 1

    def sd(i, c, e):  # noqa: ANN001
        return 1

    return create_machine(
        s,
        logic=MachineLogic(actions={"lap": lap},
                           services={"s": sa if KIND == "async" else sd}),
    )


async def part_a():
    print(f"=== A. {NM} concurrent start()s, always + descent raise (#215) ===")
    interps = [Interpreter(build_always()) for _ in range(NM)]
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(
            asyncio.gather(*(i.start() for i in interps),
                           return_exceptions=True),
            timeout=30.0,
        )
        hung = False
    except asyncio.TimeoutError:
        hung = True
    dt = time.monotonic() - t0
    laps = sorted(i.context["laps"] for i in interps)
    errs = {}
    for i in interps:
        k = type(i.error).__name__ if i.error else None
        errs[k] = errs.get(k, 0) + 1
    for i in interps:
        if i.status == "running":
            await i.stop()
    print(f"   all start()s returned in {dt:.2f}s  WATCHDOG_HANG={hung}")
    print(f"   laps: min={laps[0]} max={laps[-1]} distinct={len(set(laps))}")
    print(f"   errors={errs}")
    print(f"   VERDICT bounded+deterministic = "
          f"{'PASS' if not hung and len(set(laps)) == 1 else 'FAIL'}")


ARM_SPEC = {
    "id": "arm",
    "initial": "w",
    "context": {"hits": 0},
    "states": {
        "w": {"entry": [{"type": "raise",
                         "params": {"event": "T", "delay": 200, "id": "t1"}}],
              "on": {"T": {"actions": "hit"}}},
    },
}


def build_arm():
    def hit(i, c, e, a):  # noqa: ANN001
        c["hits"] += 1

    return create_machine(json.loads(json.dumps(ARM_SPEC)),
                          logic=MachineLogic(actions={"hit": hit}))


async def part_b():
    print(f"\n=== B. {NR} v3 snapshots w/ scheduled_sends, restored "
          f"concurrently ===")
    blobs = []
    for k in range(NR):
        c = SimulatedClock()
        i = Interpreter(build_arm(), clock=c)
        await i.start()
        await asyncio.sleep(0)
        await c.increment(50 + (k % 100))  # varied remaining delay
        blobs.append((i.get_snapshot(), 200 - (50 + (k % 100))))
        await i.stop()
    rem_ok = 0
    interps, clocks, rems = [], [], []
    for blob, rem in blobs:
        snap = json.loads(blob)
        ss = snap.get("scheduled_sends") or []
        if len(ss) == 1 and abs(ss[0]["remaining_ms"] - rem) < 0.5 \
                and ss[0].get("send_id") == "t1":
            rem_ok += 1
        c = SimulatedClock()
        i2 = Interpreter.from_snapshot(blob, build_arm())
        attach_clock(i2, c)
        interps.append(i2)
        clocks.append(c)
        rems.append(rem)
    t0 = time.monotonic()
    await asyncio.wait_for(
        asyncio.gather(*(i.start() for i in interps)), timeout=30.0
    )
    dt = time.monotonic() - t0
    early = sum(1 for i in interps if i.context["hits"])
    # advance each to just before its own remaining delay, then past it
    await asyncio.gather(*(c.increment(max(r - 1, 0))
                           for c, r in zip(clocks, rems)))
    await asyncio.sleep(0)
    early2 = sum(1 for i in interps if i.context["hits"])
    await asyncio.gather(*(c.increment(5) for c in clocks))
    await asyncio.sleep(0)
    fired = sum(1 for i in interps if i.context["hits"] == 1)
    extra = sum(1 for i in interps if i.context["hits"] > 1)
    for i in interps:
        if i.status == "running":
            await i.stop()
    print(f"   remaining_ms + send_id correct in blob : {rem_ok}/{NR}")
    print(f"   concurrent start() of {NR} restores     : {dt:.2f}s")
    print(f"   fired at start (must be 0)              : {early}")
    print(f"   fired 1 ms early (must be 0)            : {early2}")
    print(f"   fired exactly once after the remainder  : {fired}/{NR} "
          f"(duplicates {extra})")
    print(f"   VERDICT = {'PASS' if rem_ok == NR and early == 0 and early2 == 0 and fired == NR else 'FAIL'}")


async def part_c():
    print("\n=== C. #215 lap parity async vs sync, limits 1..25 ===")
    bad = []
    for limit in range(1, 26):
        ia = Interpreter(build_always(limit))
        try:
            await ia.start()
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.05)
        la = ia.context["laps"]
        if ia.status == "running":
            await ia.stop()
        isy = SyncInterpreter(build_always(limit))
        try:
            isy.start()
        except Exception:  # noqa: BLE001
            pass
        ls = isy.context["laps"]
        if isy.status == "running":
            isy.stop()
        if la != ls:
            bad.append((limit, la, ls))
    print(f"   limits 1..25: disagreements = {len(bad)} {bad[:6]}")
    print(f"   VERDICT lap parity = {'PASS' if not bad else 'FAIL'}")


async def main():
    print(f"X9 kind={KIND} NM={NM} NR={NR}")
    await part_a()
    await part_b()
    await part_c()


asyncio.run(main())
