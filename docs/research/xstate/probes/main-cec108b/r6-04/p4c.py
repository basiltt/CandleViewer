"""internal=False self-retrigger loop: does it starve the asyncio loop
(the harm maxIterations exists to prevent), or is it merely unbounded-but-fair?"""
import asyncio, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine
CFG={"id":"b","initial":"a","max_iterations":20,
     "states":{"a":{"on":{"GO":{"actions":["again"]}}}}}
async def main():
    hits=0; beats=0
    async def again(i,c,e,a):
        nonlocal hits
        hits+=1
        if hits<400: i.send_threadsafe("GO", internal=False)
    async def hb():
        nonlocal beats
        while True:
            await asyncio.sleep(0.01); beats+=1
    m=create_machine(CFG,logic=MachineLogic(actions={"again":again}))
    i=Interpreter(m); await i.start()
    t=asyncio.create_task(hb())
    await i.send("GO"); await asyncio.sleep(1.0)
    t.cancel()
    print(f"hits={hits} heartbeats_in_1s={beats} status={i.status} last_ok={i.last_transition_ok}")
    await i.stop()
asyncio.run(main())
