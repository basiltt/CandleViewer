"""#90 regression: the reroute gate is `self._processing`, an interpreter-wide
flag -- NOT "the caller is an action of this interpreter". Any other coroutine
that calls send() while the run loop is mid-macrostep is reclassified as
self-generated: it jumps the external queue AND counts against the chain budget."""
import sys, asyncio
sys.path.insert(0,"<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
seen=[]
CFG={"id":"m","maxIterations":20,"initial":"a","states":{"a":{"on":{
 "SLOW":{"actions":["slow"]},"EXT":{"actions":["note"]},"FIRST":{"actions":["note"]}}}}}
async def slow(i,c,e,a): await asyncio.sleep(0.25)   # macrostep in progress
def note(i,c,e,a): seen.append(e.type)
async def main():
    i=Interpreter(create_machine(CFG, logic=MachineLogic(actions={"slow":slow,"note":note})))
    await i.start()
    await i.send("SLOW")          # occupies the run loop for 250ms
    await asyncio.sleep(0.05)
    await i.send("FIRST")         # queued externally while SLOW runs
    await i.send("EXT")
    await asyncio.sleep(0.6)
    print("delivery order:", seen, "(FIFO expected ['FIRST','EXT'])")
    await i.stop()
asyncio.run(main())

print()
print("--- budget: independent EXTERNAL sends during a long macrostep ---")
cnt={"n":0}
def bump(i,c,e,a): cnt["n"]+=1
CFG2={"id":"m2","maxIterations":20,"initial":"a","states":{"a":{"on":{
 "SLOW":{"actions":["slow"]},"W":{"actions":["bump"]}}}}}
async def main2():
    i=Interpreter(create_machine(CFG2, logic=MachineLogic(actions={"slow":slow,"bump":bump})))
    await i.start()
    await i.send("SLOW"); await asyncio.sleep(0.05)
    for _ in range(100): await i.send("W")   # 100 INDEPENDENT external events
    await asyncio.sleep(1.5)
    print(f"external 'W' delivered: {cnt['n']} of 100 (maxIterations=20)")
    print("last_error:", type(i.last_error).__name__ if i.last_error else None)
    print("VERDICT:", "DATA LOSS - external events charged to the chain budget" if cnt["n"]<100 else "no loss")
    await i.stop()
asyncio.run(main2())
