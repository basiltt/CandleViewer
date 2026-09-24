import logging, threading, time, copy, collections
logging.disable(logging.CRITICAL)
import xstate_statemachine.base_interpreter as bi
from xstate_statemachine import create_machine, SyncInterpreter
from gen_config import make_logic
C=collections.Counter()
orig=bi.BaseInterpreter._process_event
async def patched(self, event):
    C[event.type]+=1
    return await orig(self, event)
bi.BaseInterpreter._process_event=patched
CFG = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}
it = SyncInterpreter(create_machine(copy.deepcopy(CFG), logic=make_logic(sync=True)))
th=threading.Thread(target=it.start, daemon=True); th.start()
for _ in range(3):
    time.sleep(2); print(dict(C), "inbox", len(it._event_queue), "internal", len(it._internal_queue))
