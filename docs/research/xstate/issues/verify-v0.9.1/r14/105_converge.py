"""Standalone: external burst during slow macrostep; poll to convergence (no fixed sleep)."""
import asyncio, sys, time
from xstate_statemachine import create_machine, MachineLogic, Interpreter
async def main(burst=3000):
    cfg={"id":"m","initial":"a","context":{"n":0},"maxIterations":10,
         "states":{"a":{"on":{"SLOW":{"actions":["slow"]},"T":{"actions":["inc"]}}}}}
    def inc(i,c,e,a): c["n"]+=1
    async def slow(i,c,e,a): await asyncio.sleep(0.3)
    it=await Interpreter(create_machine(cfg,logic=MachineLogic(actions={"inc":inc,"slow":slow}))).start()
    t=asyncio.ensure_future(it.send("SLOW")); await asyncio.sleep(0.03)
    for _ in range(burst): await it.send("T")
    await t
    dl=time.monotonic()+20; seen=[]
    while time.monotonic()<dl:
        seen.append(it.context["n"])
        if it.context["n"]>=burst: break
        await asyncio.sleep(0.05)
    n=it.context["n"]; await it.stop()
    print(f"burst={burst} applied={n} polls={len(seen)} first_read={seen[0]}")
    return n==burst
sys.exit(0 if asyncio.run(main()) else 1)
