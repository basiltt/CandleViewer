import asyncio
from xstate_statemachine import create_machine, SyncInterpreter, Interpreter
N=1500
states={}
for k in range(N+1):
    if k<N: states[f"s{k}"]={"entry":[{"type":"raise","params":{"event":"GO"}}],"on":{"GO":{"target":f"s{k+1}"}}}
    else: states[f"s{k}"]={}
cfg={"id":"m","initial":"s0","states":states}
i=SyncInterpreter(create_machine(cfg)).start()
print("SYNC landed:", i.current_state_ids)
async def main():
    a=await Interpreter(create_machine(cfg)).start()
    await asyncio.sleep(0.5)
    print("ASYNC landed:", a.current_state_ids)
    await a.stop()
asyncio.run(main())
