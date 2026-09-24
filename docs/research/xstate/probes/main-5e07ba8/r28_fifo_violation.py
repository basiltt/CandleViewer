"""#90 reroute: an external send made DURING a macrostep lands on the INTERNAL
queue, which drains before the external inbox. Does it overtake events queued
earlier while the machine was idle?"""
import sys, asyncio
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
def run(src):
    sys.path.insert(0,src)
    for m in list(sys.modules):
        if m.startswith("xstate_statemachine"): del sys.modules[m]
    from xstate_statemachine import create_machine, MachineLogic, Interpreter
    order=[]
    async def slow(i,c,e,a): await asyncio.sleep(0.3)
    def note(i,c,e,a): order.append(e.type)
    CFG={"id":"m","initial":"a","states":{"a":{"on":{
      "SLOW":{"actions":["slow"]},"EARLY":{"actions":["note"]},"LATE":{"actions":["note"]}}}}}
    async def main():
        i=Interpreter(create_machine(CFG, logic=MachineLogic(actions={"slow":slow,"note":note})))
        await i.start()
        await i.send("EARLY")     # queued while IDLE -> external inbox
        await i.send("SLOW")      # occupies the loop
        await asyncio.sleep(0.15)
        await i.send("LATE")      # sent DURING the SLOW macrostep -> internal queue
        await asyncio.sleep(1.0)
        print(f"  {src.split('/')[2] if src.startswith('/tmp') else 'HEAD':7s} order = {order}")
        await i.stop()
    asyncio.run(main())
    sys.path.pop(0)
print("expected FIFO: ['EARLY','LATE']")
run("/tmp/lib3c/src")
run("C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
