# -*- coding: utf-8 -*-
"""Why does the chain budget hold at 1003 in one shape and not the other?

`repro_167_knobs.py`: rollback+onDone cycle entered from the INITIAL state,
plain-`def` service -> caps at 1003 (RunawayChainError, chain_budget drop).
`repro_r603_min.py`:  same cycle entered by an EXTERNAL event, async service
                      -> ~1330/s with no ceiling.

Two candidate causes, varied independently:
  * entry = initial configuration vs reached by an external `send`
  * service = plain `def` (thread pool) vs `async def` (loop)
"""
from __future__ import annotations
import asyncio, json

from xstate_statemachine import (Interpreter, MachineLogic, OverflowPolicy,
                                 create_machine)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase


def cfg(external: bool):
    work = {"invoke": {"id": "s", "src": "svc",
                       "onDone": {"target": "#spin.recording",
                                  "actions": ["boom"]}}}
    if not external:
        return {"id": "spin", "actionErrorPolicy": "rollback",
                "initial": "starting", "context": {},
                "states": {"starting": work, "recording": {}}}
    return {"id": "spin", "actionErrorPolicy": "rollback",
            "initial": "idle", "context": {},
            "states": {"idle": {"on": {"GO": {"target": "#spin.starting"}}},
                       "starting": work, "recording": {}}}


class Drops(PluginBase):
    def __init__(self):
        self.dropped = []
    def on_event_dropped(self, i, e, reason):
        self.dropped.append(reason)


async def probe(external: bool, is_async: bool):
    calls = [0]

    def boom(*a):
        raise RuntimeError("boom")

    def svc_sync(i, c, e):
        calls[0] += 1
        return 1

    async def svc_async(i, c, e):
        calls[0] += 1
        return 1

    m = create_machine(cfg(external),
                       logic=MachineLogic(
                           actions={"boom": boom},
                           services={"svc": svc_async if is_async
                                     else svc_sync}))
    d = Drops()
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE).use(d)
    await i.start()
    if external:
        await asyncio.wait_for(i.send("GO"), 10)
    await asyncio.sleep(1.0)
    a = calls[0]
    await asyncio.sleep(2.0)
    b = calls[0]
    out = {"entered_by": "external send" if external else "initial state",
           "service": "async def" if is_async else "plain def",
           "svc@1s": a, "svc@3s": b, "still_growing": b > a + 5,
           "status": i.status,
           "last_error": type(getattr(i, "last_error", None)).__name__,
           "drops": sorted(set(d.dropped))}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        out["stop"] = repr(e)
    return out


async def main():
    res = []
    for external in (False, True):
        for is_async in (False, True):
            r = await probe(external, is_async)
            print(json.dumps(r), flush=True)
            res.append(r)
    json.dump(res, open("out_167_axes.json", "w"), indent=1, default=str)
    print("\nSTILL GROWING AT 3s:",
          [(r["entered_by"], r["service"]) for r in res if r["still_growing"]])


asyncio.run(main())
