import asyncio, json
from xstate_statemachine import create_machine, MachineLogic, Interpreter
CFG={"id":"m","initial":"a","context":{},"guardErrorPolicy":"raise",
     "onUnhandled":"ignore","states":{"a":{"on":{"E":[{"target":"b","guard":"g"}]}},"b":{}}}
class H:
    def __init__(self): self.seen=[]
    def on_unhandled_event(self,i,e,a,d): self.seen.append(d)
    def __getattr__(self,n): return lambda *a,**k: None
async def run(mode):
    def g(c,e):
        if mode=="raise": raise RuntimeError("boom")
        return False
    m=create_machine(CFG, logic=MachineLogic(guards={"g":g}))
    h=H(); it=Interpreter(m); it._plugins.append(h); await it.start()
    r=await it.send("E", wait=True); await asyncio.sleep(0.05)
    o={"mode":mode,"disposition":h.seen,"denied":r.denied,"changed":r.changed,
       "error":type(r.error).__name__ if r.error else None}
    await it.stop(); return o
async def m_(): 
    o=[await run("false"),await run("raise")]
    print(json.dumps(o,indent=1)); json.dump(o,open("repro/f5c_async_disposition.json","w"),indent=1)
asyncio.run(m_())
