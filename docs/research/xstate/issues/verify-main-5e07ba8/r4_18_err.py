import asyncio,gc
from xstate_statemachine import Interpreter,MachineLogic,create_machine
from xstate_statemachine.clock import SimulatedClock
CFG={"id":"m","initial":"a","context":{},"states":{"a":{"after":{"1000":"a"}}}}
clock=SimulatedClock()
async def sess1():
    it=Interpreter(create_machine(CFG,logic=MachineLogic()),clock=clock)
    await it.start(); await clock.increment(1000); await it.stop()
async def sess2():
    it=Interpreter(create_machine(CFG,logic=MachineLogic()),clock=clock)
    await it.start(); await clock.increment(1000); await it.stop()
    print("second loop OK, states:",it.current_state_ids)
asyncio.run(sess1())   # loop 1 closed; its settler still registered
gc.collect()
try:
    asyncio.run(sess2())   # settler from dead loop still walked
except Exception as e:
    print("ERROR from stale settler:",type(e).__name__,e)
print("settlers:",len(clock._settlers))
