import logging, copy, threading
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, SyncInterpreter, MachineLogic
import xstate_statemachine.sync_interpreter as SI

NESTED = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}

def logic():
    return MachineLogic(services={"svc_ok": lambda i,c,e: {"ok":1}})

it = SyncInterpreter(create_machine(copy.deepcopy(NESTED), logic=logic()))
it.machine.max_iterations = 20

# instrument: record (queued_before, queued_after) per macrostep
trace=[]
orig = it._process_event
def patched(ev):
    qb = len(it._internal_queue)+len(it._event_queue)
    r = orig(ev)
    trace.append((ev.type, qb, len(it._internal_queue)+len(it._event_queue)))
    return r
it._process_event = patched
th=threading.Thread(target=lambda: it.start(), daemon=True); th.start(); th.join(3)
print("alive:", th.is_alive(), "steps:", len(trace))
for t in trace[:12]: print("  ", t)
print("  ...")
for t in trace[-4:]: print("  ", t)

# any dropped-event hook fire?
from xstate_statemachine import PluginBase
class P(PluginBase):
    def __init__(self): self.drops=0; self.errs=[]
    def on_event_dropped(self, i, e, reason=None, **k): self.drops+=1
p=P()
it2 = SyncInterpreter(create_machine(copy.deepcopy(NESTED), logic=logic()))
it2.machine.max_iterations = 20
it2.use(p)
th2=threading.Thread(target=lambda: it2.start(), daemon=True); th2.start(); th2.join(3)
print("2nd: alive:",th2.is_alive(),"drops:",p.drops,"last_transition_ok:",getattr(it2,'last_transition_ok',None),"last_error:",getattr(it2,'last_error',None))
