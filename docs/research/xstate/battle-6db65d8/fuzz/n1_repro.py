"""D5-fuzz-1 repro: nested invokes whose onDone re-enters their common parent
make SyncInterpreter.start() non-terminating; maxIterations does not bound it."""
import logging, threading, time, copy, os, sys
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, SyncInterpreter, Interpreter
from gen_config import make_logic
import asyncio, psutil

CFG = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}

def sync_probe(maxit, secs):
    cfg = copy.deepcopy(CFG)
    if maxit: cfg["maxIterations"] = maxit
    it = SyncInterpreter(create_machine(cfg, logic=make_logic(sync=True)))
    out={}
    def run():
        try: it.start(); out["ok"]=sorted(it.current_state_ids)
        except BaseException as e: out["exc"]=f"{type(e).__name__}: {e}"
    th=threading.Thread(target=run,daemon=True); th.start(); th.join(secs)
    p=psutil.Process()
    print(f"  maxIterations={maxit!r:>6} after {secs}s: start_alive={th.is_alive()} rss={p.memory_info().rss//2**20}MB {out}")
    return th.is_alive()

print("SYNC engine:")
for mi, s in ((None,6),(10,6),(1000,6)):
    sync_probe(mi, s)

print("ASYNC engine:")
async def amain():
    it = Interpreter(create_machine(copy.deepcopy(CFG), logic=make_logic(sync=False)))
    try:
        await asyncio.wait_for(it.start(), 6)
        await asyncio.sleep(3)
        print("  started; state=", sorted(it.current_state_ids), "status=", it.status)
        await it.stop()
    except asyncio.TimeoutError:
        print("  async start() TIMED OUT after 6s")
try: asyncio.run(asyncio.wait_for(amain(), 20))
except Exception as e: print("  async:", type(e).__name__, e)
