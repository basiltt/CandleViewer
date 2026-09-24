# -*- coding: utf-8 -*-
"""Which interpreter knob defeats the #167 chain budget?

`repro_167_delta.py` shows both raise-shapes bound at ~1003 invocations with a
default `Interpreter(m)`. The contract harness (mandatory config for this
track) adds SimulatedClock + max_queue_size=64 + OverflowPolicy.RAISE, and the
same machine then spins ~1330/s indefinitely. Vary one knob at a time.
"""
from __future__ import annotations
import asyncio, json

from xstate_statemachine import (Interpreter, MachineLogic, OverflowPolicy,
                                 create_machine)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

CFG = {
    "id": "spin", "actionErrorPolicy": "rollback", "initial": "starting",
    "context": {},
    "states": {
        "starting": {"invoke": {"id": "s", "src": "svc",
                                "onDone": {"target": "#spin.recording",
                                           "actions": ["boom"]}}},
        "recording": {},
    },
}


class Drops(PluginBase):
    def __init__(self):
        self.dropped = []
    def on_event_dropped(self, i, e, reason):
        self.dropped.append(reason)


async def probe(label, **kw):
    calls = [0]

    def boom(*a):
        raise RuntimeError("boom")

    def svc(i, c, e):
        calls[0] += 1
        return 1

    m = create_machine(json.loads(json.dumps(CFG)),
                       logic=MachineLogic(actions={"boom": boom},
                                          services={"svc": svc}))
    d = Drops()
    i = Interpreter(m, **kw).use(d)
    await i.start()
    await asyncio.sleep(0.8)
    a = calls[0]
    await asyncio.sleep(1.2)
    b = calls[0]
    out = {"cfg": label, "svc@0.8s": a, "svc@2.0s": b,
           "bounded": a == b, "status": i.status,
           "last_error": type(getattr(i, "last_error", None)).__name__,
           "drops": sorted(set(d.dropped))}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        out["stop"] = repr(e)
    return out


async def main():
    cases = [
        ("default Interpreter(m)", {}),
        ("clock=SimulatedClock()", {"clock": SimulatedClock()}),
        ("max_queue_size=64 + RAISE",
         {"max_queue_size": 64, "overflow_policy": OverflowPolicy.RAISE}),
        ("SimulatedClock + max_queue_size=64 + RAISE (track config)",
         {"clock": SimulatedClock(), "max_queue_size": 64,
          "overflow_policy": OverflowPolicy.RAISE}),
    ]
    res = []
    for label, kw in cases:
        r = await probe(label, **kw)
        print(json.dumps(r), flush=True)
        res.append(r)
    json.dump(res, open("out_167_knobs.json", "w"), indent=1, default=str)
    print("\nUNBOUNDED CONFIGS:", [r["cfg"] for r in res if not r["bounded"]])


asyncio.run(main())
