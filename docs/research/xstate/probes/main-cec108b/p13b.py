import asyncio, threading
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase
CFG={"id":"t","initial":"a","maxIterations":20,
     "states":{"a":{"on":{"PING":{"target":"a","actions":["n"]}}}}}
class P(PluginBase):
    def __init__(self): self.ev=[]
    def on_error(self,i,e): self.ev.append(("on_error",type(e).__name__))
    def on_transition_failed(self,i,*a): self.ev.append(("failed",))
    def on_event_dropped(self,i,ev,reason=None,**k): self.ev.append(("dropped",reason))
async def main():
    hits={"n":0}
    def n(i,c,e,a):
        hits["n"]+=1
        if hits["n"]<300:
            threading.Thread(target=lambda: i.send_threadsafe("PING", internal=True)).start()
    m=create_machine(CFG, logic=MachineLogic(actions={"n":n}))
    p=P(); i=Interpreter(m); i.plugins.append(p) if hasattr(i,"plugins") else i._plugins.append(p)
    await i.start(); await i.send("PING"); await asyncio.sleep(1.0)
    print("hits",hits["n"],"status",i.status,"error",i.error,
          "last_transition_ok",getattr(i,"last_transition_ok",None),
          "last_error",type(getattr(i,"last_error",None)).__name__)
    print("plugin events:",p.ev[:5])
    await i.stop()
asyncio.run(main())
