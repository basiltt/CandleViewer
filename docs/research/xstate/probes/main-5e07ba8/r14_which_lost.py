import sys, asyncio
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
seen=[]
async def slow(i,c,e,a): await asyncio.sleep(0.4)
def bump(i,c,e,a): seen.append(e.payload.get("n"))
CFG={"id":"m","maxIterations":5,"initial":"a","states":{"a":{"on":{
  "SLOW":{"actions":["slow"]},"W":{"actions":["bump"]}}}}}
async def main():
    i=Interpreter(create_machine(CFG, logic=MachineLogic(actions={"slow":slow,"bump":bump})))
    await i.start()
    await i.send("SLOW"); await asyncio.sleep(0.05)
    recs=[i.send("W", n=k, wait=True) for k in range(12)]
    await asyncio.sleep(1.5)
    print("delivered ns:", seen)
    print("MISSING     :", [k for k in range(12) if k not in seen])
    for k,r in enumerate(recs):
        try:
            rr=await asyncio.wait_for(r, timeout=0.5)
            if k not in seen: print(f"  n={k} LOST but receipt says:", rr)
        except asyncio.TimeoutError: print(f"  n={k} receipt NEVER RESOLVED")
        except Exception as ex: print(f"  n={k} receipt raised: {type(ex).__name__}: {ex}")
    await i.stop()
asyncio.run(main())
