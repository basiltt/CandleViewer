"""Does a rerouted in-loop send() jump an EXTERNAL BACKLOG queued before it?"""
import sys, asyncio
def run(src,label):
    sys.path.insert(0,src)
    for m in list(sys.modules):
        if m.startswith("xstate_statemachine"): del sys.modules[m]
    from xstate_statemachine import create_machine, MachineLogic, Interpreter
    order=[]
    async def slow(i,c,e,a): await asyncio.sleep(0.4)
    def note(i,c,e,a): order.append(e.type+str(e.payload.get("n","")))
    CFG={"id":"m","initial":"a","states":{"a":{"on":{
      "SLOW":{"actions":["slow"]},"BACK":{"actions":["note"]},"JUMP":{"actions":["note"]}}}}}
    async def main():
        i=Interpreter(create_machine(CFG, logic=MachineLogic(actions={"slow":slow,"note":note})))
        await i.start(); await i.send("SLOW"); await asyncio.sleep(0.02)
        for n in range(5): await i.send("BACK", n=n)   # backlog, sent during macrostep
        await i.send("JUMP")
        await asyncio.sleep(1.2)
        print(f"  {label}: {order}")
        await i.stop()
    asyncio.run(main()); sys.path.pop(0)
run("/tmp/lib3c/src","3c527b0")
run("<workspace>/_ref/xstate-statemachine/src","5e07ba8")
