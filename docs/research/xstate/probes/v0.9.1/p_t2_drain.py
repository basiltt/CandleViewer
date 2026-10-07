"""T-2 probe: drain_pending() without stop(): receipt error type and whether the machine keeps running."""
import asyncio, os
from xstate_statemachine import create_machine, Interpreter, MachineLogic
os.chdir("<home>")
CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"GO": "a"}}}}
async def main():
    it = Interpreter(create_machine(CFG, logic=MachineLogic())); await it.start()
    it.send_priority("GO") if hasattr(it, "send_priority") else None
    r = it.send("GO", wait=True)
    d = await it.drain_pending()
    print("drained:", [e.type for e in d], "status:", it.status)
    try: v = await asyncio.wait_for(r, 5); print("receipt resolved ->", repr(v))
    except Exception as e: print("receipt error:", type(e).__name__, "|", e)
    await it.send("GO"); await asyncio.sleep(0.1)
    print("after drain, still processes:", sorted(it.current_state_ids), it.status)
    await it.stop()
asyncio.run(asyncio.wait_for(main(), 30))
