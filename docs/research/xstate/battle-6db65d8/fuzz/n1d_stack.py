import logging, threading, time, sys, faulthandler, copy
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, SyncInterpreter
from gen_config import make_logic
CFG = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}
it = SyncInterpreter(create_machine(copy.deepcopy(CFG), logic=make_logic(sync=True)))
th=threading.Thread(target=lambda: it.start(), daemon=True); th.start(); time.sleep(4)
import traceback
frame = sys._current_frames()[th.ident]
traceback.print_stack(frame, limit=14)
