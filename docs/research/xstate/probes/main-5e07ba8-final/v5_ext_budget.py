import asyncio
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase
CFG={"id":"m","initial":"a","context":{"n":0},"states":{"a":{"on":{"T":{"actions":["inc"]},"SLOW":{"actions":["slow"]}}}}}
def inc(i,c,e,a): c["n"]+=1
async def slow(i,c,e,a): await asyncio.sleep(0.5)
class P(PluginBase):
    def __init__(self): self.drops=[]
    def on_event_dropped(self,i,e,reason): self.drops.append((getattr(e,'type',e),reason))
async def run(burst):
    p=P(); i=Interpreter(create_machine(CFG,logic=MachineLogic(actions={"inc":inc,"slow":slow}))); i.use(p)
    await i.start()
    i.send("SLOW"); await asyncio.sleep(0.05)
    for _ in range(burst): await i.send("T")
    await asyncio.sleep(1.2)
    print(f"burst={burst} applied={i.context['n']} lost={burst-i.context['n']} drops={len(p.drops)} reasons={set(r for _,r in p.drops)} last_ok={i.last_transition_ok} err={i.last_error}")
    await i.stop()
async def main():
    for b in (999,1500,3000): await run(b)
asyncio.run(main())
