import sys, gc
from xstate_statemachine import create_machine, SyncInterpreter
from xstate_statemachine.models import Event

cfg = {
  "id": "m", "initial": "a", "onUnhandled": "defer",
  "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"BACK": "a"}}},
}
m = create_machine(cfg)
i = SyncInterpreter(m).start()

# 1. growth under fire-and-forget (documented default usage)
N = 3000
for k in range(N):
    i.send("NOPE")          # unhandled -> deferred, wait=False
print("deferred_events buffer:", i.deferred_count, "(DEFER_MAX", i.DEFER_MAX, ")")
print("_deferred_this_step size:", len(i._deferred_this_step))

# 2. false positive: does an id get reused and mis-report deferred=True?
i2 = SyncInterpreter(create_machine(cfg)).start()
fp = 0
tries = 0
for k in range(3000):
    e = Event(type="NOPE")          # unhandled -> id recorded, never discarded
    i2.send(e)
    del e
    gc.collect() if k % 500 == 0 else None
    e2 = Event(type="GO")           # HANDLED event
    r = i2.send(e2, wait=True)
    tries += 1
    if r.deferred:
        fp += 1
        if fp == 1:
            print("FIRST FALSE POSITIVE at k=", k, "changed=", r.changed, "state=", r.state_ids)
    i2.send("BACK")
    del e2
print("handled-event receipts:", tries, "false deferred=True:", fp)
print("_deferred_this_step size i2:", len(i2._deferred_this_step))
print("approx bytes:", sys.getsizeof(i2._deferred_this_step))
