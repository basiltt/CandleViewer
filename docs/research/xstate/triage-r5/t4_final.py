import json, asyncio, threading, time
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter
from xstate_statemachine.plugins import PluginBase
R={}
def gboom(c,e): raise RuntimeError("guardboom")

class Spy(PluginBase):
    def __init__(s): s.seen=[]
for h in [a for a in dir(PluginBase) if a.startswith("on_")]:
    def mk(h):
        def f(self,*a,**k): self.seen.append(h)
        return f
    setattr(Spy,h,mk(h))

async def main():
    # LD-01: guard raise on an invoke onDone (no caller, no receipt)
    async def svc(i,c,e): return {"ok":True}
    cfg={"id":"ld","initial":"v","guardErrorPolicy":"raise","states":{
      "v":{"invoke":{"id":"ver","src":"svc","onDone":{"target":"done","guard":"bad"}}},"done":{}}}
    sp=Spy()
    m=create_machine(cfg,logic=MachineLogic(services={"svc":svc},guards={"bad":gboom}))
    i=Interpreter(m); i.use(sp); await i.start(); await asyncio.sleep(0.3)
    R["LD01"]={"ids":sorted(i.current_state_ids),"status":i.status,"error":repr(i.error),
               "last_ok":getattr(i,"last_transition_ok",None),"last_error":repr(getattr(i,"last_error",None))[:40],
               "pending_invocations":repr(getattr(i,"pending_invocations",lambda:"n/a")())[:120],
               "error_hooks":[h for h in set(sp.seen) if "error" in h or "fail" in h or "drop" in h]}
    # send a further event: swallowed?
    r=await i.send("ANY", wait=True)
    R["LD01"]["further_send"]={"changed":r.changed,"error":repr(r.error)}
    R["LD01"]["ids_after"]=sorted(i.current_state_ids)
    await i.stop()

    # new error classes -> hooks?
    from xstate_statemachine.exceptions import InvalidEventError
    sp2=Spy()
    m2=create_machine({"id":"e","initial":"a","states":{"a":{"on":{"GO":"b"}},"b":{}}},logic=MachineLogic())
    i2=Interpreter(m2); i2.use(sp2); await i2.start()
    try: await i2.send(42, wait=True)
    except InvalidEventError as ex: R["InvalidEventError_raised"]=True
    R["InvalidEventError_hooks"]=[h for h in set(sp2.seen) if "error" in h or "drop" in h]
    await i2.stop()
asyncio.run(main())

# send_threadsafe backpressure
print(json.dumps(R,indent=1,default=str))
