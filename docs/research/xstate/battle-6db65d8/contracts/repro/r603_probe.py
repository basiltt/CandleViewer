import asyncio, time, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter, PluginBase

def cfg(policy, maxit=None):
    c={"id":"spin","actionErrorPolicy":policy,"initial":"starting","context":{},
       "states":{"starting":{"invoke":{"id":"s","src":"svc","onDone":{"target":"#spin.recording"}}},
                 "recording":{"entry":["boom"]}}}
    if maxit is not None: c["maxIterations"]=maxit
    return c

class Audit(PluginBase):
    def __init__(self): self.tf=0; self.drop=[]
    def on_transition_failed(self,i,t,f): self.tf+=1
    def on_event_dropped(self,i,e,reason): self.drop.append(reason)

def boom(i,c,e,a): raise RuntimeError("entry action failed")

async def run(policy, maxit, dur=1.0):
    calls=[]
    async def svc(i,c,e):
        calls.append(1); return {"ok":True}
    a=Audit()
    m=create_machine(cfg(policy,maxit), logic=MachineLogic(actions={"boom":boom},services={"svc":svc}))
    it=Interpreter(m).use(a)
    await it.start()
    await asyncio.sleep(dur)
    r=(len(calls),sorted(it.current_state_ids),it.status,a.tf,
       type(getattr(it,"last_error",None)).__name__, getattr(it,"last_transition_ok",None),
       a.drop[:3])
    try: await it.stop()
    except Exception: pass
    return r

def runsync(policy, maxit):
    calls=[]
    def svc(i,c,e):
        calls.append(1); return {"ok":True}
    a=Audit()
    m=create_machine(cfg(policy,maxit), logic=MachineLogic(actions={"boom":boom},services={"svc":svc}))
    it=SyncInterpreter(m).use(a)
    t=time.monotonic()
    try: it.start()
    except Exception as ex: return ("EXC",type(ex).__name__)
    el=time.monotonic()-t
    r=(len(calls),sorted(it.current_state_ids),it.status,a.tf,
       type(getattr(it,"last_error",None)).__name__, getattr(it,"last_transition_ok",None), a.drop[:3], round(el,2))
    try: it.stop()
    except Exception: pass
    return r

async def main():
    for pol in ("rollback","continue","fail"):
        print("ASYNC",pol,"maxit=dflt", await run(pol,None))
    print("ASYNC rollback maxit=5", await run("rollback",5))
    for pol in ("rollback","continue","fail"):
        print("SYNC ",pol,"maxit=dflt", runsync(pol,None))
asyncio.run(main())
