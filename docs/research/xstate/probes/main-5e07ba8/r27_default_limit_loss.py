"""Default maxIterations=1000: external sends issued while ONE macrostep is
in flight. This is ordinary production shape -- a handler doing I/O while a
producer keeps sending."""
import sys, asyncio
sys.path.insert(0,"<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
async def run(n):
    got=set(); dropped=[]
    async def slow(i,c,e,a): await asyncio.sleep(0.5)    # one slow handler: a DB call
    def bump(i,c,e,a): got.add(e.payload["n"])
    CFG={"id":"m","initial":"a","states":{"a":{"on":{
      "SLOW":{"actions":["slow"]},"W":{"actions":["bump"]}}}}}   # default maxIterations=1000
    i=Interpreter(create_machine(CFG, logic=MachineLogic(actions={"slow":slow,"bump":bump})))
    await i.start(); await i.send("SLOW"); await asyncio.sleep(0.05)
    for k in range(n): await i.send("W", n=k)
    await asyncio.sleep(3.0)
    lost=sorted(set(range(n))-got)
    print(f"  burst={n:5d} delivered={len(got):5d} LOST={len(lost):4d}  lost ns: {lost[:6]}{'...' if len(lost)>6 else ''}")
    await i.stop()
async def main():
    print("default maxIterations=1000, external burst during one 0.5s macrostep:")
    for n in [500, 1000, 1500, 3000]:
        await run(n)
asyncio.run(main())
