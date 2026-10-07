"""Amplified: how many INDEPENDENT external sends issued during a long
macrostep are discarded by the #90 reroute + chain budget?"""
import sys, asyncio
sys.path.insert(0,"<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
async def run(limit, n):
    cnt={"n":0}; dropped=[]
    async def slow(i,c,e,a): await asyncio.sleep(0.4)
    def bump(i,c,e,a): cnt["n"]+=1
    CFG={"id":"m","maxIterations":limit,"initial":"a","states":{"a":{"on":{
      "SLOW":{"actions":["slow"]},"W":{"actions":["bump"]}}}}}
    i=Interpreter(create_machine(CFG, logic=MachineLogic(actions={"slow":slow,"bump":bump})))
    await i.start()
    await i.send("SLOW"); await asyncio.sleep(0.05)
    for _ in range(n): await i.send("W")
    await asyncio.sleep(2.0)
    print(f"  maxIterations={limit:5d}  sent={n:5d}  delivered={cnt['n']:5d}  LOST={n-cnt['n']}")
    await i.stop()
async def main():
    print("independent external W sends issued while a macrostep is in flight:")
    for limit,n in [(20,100),(10,500),(5,1000),(1000,3000)]:
        await run(limit,n)
asyncio.run(main())
