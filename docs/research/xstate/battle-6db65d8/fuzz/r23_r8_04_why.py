"""Why do received EXT events not apply on the async-def lane? Check the
settle budget: is the macrostep aborting before the root EXT handler runs?"""
import asyncio, logging, warnings, collections
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine
C = collections.Counter()
class Spy(PluginBase):
    def on_event_received(self, i, e):
        C[f"recv@{','.join(sorted(i.current_state_ids))}:{getattr(e,'type','?')}"] += 1
CFG = {"id":"m","initial":"a","maxIterations":50,"context":{"ext":0},
 "on":{"EXT":{"actions":["extbump"]}},
 "states":{"a":{"on":{"GO":"b"}},
  "b":{"always":{"target":"b2"},"initial":"b2",
   "states":{"b2":{"invoke":{"id":"s","src":"svc","onDone":{"target":"#m.a"}}}}}}}
async def a_svc(i,c,e):
    await asyncio.sleep(0); return {"ok":1}
def extbump(i,c,e,a): c["ext"]=c.get("ext",0)+1
async def main():
    it = Interpreter(create_machine(dict(CFG), logic=MachineLogic(
        services={"svc": a_svc}, actions={"extbump": extbump})))
    it.use(Spy())
    await asyncio.wait_for(it.start(), 10)
    for _ in range(100):
        await it.send("GO"); it.send("EXT", priority=True); await asyncio.sleep(0)
    await asyncio.sleep(8)
    print("  receipt sites:", dict(C))
    print("  settle_tripped=", getattr(it,"_settle_tripped",None),
          "settle_iters=", getattr(it,"_settle_iterations",None),
          "raise_depth=", getattr(it,"_raise_depth",None),
          "chain_tripped=", getattr(it,"_chain_tripped",None))
    print("  applied=", (it.context or {}).get("ext"))
    await it.stop()
asyncio.run(main())
