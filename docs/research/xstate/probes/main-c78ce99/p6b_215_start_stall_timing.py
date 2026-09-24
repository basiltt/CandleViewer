import asyncio, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine
CFG={"id":"dead","initial":"x","context":{"n":0},
     "states":{"x":{"entry":["selfwait"],"on":{"GO":"y"}},"y":{}}}
async def main():
    async def selfwait(i,c,e,a):
        try:
            await asyncio.wait_for(i.send("GO", wait=True), 3.0)
            c["n"]+=1
        except asyncio.TimeoutError:
            c["n"]=-1
    m=create_machine(CFG, logic=MachineLogic(actions={"selfwait":selfwait}))
    i=Interpreter(m); t0=time.perf_counter()
    await i.start()
    print(f"start() took {time.perf_counter()-t0:.2f}s  n={i.context['n']} states={sorted(i.current_state_ids)} err={type(i.last_error).__name__ if i.last_error else None}")
    await asyncio.sleep(0.2); print("  after settle:", sorted(i.current_state_ids)); await i.stop()
asyncio.run(main())
