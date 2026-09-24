"""R9-03 refutation: is the async-def lane PERMANENTLY starved, or merely
behind during the producer burst? Standalone (stdlib + xstate_statemachine).
Identical chart to r18_ext_starvation_repro.py; the only change is the length
of the settle window after the producer stops."""
import asyncio, logging, warnings, collections, time
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

C = collections.Counter()

class Spy(PluginBase):
    def on_event_received(self, i, e): C[f"recv:{getattr(e,'type',e)}"] += 1
    def on_event_dropped(self, i, e, reason=None, **kw): C[f"drop:{reason}"] += 1

CFG = {
    "id": "m", "initial": "a", "maxIterations": 50, "context": {"ext": 0},
    "on": {"EXT": {"actions": ["extbump"]}},
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {"always": {"target": "b2"}, "initial": "b2",
              "states": {"b2": {"invoke": {"id": "s", "src": "svc",
                                           "onDone": {"target": "#m.a"}}}}},
    },
}

async def a_svc(i, c, e):
    await asyncio.sleep(0); return {"ok": 1}
def p_svc(i, c, e): return {"ok": 1}
def extbump(i, c, e, a): c["ext"] = c.get("ext", 0) + 1

def logic(a): return MachineLogic(services={"svc": a_svc if a else p_svc},
                                  actions={"extbump": extbump})

async def trial(async_svc, settle, n=500):
    C.clear()
    it = Interpreter(create_machine(dict(CFG), logic=logic(async_svc)))
    it.use(Spy())
    await asyncio.wait_for(it.start(), 10)
    for _ in range(n):
        await it.send("GO"); it.send("EXT", priority=True); await asyncio.sleep(0)
    t0 = time.time()
    # poll until both queues drain or settle budget elapses
    while time.time() - t0 < settle:
        await asyncio.sleep(0.25)
        if it._event_queue.qsize() == 0 and len(it._priority_queue) == 0:
            break
    ap = (it.context or {}).get("ext", 0)
    err = type(it.last_error).__name__ if it.last_error else None
    print(f"  {'async def' if async_svc else 'plain def':<9} settle<={settle:>4}s "
          f"drained_after={time.time()-t0:5.2f}s APPLIED={ap}/{n} ({100*ap/n:.1f}%) "
          f"inbox={it._event_queue.qsize()} prio={len(it._priority_queue)} "
          f"err={err} drops={ {k:v for k,v in C.items() if k.startswith('drop')} }")
    await it.stop()

async def main():
    print("R9-03: 'starves external priority traffic PERMANENTLY' -- test the word.")
    for a in (False, True):
        for s in (1, 30):
            await trial(a, s)

asyncio.run(main())
