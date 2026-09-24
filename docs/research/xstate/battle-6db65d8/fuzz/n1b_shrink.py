"""N1b: minimal shape for the surviving sync start() non-termination."""
import logging, threading, time, tracemalloc
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, SyncInterpreter
from gen_config import make_logic

MIN = {
  "id": "m", "initial": "a",
  "states": {
    "a": {
      "initial": "a1",
      "invoke": {"id": "inv", "src": "svc_ok", "onDone": {"target": "#m.a"}},
      "states": {"a1": {}}
    }
  },
}
m = create_machine(MIN, logic=make_logic(sync=True))
it = SyncInterpreter(m)
def run():
    try: it.start()
    except BaseException as e: print("raised", type(e).__name__, e)
th=threading.Thread(target=run, daemon=True); th.start()
for t in (3,8,15):
    th.join(t - (t-3 if t==3 else 0)) if False else th.join(3 if t==3 else 5 if t==8 else 7)
    print(f"t={t}s alive={th.is_alive()} inbox={len(getattr(it,'_event_queue',[]))}")
