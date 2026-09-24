"""Q1 -- MINIMAL repro: an invoke cycle whose service is an `async def` is
NEVER charged to the async chain budget. maxIterations is ignored; the loop
spins for ever at ~7k laps/s with last_error=None. The SAME chart with a
plain-`def` service trips RunawayChainError at the limit, and SyncInterpreter
trips too. Root cause: interpreter.py:_deliver_priority charges the budget only
`if self._processing`; an async-def service resolves on its own task AFTER the
entering macrostep has ended, so every lap arrives 'free'."""
import asyncio, logging, warnings, collections
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
import xstate_statemachine.base_interpreter as bi
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine

C = collections.Counter(); _o = bi.BaseInterpreter._process_event
async def _p(self, e):
    C[e.type] += 1; return await _o(self, e)
bi.BaseInterpreter._process_event = _p

CFG = {  # 5 lines: two states, each invokes a service whose onDone enters the other
    "id": "m", "initial": "a", "maxIterations": 20,
    "states": {
        "a": {"invoke": {"id": "i1", "src": "svc", "onDone": {"target": "#m.b"}}},
        "b": {"invoke": {"id": "i2", "src": "svc", "onDone": {"target": "#m.a"}}},
    },
}

async def async_svc(i, c, e): return {"ok": 1}
def plain_svc(i, c, e): return {"ok": 1}

async def run(kind, secs=5):
    C.clear()
    svc = async_svc if kind == "async def" else plain_svc
    it = Interpreter(create_machine(dict(CFG), logic=MachineLogic(services={"svc": svc})))
    await asyncio.wait_for(it.start(), 10)
    await asyncio.sleep(secs)
    err = type(it.last_error).__name__ if getattr(it, "last_error", None) else None
    n = sum(C.values())
    print(f"  async engine, {kind:<10} svc: laps={n:>7} in {secs}s  "
          f"last_error={err}  ok={it.last_transition_ok}  "
          f"=> {'RUNAWAY (budget never charged)' if err is None and n > 1000 else 'bounded'}")
    await it.stop()

def run_sync():
    C.clear()
    it = SyncInterpreter(create_machine(dict(CFG), logic=MachineLogic(services={"svc": plain_svc})))
    it.start()
    err = type(it.last_error).__name__ if getattr(it, "last_error", None) else None
    print(f"  sync  engine, plain      svc: laps={sum(C.values()):>7}         last_error={err}")
    it.stop()

async def main():
    print("== maxIterations=20, invoke ping-pong a<->b ==")
    run_sync()
    await run("plain def")
    await run("async def")
asyncio.run(main())
