"""R11-05: is the tiny-delay periodic process a LIVELOCK (starves external
traffic) or a merely fast periodic process? STANDALONE."""
import asyncio, time
from typing import Any
from xstate_statemachine import Interpreter, MachineLogic, create_machine

def cfg(d, act):
    arm = {"type": "raise", "params": {"event": "BEAT", "delay": d}}
    return {"id": "hb", "initial": "up", "maxIterations": 10, "context": {"n": 0},
            "states": {"up": {"entry": [arm, act], "on": {"BEAT": "down", "PING": "done"}},
                       "down": {"entry": [arm, act], "on": {"BEAT": "up", "PING": "done"}},
                       "done": {"type": "final"}}}

def mk(c):
    def b(i, ctx, e, a): ctx["n"] += 1
    async def ab(i, ctx, e, a): ctx["n"] += 1
    return create_machine(c, logic=MachineLogic(actions={"beat": b, "abeat": ab}))

async def main():
    for act in ("beat", "abeat"):
        for d in (0.0001, 1):
            i = await Interpreter(mk(cfg(d, act))).start()
            await asyncio.sleep(0.3)
            t0 = time.perf_counter()
            await i.send("PING")
            # poll to convergence
            for _ in range(200):
                if "done" in str(i.current_state_ids): break
                await asyncio.sleep(0.01)
            lat = round((time.perf_counter() - t0) * 1000, 2)
            print(f"{act:6s} delay={d:<8} beats={i.context['n']:6d} "
                  f"PING latency={lat}ms final={i.current_state_ids}")
            await i.stop()

asyncio.run(main())
