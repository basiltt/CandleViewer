import sys, asyncio
sys.path.insert(0, r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, SyncInterpreter, Interpreter, MachineLogic
def boom(ctx,e): raise ValueError("guard blew up")
for pol in ("false","true"):
    m=create_machine({"id":"g","initial":"a","guardErrorPolicy":pol,"states":{"a":{"on":{"GO":{"target":"b","guard":"boom"}}},"b":{}}}, logic=MachineLogic(guards={"boom":boom}))
    i=SyncInterpreter(m); i.start()
    r=i.send("GO", wait=True)
    print(f"OBS2 policy={pol}: {r} ok={i.last_transition_ok} err={i.last_error} states={i.current_state_ids}")
class P:
    def __init__(self): self.d=[]
    def on_event_dropped(self,*a,**k): self.d.append((a,k))
async def main():
    async def slow(ctx,e): await asyncio.sleep(0.4)
    m3=create_machine({"id":"q","initial":"a","states":{"a":{"on":{"GO":{"target":"a","actions":["slow"]},"CMD":"a"}}}}, logic=MachineLogic(actions={"slow":slow}))
    p=P(); i3=Interpreter(m3); i3.use(p); await i3.start()
    i3.send("GO"); 
    for n in range(5): i3.send("CMD")
    await asyncio.sleep(0.05)
    print("OBS8 queue_depth before stop:", i3.queue_depth)
    await i3.stop()
    print("OBS8 status:", i3.status, "queue_depth:", i3.queue_depth, "drop hooks:", len(p.d))
asyncio.run(main())
