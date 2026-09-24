# -*- coding: utf-8 -*-
"""X1 -- v3 snapshot round-trip property, >=300 random machines (#213).

STANDALONE (stdlib + xstate_statemachine). Neutral cwd.

Each machine: random states, random armed `raise(delay=)` self-sends at
random delays, driven by a SimulatedClock. We arm, advance a random slice
of the delay, snapshot, restore, re-attach a fresh SimulatedClock, start,
then advance the REMAINING delay and assert the send fires exactly then --
not earlier, not later, not never.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

KIND = os.environ.get("XS_SVC", "async")
N = int(os.environ.get("XS_N", "300"))


def attach_clock(interp, clock):
    from xstate_statemachine.base_interpreter import _accepts_kwarg

    interp.clock = clock
    interp._clock_accepts_sync = _accepts_kwarg(clock.set_timeout, "sync")
    clock._attach(interp._settle_for_clock)


def build(delay_ms, n_arms, send_id):
    arms = []
    for i in range(n_arms):
        p = {"event": f"PING{i}", "delay": delay_ms}
        if send_id:
            p["id"] = f"sid{i}"
        arms.append({"type": "raise", "params": p})
    spec = {
        "id": "rt",
        "initial": "armed",
        "context": {"hits": []},
        "states": {
            "armed": {
                "entry": arms,
                "on": {
                    f"PING{i}": {"actions": "hit"} for i in range(n_arms)
                },
            }
        },
    }

    def hit(i, c, e, a):  # noqa: ANN001
        c["hits"].append((e.type, round(i.clock.now() * 1000.0, 3)))

    async def svc_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return 1

    def svc_def(i, c, e):  # noqa: ANN001
        return 1

    return create_machine(
        spec,
        logic=MachineLogic(
            actions={"hit": hit},
            services={"s": svc_async if KIND == "async" else svc_def},
        ),
    )


async def one(rnd):
    delay = rnd.choice([1, 5, 17, 50, 120, 333, 1000])
    n_arms = rnd.choice([1, 1, 2, 3])
    send_id = rnd.random() < 0.4
    m = build(delay, n_arms, send_id)
    c1 = SimulatedClock()
    i1 = Interpreter(m, clock=c1)
    await i1.start()
    await asyncio.sleep(0)
    # advance a random slice strictly inside the delay
    frac = rnd.uniform(0.0, 0.9)
    elapsed = delay * frac
    if elapsed > 0:
        await c1.increment(elapsed)
    blob = i1.get_snapshot()
    snap = json.loads(blob)
    await i1.stop()
    if snap.get("version") != 3:
        return ("BADVER", snap.get("version"))
    recs = snap.get("scheduled_sends") or []
    if len(recs) != n_arms:
        return ("COUNT", len(recs), n_arms)
    expect_rem = delay - elapsed
    for r in recs:
        got = r.get("remaining_ms")
        if got is None or abs(got - expect_rem) > 0.5:
            return ("REMAIN", got, expect_rem)
        if send_id and "send_id" not in r:
            return ("NOSID", r)
    # restore
    c2 = SimulatedClock()
    i2 = Interpreter.from_snapshot(blob, m)
    attach_clock(i2, c2)
    await i2.start()
    await asyncio.sleep(0)
    if i2.context["hits"]:
        return ("EARLY_AT_START", i2.context["hits"])
    # just short of the remaining delay
    short = max(expect_rem - 0.5, 0.0)
    if short > 0:
        await c2.increment(short)
        await asyncio.sleep(0)
    if i2.context["hits"]:
        return ("EARLY", i2.context["hits"], expect_rem)
    await c2.increment(2.0)
    await asyncio.sleep(0)
    hits = list(i2.context["hits"])
    await i2.stop()
    if len(hits) != n_arms:
        return ("MISS", len(hits), n_arms, expect_rem)
    return ("OK",)


async def main():
    rnd = random.Random(int(os.environ.get("XS_SEED", "20260922")))
    fails = {}
    ok = 0
    for k in range(N):
        try:
            r = await asyncio.wait_for(one(rnd), timeout=5.0)
        except asyncio.TimeoutError:
            r = ("TIMEOUT",)
        except Exception as exc:  # noqa: BLE001
            r = ("EXC", type(exc).__name__, str(exc)[:120])
        if r[0] == "OK":
            ok += 1
        else:
            fails.setdefault(r[0], []).append((k, r))
    print(f"X1 kind={KIND} N={N} OK={ok}")
    for tag, items in sorted(fails.items()):
        print(f"  {tag}: {len(items)}  first={items[0]}")
    print("VERDICT", "PASS" if ok == N else "FAIL")


asyncio.run(main())
