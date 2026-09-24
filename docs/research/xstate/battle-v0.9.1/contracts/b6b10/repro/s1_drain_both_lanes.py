import asyncio
from xstate_statemachine import Interpreter, create_machine, MachineLogic
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import InterpreterStoppedError
M={"id":"m","initial":"a","states":{"a":{"on":{"X":"b"}},"b":{"on":{"Y":"a"}}}}
async def main():
    i=Interpreter(create_machine(M),clock=SimulatedClock()); await i.start()
    a1=i.send("X",wait=False); print("after call pending",len(i.pending_events))
    a2=i.send_priority("Y",wait=False); print("after prio call",len(i.pending_events))
    a3=i.send("X",wait=True); print("after wait call",len(i.pending_events))
    d=await i.drain_pending(); print([e.type for e in d], len(i.pending_events))
    for a in (a1,a2): await a
    try: print(await asyncio.wait_for(a3,3))
    except InterpreterStoppedError as e: print("stopped-err OK")
    print(i.current_state_ids if hasattr(i,"current_state_ids") else [s.id for s in i.active_state_nodes])
    await i.stop()
asyncio.run(main())
