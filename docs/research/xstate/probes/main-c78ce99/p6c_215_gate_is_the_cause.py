import asyncio, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine
CFG={"id":"dead","initial":"x","context":{"n":0},
     "states":{"x":{"entry":["selfwait"],"on":{"GO":"y"}},"y":{}}}
class PreSet(asyncio.Event):
    """An already-set Event: the #215 gate is a no-op (pre-#215 behaviour)."""
class NoGate(Interpreter):
    def _spawn_run_loop(self):
        if self._descent_done is not None:
            self._descent_done.set()   # open the gate before the loop starts
        return super()._spawn_run_loop()
async def main():
    async def selfwait(i,c,e,a):
        try:
            await asyncio.wait_for(i.send("GO", wait=True), 3.0); c["n"]+=1
        except asyncio.TimeoutError: c["n"]=-1
    m=create_machine(CFG, logic=MachineLogic(actions={"selfwait":selfwait}))
    i=NoGate(m); t0=time.perf_counter(); await i.start()
    print(f"gate pre-opened: start() took {time.perf_counter()-t0:.2f}s n={i.context['n']} states={sorted(i.current_state_ids)}")
    await i.stop()
asyncio.run(main())
