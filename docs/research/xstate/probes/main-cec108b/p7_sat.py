import asyncio, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine

def slow(i,c,e):
    time.sleep(0.2); return 1

async def run(n):
    cfg={"id":"sat","type":"parallel","states":{f"r{k}":{"initial":"s","states":{
        "s":{"invoke":{"src":"slow","onDone":"d"}},"d":{"type":"final"}}} for k in range(n)}}
    m=create_machine(cfg, logic=MachineLogic(services={"slow":slow}))
    i=Interpreter(m); t0=time.monotonic(); await i.start()
    done=lambda: sum(1 for s in i.current_state_ids if s.endswith(".d"))
    while done()<n and time.monotonic()-t0<15:
        await asyncio.sleep(0.005)
    print(f"n={n}: all-done in {(time.monotonic()-t0):.2f}s (ideal 0.20)")
    await i.stop()

async def main():
    for n in (1,2,4,5,8,12):
        await run(n)
asyncio.run(main())
