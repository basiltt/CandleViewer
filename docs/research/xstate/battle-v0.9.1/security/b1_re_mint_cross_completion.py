"""Round question: can events.re_mint() forge a DIFFERENT completion?
Take a legitimately engine-minted event (after-timer / done of svc 'a'), re_mint
type->done.invoke.victim, send it while 'victim' is still running. STANDALONE."""
import asyncio, time
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter
from xstate_statemachine.events import re_mint, is_system_event
captured = []
class Cap:
    def __getattr__(self, n):
        def h(*a, **k):
            for x in a:
                if is_system_event(x): captured.append(x)
        return h
cfg = {"id": "m", "type": "parallel", "states": {
  "A": {"initial": "run", "states": {"run": {"invoke": {"id": "a", "src": "fast", "onDone": "ok"}}, "ok": {}}},
  "V": {"initial": "run", "states": {"run": {"invoke": {"id": "victim", "src": "slow", "onDone": "paid"}}, "paid": {}}}}}
async def fast(i, c, e): return 1
async def slow(i, c, e): await asyncio.sleep(30); return 2
def sfast(i, c, e): return 1
def sslow(i, c, e): time.sleep(0); return None  # sync never completes differently; see below
async def run_async():
    captured.clear()
    m = create_machine(cfg, logic=MachineLogic(services={"fast": fast, "slow": slow}))
    it = Interpreter(m); it.use(Cap()); await it.start()
    for _ in range(100):
        if any(getattr(x,"type","").startswith("done.invoke.a") for x in captured): break
        await asyncio.sleep(0.01)
    src = next(x for x in captured if x.type.startswith("done.invoke.a"))
    forged = re_mint(src, type="done.invoke.victim", src="victim") if hasattr(src,"src") else re_mint(src, type="done.invoke.victim")
    print("async src:", type(src).__name__, src.type, "forged sys:", is_system_event(forged), forged)
    await it.send(forged)
    for _ in range(50):
        await asyncio.sleep(0.01)
    print("async state:", sorted(it.current_state_ids))
    print("ASYNC FORGERY FIRES victim onDone:", "m.V.paid" in it.current_state_ids)
    await it.stop()
asyncio.run(run_async())
