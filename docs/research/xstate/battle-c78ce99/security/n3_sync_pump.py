"""STANDALONE: does the SYNC engine ever fire a raise(delay=) without an
external pump?  And does a restored scheduled_send fire on the next send()?
"""

import json
import time

from xstate_statemachine import create_machine
from xstate_statemachine.sync_interpreter import SyncInterpreter

CFG = {
    "id": "h", "initial": "a", "context": {},
    "states": {
        "a": {
            "entry": [{"type": "raise",
                       "params": {"event": "PONG", "delay": 100}}],
            "on": {"PONG": {"target": "b"}, "NUDGE": {}},
        },
        "b": {},
    },
}

m = create_machine(dict(CFG))
it = SyncInterpreter(m).start()
time.sleep(0.4)
print("sync after 400ms idle:", sorted(it.current_state_ids), flush=True)
it.send("NUDGE")
print("sync after one NUDGE send:", sorted(it.current_state_ids), flush=True)
for _ in range(5):
    it.send("NUDGE")
    time.sleep(0.05)
print("sync after 5 more NUDGEs:", sorted(it.current_state_ids), flush=True)
it.stop()

# restored path
m2 = create_machine(dict(CFG))
i2 = SyncInterpreter(m2).start()
snap = json.loads(i2.get_snapshot())
i2.stop()
print("persisted scheduled_sends:", snap["scheduled_sends"], flush=True)
i3 = SyncInterpreter.from_snapshot(json.dumps(snap), m2).start()
time.sleep(0.4)
print("restored, idle 400ms:", sorted(i3.current_state_ids), flush=True)
for _ in range(5):
    i3.send("NUDGE")
    time.sleep(0.05)
print("restored, after 5 NUDGEs:", sorted(i3.current_state_ids), flush=True)
i3.stop()
