import logging, copy, asyncio, time, threading
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, SyncInterpreter
from gen_config import make_logic
import psutil

NESTED = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}
SINGLE_COMPOUND = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{}}}}}

# count service invocations to see if it's really unbounded re-entry
def counting_logic(counter, sync=True):
    from xstate_statemachine import MachineLogic
    def svc_ok(i, ctx, e):
        counter[0]+=1
        return {"ok":1}
    async def asvc_ok(i, ctx, e):
        counter[0]+=1
        return {"ok":1}
    return MachineLogic(services={"svc_ok": svc_ok if sync else asvc_ok})

print("=== SYNC invocation counts over 4s ===")
for name,cfg in (("single_compound",SINGLE_COMPOUND),("nested",NESTED)):
    c=[0]
    it=SyncInterpreter(create_machine(copy.deepcopy(cfg), logic=counting_logic(c,True)))
    th=threading.Thread(target=lambda: it.start(), daemon=True); th.start(); th.join(4)
    print(f"  {name:<18} alive={th.is_alive()} invocations={c[0]}")

print("=== ASYNC: is it progressing or idle? ===")
async def amain():
    c=[0]
    it=Interpreter(create_machine(copy.deepcopy(NESTED), logic=counting_logic(c,False)))
    p=psutil.Process(); p.cpu_percent()
    await asyncio.wait_for(it.start(), 10)
    t0=time.time(); c0=c[0]
    await asyncio.sleep(3)
    print(f"  after start: state={sorted(it.current_state_ids)} status={it.status}")
    print(f"  invocations in 3s idle window: {c[0]-c0} (total {c[0]}) cpu={p.cpu_percent():.0f}%")
    # can the caller still interact?
    t1=time.time()
    try:
        await asyncio.wait_for(it.stop(), 5); print(f"  stop() ok in {time.time()-t1:.2f}s")
    except asyncio.TimeoutError: print("  stop() TIMED OUT")
asyncio.run(amain())
