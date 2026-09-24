"""N1: does the F1 A4 'start() never settles' case actually hang in wall clock?"""
import json, logging, threading, time, sys
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, SyncInterpreter, Interpreter
from gen_config import make_logic

cfg = json.load(open("a4.json"))
m = create_machine(cfg, logic=make_logic(sync=True))
interp = SyncInterpreter(m)
res = {}
def run():
    t0=time.time()
    try:
        interp.start(); res["ok"]=True
    except BaseException as e:
        res["exc"]=f"{type(e).__name__}: {e}"
    res["dt"]=time.time()-t0
th=threading.Thread(target=run, daemon=True); th.start(); th.join(20)
print("alive after 20s:", th.is_alive(), res)
if th.is_alive():
    try: print("inbox:", interp._event_queue.qsize() if hasattr(interp,'_event_queue') else len(getattr(interp,'_inbox',[])))
    except Exception as e: print("inbox?", e)
else:
    print("status:", interp.status, "value:", interp.current_state_ids if hasattr(interp,'current_state_ids') else None)
    print("last_transition_ok:", getattr(interp,'last_transition_ok',None), "last_error:", getattr(interp,'last_error',None))
