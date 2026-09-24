# -*- coding: utf-8 -*-
"""B18 kill-switch shape: N external send_priority() during an open macrostep.

#180 says external priority sends are never charged to the chain budget.
Requirement: 0 dropped, 0 charged, all N applied. Both service styles.
"""
from __future__ import annotations
import asyncio, json, logging
from xstate_statemachine import (Interpreter, MachineLogic, OverflowPolicy,
                                 create_machine)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)

CFG = {
    "id": "k", "initial": "run", "maxIterations": 50,
    "actionErrorPolicy": "rollback", "onUnhandled": "error",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "context": {"kills": 0, "laps": 0},
    "states": {
        "run": {
            "invoke": {"id": "w", "src": "work",
                       "onDone": {"target": "#k.run", "reenter": True,
                                  "actions": ["lap"]},
                       "onError": {"target": "#k.halted"}},
            "on": {"KILL": {"target": "#k.halted", "actions": ["kill"]},
                   "PING": {"actions": ["kill"]}},
        },
        "halted": {"on": {"KILL": {"actions": ["kill"]},
                          "PING": {"actions": ["kill"]}}},
    },
}


class P(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, i, e, reason):
        self.dropped.append((getattr(e, "type", "?"), reason))


async def run(style, n=40):
    def kill(i, c, e, a):
        c["kills"] = c["kills"] + 1

    def lap(i, c, e, a):
        c["laps"] = c["laps"] + 1

    async def awork(i, c, e):
        await asyncio.sleep(0.002); return {}

    def dwork(i, c, e):
        return {}

    m = create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic(
        actions={"kill": kill, "lap": lap},
        services={"work": awork if style == "async" else dwork}, strict=True))
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=8,
                    overflow_policy=OverflowPolicy.RAISE)
    p = P(); i.use(p)
    await i.start()
    # Fire N external priority sends while the invoke/onDone chain is open.
    results = await asyncio.gather(
        *[i.send("PING", priority=True) for _ in range(n)],
        return_exceptions=True)
    await asyncio.sleep(2.0)
    exc = [repr(r) for r in results if isinstance(r, BaseException)]
    out = {"style": style, "sent": n, "kills_applied": i.context["kills"],
           "all_applied": i.context["kills"] == n,
           "dropped": p.dropped[:5], "n_dropped": len(p.dropped),
           "send_exceptions": exc[:3], "n_send_exc": len(exc),
           "states": sorted(i.current_state_ids), "status": i.status,
           "interp_error": repr(i.error)}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        out["stop"] = repr(e)
    return out


async def main():
    res = []
    for style in ("async", "def"):
        r = await run(style)
        res.append(r); print(json.dumps(r), flush=True)
    json.dump(res, open("y4_priority.json", "w"), indent=1)


asyncio.run(main())
