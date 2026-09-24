import sys, asyncio
sys.path.insert(0, r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, Interpreter, MachineLogic
class P:
    def __init__(self): self.d=[]
    def on_event_dropped(self,*a,**k): self.d.append((a,k))
async def main():
    seen=[]
    async def slow(ctx,e): await asyncio.sleep(1.0)
    def note(ctx,e): seen.append(e.type)
    m=create_machine({"id":"q","initial":"a","states":{"a":{"on":{"GO":{"target":"a","actions":["slow"]},"CMD":{"target":"a","actions":["note"]}}}}}, logic=MachineLogic(actions={"slow":slow,"note":note}))
    p=P(); i=Interpreter(m); i.use(p); await i.start()
    await i.send("GO")
    await asyncio.sleep(0.1)
    for n in range(5): await i.send("CMD")
    print("queue_depth before stop:", i.queue_depth, "seen:", seen)
    await i.stop()
    print("status:", i.status, "queue_depth:", i.queue_depth, "seen after:", seen, "drop hooks:", len(p.d))
asyncio.run(main())
