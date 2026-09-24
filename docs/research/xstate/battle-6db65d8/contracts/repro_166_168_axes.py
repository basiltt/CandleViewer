# -*- coding: utf-8 -*-
"""Generalise the plain-def/async-def split to #168 and #166.

#168 ping-pong `ver -> arm -> ver`, and #166 `always`-into-a-child-with-a-
completed-invoke. Both are pinned in tests/test_round6_findings.py with
plain-`def` services. Run each with `def` and with `async def`.
"""
from __future__ import annotations
import asyncio, json

from xstate_statemachine import (Interpreter, MachineLogic, OverflowPolicy,
                                 create_machine)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

PINGPONG = {  # #168
    "id": "cyc", "initial": "idle", "maxIterations": 50, "context": {},
    "states": {
        "idle": {"on": {"GO": "ver"}},
        "ver": {"invoke": {"id": "ver", "src": "svc",
                           "onDone": {"target": "#cyc.arm"}}},
        "arm": {"invoke": {"id": "arm", "src": "svc",
                           "onDone": {"target": "#cyc.ver"}}},
    },
}

ALWAYS_CHILD = {  # #166
    "id": "m", "initial": "idle", "maxIterations": 50, "context": {},
    "states": {
        "idle": {"on": {"GO": {"target": "#m.a"}}},
        "a": {
            "initial": "a",
            "always": [{"target": "#m.a.a"}],
            "states": {"a": {"invoke": {"id": "i", "src": "svc",
                                        "onDone": {"target": "#m.a.a"}}}},
        },
    },
}


class Drops(PluginBase):
    def __init__(self):
        self.dropped = []
    def on_event_dropped(self, i, e, reason):
        self.dropped.append(reason)


async def probe(cfg, label, is_async):
    laps = [0]

    def svc_s(i, c, e):
        laps[0] += 1
        return 1

    async def svc_a(i, c, e):
        laps[0] += 1
        return 1

    m = create_machine(json.loads(json.dumps(cfg)),
                       logic=MachineLogic(
                           services={"svc": svc_a if is_async else svc_s}))
    d = Drops()
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE).use(d)
    await i.start()
    try:
        await asyncio.wait_for(i.send("GO"), 8)
        sent = "ok"
    except asyncio.TimeoutError:
        sent = "SEND HANG 8s"
    await asyncio.sleep(1.0)
    a = laps[0]
    await asyncio.sleep(2.0)
    b = laps[0]
    out = {"case": label, "service": "async def" if is_async else "plain def",
           "send": sent, "laps@1s": a, "laps@3s": b,
           "still_growing": b > a + 5, "status": i.status,
           "last_error": type(getattr(i, "last_error", None)).__name__,
           "drops": sorted(set(d.dropped))}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        out["stop"] = repr(e)
    return out


async def main():
    res = []
    for cfg, label in ((PINGPONG, "#168 invoke ping-pong"),
                       (ALWAYS_CHILD, "#166 always-into-invoked-child")):
        for is_async in (False, True):
            r = await probe(cfg, label, is_async)
            print(json.dumps(r), flush=True)
            res.append(r)
    json.dump(res, open("out_166_168_axes.json", "w"), indent=1, default=str)
    print("\nESCAPES BUDGET:",
          [(r["case"], r["service"]) for r in res if r["still_growing"]])


asyncio.run(main())
