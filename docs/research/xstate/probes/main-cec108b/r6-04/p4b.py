"""Corrected usage: does internal=True grant anything the DOCUMENTED honest
path (contextvars-inheriting thread issuing a self-send) does not?"""
import asyncio, contextvars, threading
from xstate_statemachine import Interpreter, MachineLogic, OverflowPolicy, create_machine
from xstate_statemachine.exceptions import QueueOverflowError

CFG={"id":"b","initial":"a","states":{"a":{"on":{"STALL":{"actions":["stall"]},"X":"a"}}}}

async def main():
    gate=threading.Event(); res={}
    async def stall(i,c,e,a):
        ctx=contextvars.copy_context()
        ok=ref=0
        def prod():
            nonlocal ok,ref
            for _ in range(500):
                try: i.send_threadsafe("X"); ok+=1
                except QueueOverflowError: ref+=1
        t=threading.Thread(target=lambda: ctx.run(prod)); t.start()
        await asyncio.get_running_loop().run_in_executor(None,t.join)
        res["honest_ctx"]=(ok,ref)
    m=create_machine(CFG,logic=MachineLogic(actions={"stall":stall}))
    i=Interpreter(m,max_queue_size=2,overflow_policy=OverflowPolicy.RAISE)
    await i.start(); await i.send("STALL"); await asyncio.sleep(0.6)
    print("honest contextvars-inherited thread (no flag):",res)
    await asyncio.sleep(0.3)
    print("status",i.status,"internal_q",len(i._internal_queue),"raise_depth",i._raise_depth,"last_ok",i.last_transition_ok)
    await i.stop()

asyncio.run(main())
