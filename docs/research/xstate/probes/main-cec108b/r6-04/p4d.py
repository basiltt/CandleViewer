import asyncio, threading, logging
from xstate_statemachine import Interpreter, MachineLogic, OverflowPolicy, create_machine
from xstate_statemachine.exceptions import QueueOverflowError
logging.basicConfig(level=logging.ERROR)
CFG={"id":"b","initial":"a","max_iterations":20,"states":{"a":{"on":{"STALL":{"actions":["stall"]},"X":{"actions":["tick"]}}}}}
async def main():
    gate=threading.Event(); ticks=0; dropped=[]
    async def stall(i,c,e,a):
        await asyncio.get_running_loop().run_in_executor(None,gate.wait)
    async def tick(i,c,e,a):
        nonlocal ticks; ticks+=1
    m=create_machine(CFG,logic=MachineLogic(actions={"stall":stall,"tick":tick}))
    i=Interpreter(m,max_queue_size=2,overflow_policy=OverflowPolicy.RAISE)
    await i.start(); await i.send("STALL"); await asyncio.sleep(0.2)
    ok=0
    def prod():
        nonlocal ok
        for _ in range(5000):
            try: i.send_threadsafe("X",internal=True); ok+=1
            except QueueOverflowError: pass
    t=threading.Thread(target=prod); t.start()
    await asyncio.get_running_loop().run_in_executor(None,t.join)
    print("accepted",ok,"internal_q_before_release",len(i._internal_queue),"raise_depth",i._raise_depth)
    gate.set(); await asyncio.sleep(1.5)
    print("ticks_executed",ticks,"internal_q",len(i._internal_queue),"raise_depth",i._raise_depth,"last_ok",i.last_transition_ok,"status",i.status)
    await i.stop()
asyncio.run(main())
