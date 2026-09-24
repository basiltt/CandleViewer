"""N1c: candidate shapes for the surviving sync start() hang."""
import logging, threading, time, copy, json
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, SyncInterpreter
from gen_config import make_logic

def probe(name, cfg, secs=6):
    try:
        m = create_machine(copy.deepcopy(cfg), logic=make_logic(sync=True))
    except BaseException as e:
        print(f"{name}: BUILD {type(e).__name__}"); return None
    it = SyncInterpreter(m); out={}
    def run():
        try: it.start(); out["ok"]=it.current_state_ids
        except BaseException as e: out["exc"]=f"{type(e).__name__}"
    th=threading.Thread(target=run,daemon=True); th.start(); th.join(secs)
    print(f"{name}: hang={th.is_alive()} inbox={len(getattr(it,'_event_queue',[]))} {out}")
    return th.is_alive()

NESTED = {"id":"m","initial":"a","states":{"a":{"initial":"a","invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}
probe("nested-2-invokes-both-onDone-#m.a", NESTED)

ONE_OUTER = {"id":"m","initial":"a","states":{"a":{"initial":"a","invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{}}}}}
probe("outer-only", ONE_OUTER)

ONE_INNER = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}
probe("inner-only(child onDone->parent)", ONE_INNER)
