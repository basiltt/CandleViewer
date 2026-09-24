import sys, asyncio, os
SRC = sys.argv[1]
sys.path.insert(0, SRC)
from xstate_statemachine import create_machine, MachineLogic, Interpreter
async def main():
    cnt={"n":0}
    async def slow(i,c,e,a): await asyncio.sleep(0.4)
    def bump(i,c,e,a): cnt["n"]+=1
    CFG={"id":"m","maxIterations":5,"initial":"a","states":{"a":{"on":{
      "SLOW":{"actions":["slow"]},"W":{"actions":["bump"]}}}}}
    i=Interpreter(create_machine(CFG, logic=MachineLogic(actions={"slow":slow,"bump":bump})))
    await i.start(); await i.send("SLOW"); await asyncio.sleep(0.05)
    for _ in range(50): await i.send("W")
    await asyncio.sleep(1.5)
    print(f"{os.path.basename(os.path.dirname(SRC)) or SRC}: delivered {cnt['n']}/50  LOST={50-cnt['n']}")
    await i.stop()
asyncio.run(main())
