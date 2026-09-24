"""N9 -- scope of the D5-fuzz-1 sync livelock: which shapes trigger it, does the
async engine share it, and does ANY maxIterations bound it?"""
import asyncio, copy, logging, threading, time, warnings, collections
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
import xstate_statemachine.base_interpreter as bi
from xstate_statemachine import SyncInterpreter, Interpreter, create_machine
from gen_config import make_logic

C = collections.Counter()
_orig = bi.BaseInterpreter._process_event
async def _patched(self, event):
    C[event.type] += 1
    return await _orig(self, event)
bi.BaseInterpreter._process_event = _patched

NEST = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}

def sync_probe(label, cfg, secs=5):
    C.clear()
    it = SyncInterpreter(create_machine(copy.deepcopy(cfg), logic=make_logic(sync=True)))
    th = threading.Thread(target=it.start, daemon=True); th.start(); th.join(secs)
    alive = th.is_alive()
    print(f"  {label:44} hang={alive} events_processed={sum(C.values())} "
          f"inbox={len(getattr(it,'_event_queue',[]))} internal={len(getattr(it,'_internal_queue',[]))}")
    return alive

print("sync engine, varying maxIterations:")
for mi in (None, 2, 10, 1000, 100000):
    c = copy.deepcopy(NEST)
    if mi: c["maxIterations"] = mi
    sync_probe(f"maxIterations={mi}", c)

print("shape ablation (sync):")
sync_probe("outer invoke only", {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},"states":{"a":{}}}}})
sync_probe("inner invoke only", {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}})
sync_probe("both, inner onDone -> own state", {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a.a"}}}}}}})
sync_probe("3-deep nest, all onDone -> #m.a", {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{"initial":"a","invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}},
    "states":{"a":{"invoke":{"id":"i3","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}}})

print("async engine, same shape:")
async def amain():
    C.clear()
    i = Interpreter(create_machine(copy.deepcopy(NEST), logic=make_logic(sync=False)))
    try:
        await asyncio.wait_for(i.start(), 5)
    except asyncio.TimeoutError:
        print("  async start() TIMED OUT"); return
    await asyncio.sleep(3)
    print(f"  async settled: states={sorted(i.current_state_ids)} status={i.status} "
          f"events_processed={sum(C.values())}")
    await i.stop()
try: asyncio.run(asyncio.wait_for(amain(), 25))
except BaseException as e: print("  async:", type(e).__name__, e)
