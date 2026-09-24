"""P3 -- mechanism + blast radius for the async unbounded invoke cycle.
Variants: async-def service, plain-def (executor) service, single (non-nested)
invoke, always-driven re-arm. Watchdog 12s each; trip = last_error set."""
import asyncio, logging, warnings, time
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
import xstate_statemachine.base_interpreter as bi
import collections
C = collections.Counter(); _o = bi.BaseInterpreter._process_event
async def _p(self, e):
    C[e.type] += 1; return await _o(self, e)
bi.BaseInterpreter._process_event = _p

def logic(kind):
    if kind == "async":
        async def svc(i, c, e): return {"ok": 1}
    else:
        def svc(i, c, e): return {"ok": 1}
    return MachineLogic(services={"svc": svc}, guards={"g": lambda c, e: True})

NESTED = {"id":"m","initial":"a","maxIterations":20,"states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc","onDone":{"target":"#m.a"}},
  "states":{"a":{"invoke":{"id":"i2","src":"svc","onDone":{"target":"#m.a"}}}}}}}
SINGLE = {"id":"m","initial":"a","maxIterations":20,"states":{"a":{
  "invoke":{"id":"i1","src":"svc","onDone":{"target":"#m.a"}}}}}
PINGPONG = {"id":"m","initial":"a","maxIterations":20,"states":{
  "a":{"invoke":{"id":"i1","src":"svc","onDone":{"target":"#m.b"}}},
  "b":{"invoke":{"id":"i2","src":"svc","onDone":{"target":"#m.a"}}}}}

async def probe(name, cfg, kind, secs=6):
    C.clear()
    i = Interpreter(create_machine(dict(cfg), logic=logic(kind)))
    try: await asyncio.wait_for(i.start(), 12)
    except asyncio.TimeoutError:
        print(f"  {name:<28} {kind:<6} start() TIMEOUT"); return
    await asyncio.sleep(secs)
    err = type(i.last_error).__name__ if getattr(i,"last_error",None) else None
    n = sum(C.values())
    print(f"  {name:<28} {kind:<6} laps={n:>7} in {secs}s  trip={err}  "
          f"{'RUNAWAY' if err is None and n > 5000 else 'bounded'}")
    await i.stop()

def probe_sync(name, cfg):
    C.clear()
    i = SyncInterpreter(create_machine(dict(cfg), logic=logic("plain")))
    t = time.time(); i.start(); d = time.time()-t
    err = type(i.last_error).__name__ if getattr(i,"last_error",None) else None
    print(f"  {name:<28} SYNC   laps={sum(C.values()):>7} in {d:.2f}s  trip={err}")
    i.stop()

async def main():
    for nm, cfg in (("nested-invoke-onDone-anc", NESTED), ("single-invoke-self-onDone", SINGLE),
                    ("invoke-pingpong a<->b", PINGPONG)):
        probe_sync(nm, cfg)
        for kind in ("async", "plain"):
            await probe(nm, cfg, kind)
asyncio.run(main())
