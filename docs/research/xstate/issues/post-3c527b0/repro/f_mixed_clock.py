import asyncio, time, logging; logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, SyncInterpreter
from xstate_statemachine.clock import RealClock
cfg={"id":"m","initial":"a","states":{"a":{"after":{20:{"target":"b"}}},"b":{"type":"final"}}}
async def main():
    c=RealClock()
    s=SyncInterpreter(create_machine(cfg), clock=c).start()
    a=await Interpreter(create_machine(cfg), clock=c).start()
    await asyncio.sleep(0.15); s.tick()
    print("sync:", s.current_state_ids, "async:", a.current_state_ids)
    await a.stop()
asyncio.run(main())
