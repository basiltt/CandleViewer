"""D6-semantics: send_threadsafe(..., internal=True) silently drops exactly one
event per interpreter — no hook, no error, no receipt. internal=False loses none."""
import asyncio, threading, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, create_machine
MAXIT=30
cfg={"id":"f","initial":"a","context":{"n":0},"maxIterations":MAXIT,
     "states":{"a":{"on":{"P":{"actions":["bump"]}}}}}
def bump(i,ctx,e,am): ctx["n"]=ctx.get("n",0)+1
async def run(internal, nth, per, from_loop=False):
    m=create_machine(cfg,logic=MachineLogic(actions={"bump":bump}))
    i=await Interpreter(m).start()
    drops=[]
    class I:
        def on_event_dropped(self,**kw): drops.append(kw)
        def on_unhandled_event(self,**kw): drops.append(kw)
    i.use(I())
    if from_loop:
        for _ in range(per): i.send_threadsafe("P", internal=internal)
    else:
        def w():
            for _ in range(per): i.send_threadsafe("P", internal=internal)
        ts=[threading.Thread(target=w) for _ in range(nth)]
        [t.start() for t in ts]; [t.join() for t in ts]
    exp=per if from_loop else nth*per
    for _ in range(400):
        await asyncio.sleep(0.01)
        if i.context["n"]>=exp: break
    got=i.context["n"]; err=i.last_error; await i.stop()
    return got, exp, len(drops), (type(err).__name__ if err else None)
async def main():
    print("threads  internal per  -> delivered/expected drops last_error")
    for nth,per in [(1,1),(1,2),(1,10),(1,200),(4,200),(8,50)]:
        for internal in (True,False):
            g,e,d,err = await run(internal,nth,per)
            flag = "  <<< LOST %d" % (e-g) if g!=e else ""
            print(f"  {nth:2d}      {str(internal):5}  {per:4d} -> {g}/{e}  drops={d} err={err}{flag}")
    g,e,d,err = await run(True,1,50,from_loop=True)
    print(f"  from the LOOP thread, internal=True, 50 -> {g}/{e} drops={d}{'  <<< LOST %d'%(e-g) if g!=e else ''}")
asyncio.run(main())
