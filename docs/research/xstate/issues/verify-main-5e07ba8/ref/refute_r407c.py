import sys
from xstate_statemachine import create_machine, SyncInterpreter
cfg = {"id":"m","initial":"a","onUnhandled":"defer",
 "states":{"a":{"on":{"GO":"b"}},"b":{"on":{"BACK":"a"}}}}
i = SyncInterpreter(create_machine(cfg)).start()
import gc
for k in range(20000):
    i.send("NOPE")            # deferred (fire & forget)
    if k % 50 == 0:
        i.send("GO"); i.send("BACK")   # state change -> replay/drain
print("held:", i.deferred_count, "stale-id set:", len(i._deferred_this_step),
      "bytes:", sys.getsizeof(i._deferred_this_step))
