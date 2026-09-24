"""r19 async: inbox drained to 0 but applied=1/500. Where did the other 499 go?
Count received vs applied vs dropped, then let it fully settle."""
import asyncio, logging, warnings, collections
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine
C = collections.Counter()
class Spy(PluginBase):
    def on_event_received(self, i, e): C[f"recv:{getattr(e,'type','?')}"] += 1
    def on_event_dropped(self, i, e, reason=None, **k): C[f"drop:{reason}:{getattr(e,'type','?')}"] += 1
CFG = {"id":"m","initial":"a","maxIterations":50,"context":{"ext":0},
 "on":{"EXT":{"actions":["extbump"]}},
 "states":{"a":{"on":{"GO":"b"}},
  "b":{"always":{"target":"b2"},"initial":"b2",
   "states":{"b2":{"invoke":{"id":"s","src":"svc","onDone":{"target":"#m.a"}}}}}}}
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
    for _ in range(n):
        await it.send("GO"); it.send("EXT", priority=True); await asyncio.sleep(0)
    await asyncio.sleep(12.0)   # long settle
    ap=(it.context or {}).get("ext",0)
    print(f"  {'async def' if asyncsvc else 'plain def':<9} sent={n} "
          f"recvEXT={C['recv:EXT']} APPLIED={ap} LOST={n-ap} "
          f"inbox={it._event_queue.qsize()} prio={len(it._priority_queue)} "
          f"state={sorted(it.current_state_ids)} "
          f"drops={ {k:v for k,v in C.items() if k.startswith('drop')} }")
    await it.stop()
async def main():
    print("Fate of the 'starved' external events after a long settle:")
    for a in (False, True): await run(a)
asyncio.run(main())
