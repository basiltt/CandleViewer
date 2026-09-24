import sys
from xstate_statemachine import create_machine, SyncInterpreter
from xstate_statemachine.models import Event
cfg = {"id":"m","initial":"a","onUnhandled":"defer","states":{"a":{"on":{"GO":"b"}},"b":{}}}
# caller keeps its own references (audit log) -> ids cannot be recycled
i = SyncInterpreter(create_machine(cfg)).start()
keep=[]
for k in range(50000):
    e = Event(type="NOPE", payload={"k":k})
    keep.append(e)
    i.send(e)
print("held:", i.deferred_count, "stale-id set:", len(i._deferred_this_step),
      "bytes:", sys.getsizeof(i._deferred_this_step))
