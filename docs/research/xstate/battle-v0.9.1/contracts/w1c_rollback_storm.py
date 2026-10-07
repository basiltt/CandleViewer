# -*- coding: utf-8 -*-
"""W1c: STANDALONE. rollback + invoke.onDone whose action raises: is the storm
cut by maxIterations on BOTH service spellings (docs/api RunawayChainError row)?"""
import asyncio, os, sys
os.chdir("<home>")
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

def machine(style):
    if style == "def":
        def svc(i, c, e): return 1
    else:
        async def svc(i, c, e): return 1
    def boom(i, c, e, a): c["n"] += 1; raise RuntimeError("boom")
    cfg = {"id": "m", "initial": "idle", "actionErrorPolicy": "rollback", "context": {"n": 0},
           "states": {"idle": {"on": {"GO": "fetching"}},
                      "fetching": {"invoke": {"src": "svc", "onDone": {"target": "done", "actions": ["boom"]}}},
                      "done": {}}}
    return create_machine(cfg, logic=MachineLogic(actions={"boom": boom}, services={"svc": svc}))

async def one(style):
    i = Interpreter(machine(style), clock=SimulatedClock()); await i.start()
    await i.send("GO")
    samples = []
    for _ in range(6):
        await asyncio.sleep(0.25); samples.append((i.context["n"], i.chain_trips))
    await i.stop()
    stalled = samples[-1][0] == samples[-2][0]
    print("%-5s samples(n,chain_trips)=%s -> %s" % (style, samples,
          "CUT (bounded)" if stalled and samples[-1][1] > 0 else "UNBOUNDED"))
    return stalled and samples[-1][1] > 0

async def main():
    r = [await one(s) for s in ("async", "def")]
    sys.exit(0 if all(r) else 1)
asyncio.run(main())
