"""K-5b: does internal=True from a foreign thread grow memory unbounded?"""
import asyncio, threading
from xstate_statemachine import Interpreter, MachineLogic, OverflowPolicy, create_machine
CFG={"id":"b","initial":"a","states":{"a":{"on":{"STALL":{"actions":["stall"]},"X":"a"}}}}
async def main():
    gate=threading.Event()
    async def stall(i,c,e,a):
        await asyncio.get_running_loop().run_in_executor(None, gate.wait)
    m=create_machine(CFG, logic=MachineLogic(actions={"stall":stall}))
    i=Interpreter(m, max_queue_size=2, overflow_policy=OverflowPolicy.RAISE)
    await i.start(); await i.send("STALL"); await asyncio.sleep(0.1)
    N=200000
    def prod():
        for _ in range(N): i.send_threadsafe("X", internal=True)
    t=threading.Thread(target=prod); t.start()
    await asyncio.get_running_loop().run_in_executor(None, t.join)
    await asyncio.sleep(0.2)
    print(f"queued {N} internal=True sends behind a stalled loop; "
          f"in_flight={i._threadsafe_self_sends_in_flight} "
          f"loop callbacks pending (no refusal raised)")
    import sys
    print(f"inbox qsize={i._event_queue.qsize()} (bounded at 2)")
    gate.set(); await asyncio.sleep(1.0)
    print(f"after release: status={i.status} err={type(i.error).__name__ if i.error else None} "
          f"internal_q={len(i._internal_queue)} raise_depth={i._raise_depth}")
    await i.stop()
asyncio.run(main())
