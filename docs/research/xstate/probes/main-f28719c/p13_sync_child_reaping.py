"""P13 (STANDALONE): #196's sync-engine child reaping -- leak, double stop,
and stop during bring-up.

  A) re-entering cycle: the invoking state is entered/exited N times; the
     live thread count must not grow with N.
  B) stop() after the state already exited (double reap) must not raise.
  C) stop() called while a child is still being brought up.

Exit 1 on a leak or an exception.
"""
import json, sys, threading, time
from xstate_statemachine import create_machine, SyncInterpreter, MachineLogic

KID = {"id": "kid", "initial": "s",
       "states": {"s": {"on": {"NEVER": "e"}}, "e": {"type": "final"}}}

PARENT = {
    "id": "p",
    "initial": "idle",
    "states": {
        "idle": {"on": {"GO": "run"}},
        "run": {"invoke": {"id": "kid", "src": "kid"}, "on": {"BACK": "idle"}},
    },
}


def build():
    kid = create_machine(json.loads(json.dumps(KID)), logic=MachineLogic())
    return create_machine(json.loads(json.dumps(PARENT)),
                          logic=MachineLogic(services={"kid": kid}))


def threads():
    return threading.active_count()


bad = 0

# A) leak across laps
i = SyncInterpreter(build()).start()
base = threads()
for _ in range(15):
    i.send("GO")
    i.send("BACK")
time.sleep(0.3)
grew = threads() - base
print(f"A) threads base={base} after 15 laps delta={grew} actors={len(i._actors)}")
if grew > 2 or len(i._actors) > 0:
    bad = 1
i.stop()

# B) double stop / stop after exit
j = SyncInterpreter(build()).start()
j.send("GO")
j.send("BACK")
try:
    j.stop()
    j.stop()
    print("B) double stop: ok")
except Exception as exc:  # noqa: BLE001
    print("B) double stop RAISED:", type(exc).__name__, exc)
    bad = 1

# C) stop while the child is alive
k = SyncInterpreter(build()).start()
k.send("GO")
try:
    k.stop()
    time.sleep(0.2)
    print(f"C) stop with live child: ok; actors={len(k._actors)}")
except Exception as exc:  # noqa: BLE001
    print("C) stop with live child RAISED:", type(exc).__name__, exc)
    bad = 1

print("VERDICT:", "PROBLEM" if bad else "ok")
sys.exit(bad)
