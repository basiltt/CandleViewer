"""How much traffic does the #90 reroute lose over a sustained run?
Realistic shape: every event does a little async work (an await), and a
producer keeps sending. Default maxIterations=1000."""
import sys, asyncio
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
async def main():
    got=[]
    async def handle(i,c,e,a):
        await asyncio.sleep(0)          # any await -> _processing is True for others
        got.append(e.payload["n"])
    CFG={"id":"m","maxIterations":1000,"initial":"a","states":{"a":{"on":{"W":{"actions":["h"]}}}}}
    i=Interpreter(create_machine(CFG, logic=MachineLogic(actions={"h":handle})))
    await i.start()
    N=5000
    async def producer():
        for n in range(N):
            await i.send("W", n=n)
    await producer(); await asyncio.sleep(3.0)
    lost=[n for n in range(N) if n not in set(got)]
    print(f"sent={N} delivered={len(got)} LOST={len(lost)}")
    print("first lost ns:", lost[:10])
    print("last_error:", type(i.last_error).__name__ if i.last_error else None)
    await i.stop()
asyncio.run(main())
