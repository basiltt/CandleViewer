import asyncio
from xstate_statemachine import Interpreter, MachineLogic, create_machine
CONFIG={"id":"p1","initial":"a","context":{"n":0},"states":{"a":{"on":{"PING":{"actions":["bump"]}}}}}
async def bump(i,ctx,ev,ad):
    ctx["n"]+=1
    await asyncio.sleep(0.0005)   # realistic I/O inside an action
class W:
    def __init__(self): self.d=[]
    def on_event_dropped(self,i,e,r): self.d.append(r)
    def __getattr__(self,n): return lambda *a,**k: None
async def main():
    m=create_machine(CONFIG,logic=MachineLogic(actions={"bump":bump}))
    w=W(); it=Interpreter(m); it._plugins.append(w); await it.start()
    N=1500
    async def prod():
        for _ in range(N):
            it.send("PING",priority=True)     # external, separate task
            await asyncio.sleep(0.0001)
    t=asyncio.create_task(prod())
    await t
    await asyncio.sleep(1.0)
    print("sent",N,"processed",it.context["n"],"dropped",len(w.d),set(w.d))
    await it.stop()
asyncio.run(main())
