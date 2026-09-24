"""Does the runaway EVER surface on the async-def + invoke lane, or is it silent?
Poll last_error every 10ms during the producer run instead of sampling once.
"""
import asyncio, logging, warnings, collections
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

C = collections.Counter()
class Spy(PluginBase):
    def on_event_dropped(self, i, e, reason=None, **k): C[f"drop:{reason}"] += 1

CFG = {"id": "m", "initial": "a", "maxIterations": 50, "context": {"ext": 0},
       "on": {"EXT": {"actions": ["extbump"]}},
       "states": {"a": {"on": {"GO": "b"}},
                  "b": {"always": {"target": "b2"}, "initial": "b2",
                        "states": {"b2": {"invoke": {"id": "s", "src": "svc",
                                                     "onDone": {"target": "#m.a"}}}}}}}

async def a_svc(i,c,e):
    await asyncio.sleep(0); return {"ok":1}
def p_svc(i,c,e): return {"ok":1}
def extbump(i,c,e,a): c["ext"]=c.get("ext",0)+1

async def run(asyncsvc, n=300):
    C.clear()
    it = Interpreter(create_machine(dict(CFG), logic=MachineLogic(
        services={"svc": a_svc if asyncsvc else p_svc}, actions={"extbump": extbump})))
    it.use(Spy())
    await asyncio.wait_for(it.start(), 10)
    seen = collections.Counter()
    async def poll():
        for _ in range(400):
            seen[type(it.last_error).__name__ if it.last_error else "None"] += 1
            await asyncio.sleep(0.01)
    t = asyncio.ensure_future(poll())
    for _ in range(n):
        await it.send("GO"); it.send("EXT", priority=True); await asyncio.sleep(0)
    await t
    print(f"  {'async def' if asyncsvc else 'plain def':<9} last_error samples={dict(seen)} "
          f"drops={dict(C)} applied={(it.context or {}).get('ext',0)}/{n}")
    await it.stop()

async def main():
    print("Is the runaway ever SIGNALLED while starvation is happening?")
    for a in (False, True): await run(a)
asyncio.run(main())
