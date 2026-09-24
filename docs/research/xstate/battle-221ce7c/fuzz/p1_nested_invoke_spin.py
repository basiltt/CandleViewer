"""P1 -- is the nested-invoke onDone->ancestor cycle bounded on async @221ce7c?
Sync settles (RunawayChainError). Does async ever trip, or spin for ever?"""
import asyncio, copy, logging, time, warnings, collections
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
import xstate_statemachine.base_interpreter as bi
from xstate_statemachine import Interpreter, SyncInterpreter, create_machine
from gen_config import make_logic
import psutil

C = collections.Counter(); _o = bi.BaseInterpreter._process_event
async def _p(self, e):
    C[e.type] += 1; return await _o(self, e)
bi.BaseInterpreter._process_event = _p

def cfg(mi=None):
    c = {"id":"m","initial":"a","states":{"a":{"initial":"a",
      "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
      "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}
    if mi is not None: c["maxIterations"] = mi
    return c

async def run_async(mi, secs):
    C.clear(); p = psutil.Process()
    i = Interpreter(create_machine(cfg(mi), logic=make_logic(sync=False)))
    try:
        await asyncio.wait_for(i.start(), 15)
    except asyncio.TimeoutError:
        print(f"  async mi={mi}: start() TIMEOUT>15s"); return
    c0 = p.cpu_times().user; await asyncio.sleep(secs); c1 = p.cpu_times().user
    err = type(i.last_error).__name__ if getattr(i,"last_error",None) else None
    print(f"  async mi={mi!s:>5}: events={sum(C.values()):>7} cpu={c1-c0:.2f}s/{secs}s "
          f"status={i.status} last_error={err} states={sorted(i.current_state_ids)}")
    await i.stop()

def run_sync(mi):
    C.clear()
    i = SyncInterpreter(create_machine(cfg(mi), logic=make_logic(sync=True)))
    t = time.time(); i.start(); d = time.time()-t
    err = type(i.last_error).__name__ if getattr(i,"last_error",None) else None
    print(f"  sync  mi={mi!s:>5}: start() {d:.2f}s events={sum(C.values())} "
          f"last_error={err} states={sorted(i.current_state_ids)}")
    i.stop()

async def main():
    print("== nested invoke onDone->ancestor, no external events ==")
    for mi in (None, 10, 1000):
        run_sync(mi)
    for mi in (None, 10, 1000):
        await run_async(mi, 5)
asyncio.run(main())
