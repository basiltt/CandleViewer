"""D6-semantics-2 (Medium) — on the ASYNC engine `await Interpreter.start()`
returns before the initial state's `invoke` children are registered, so a
`sendTo` addressed to a child in the very first macrostep(s) finds no live
actor. The delivery failure IS reported (on_event_dropped
reason="unresolved_target" + a soft step error), so it is not silent -- but
`await start()` reads as "the machine is up", and the SYNC engine has the
child addressable the instant `start()` returns. The engines disagree.

Effect: a supervision tree that pokes its child immediately after start
loses the first N pokes on async and zero on sync.
"""
import asyncio, logging, time
logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
child={"id":"kid","initial":"run","states":{"run":{"on":{"PING":{"actions":[{"type":"sendParent","params":{"event":"TICK"}}]}}}}}
parent={"id":"par","initial":"up","context":{"n":0},
 "states":{"up":{"invoke":{"id":"kid","src":"kid"},
  "on":{"TICK":{"actions":["inc"]},"POKE":{"actions":[{"type":"sendTo","params":{"to":"kid","event":"PING"}}]}}}}}
def inc(i,ctx,e,am): ctx["n"]=ctx.get("n",0)+1
def mk(): return create_machine(parent,logic=MachineLogic(actions={"inc":inc},services={"kid":create_machine(child,logic=MachineLogic())}))

async def amain():
    drops=[]
    class Insp:
        def on_event_dropped(self,interp,event,reason): drops.append(reason)
    i=await Interpreter(mk()).start()
    print("async: actors immediately after `await start()` :", list(getattr(i,'_actors',{}) or {}))
    i.use(Insp())
    # first POKE, before the child exists: watch the drop reason
    await i.send("POKE", wait=True)
    print("async: first POKE ->", "drops:", drops, "last_error:",
          (str(i.last_error)[:70] if i.last_error else None))
    N=60
    for _ in range(N): await i.send("POKE", wait=True)
    # (the losses all happen in the first few ms, before the child registers)
    for _ in range(300):
        await asyncio.sleep(0.01)
        if i.context["n"]>=N: break
    print(f"async: sent {N} POKE with wait=True -> parent saw {i.context['n']} TICK; drops={drops}")
    await i.stop()
    # spawn latency
    i=await Interpreter(mk()).start(); t=time.monotonic()
    while not (getattr(i,'_actors',{}) or {}):
        await asyncio.sleep(0.001)
        if time.monotonic()-t>2: break
    print(f"async: child actor became addressable {1000*(time.monotonic()-t):.1f} ms AFTER start() returned")
    await i.stop()

def smain():
    i=SyncInterpreter(mk()).start()
    print("sync : actors immediately after start()        :", list(getattr(i,'_actors',{}) or {}))
    for _ in range(10): i.send("POKE")
    print("sync : sent 10 POKE -> parent saw", i.context["n"], "TICK")
    i.stop()
asyncio.run(amain()); smain()
