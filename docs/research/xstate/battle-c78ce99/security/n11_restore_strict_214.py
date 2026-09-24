"""STANDALONE: #214 restore-strict matrix + observability.

A  restored USER event under strict:True -> refused, on_invalid_event
   fires EXACTLY once, last_error set.
B  restored engine completion is never "unknown".
C  same matrix on both engines.
"""

import asyncio
import json
import time

from xstate_statemachine import create_machine, Interpreter, MachineLogic
from xstate_statemachine.sync_interpreter import SyncInterpreter
from xstate_statemachine.persistence import structure_hash

CFG = {
    "id": "s", "initial": "w", "context": {},
    "strict": True,
    "states": {
        "w": {"on": {"KNOWN": {"target": "x"},
                     "done.invoke.q": {"target": "d"}}},
        "x": {}, "d": {},
    },
}


class Spy:
    def __init__(self):
        self.invalid = []

    def on_invalid_event(self, interp, event, *a, **k):
        self.invalid.append(getattr(event, "type", event))


def blob(m, records):
    return json.dumps({
        "version": 3, "machine_id": m.id, "machine_hash": structure_hash(m),
        "taken_at": time.time(), "status": "running", "context": {},
        "state_ids": ["s.w"], "value": "w",
        "configuration": ["s", "s.w"], "output": None, "error": None,
        "pending_events": records, "deferred": [], "scheduled_sends": [],
        "history": {}, "actors": {}, "system": {},
    })


CASES = [
    ("undeclared user event", [{"kind": "event", "type": "BOGUS"}]),
    ("declared user event", [{"kind": "event", "type": "KNOWN"}]),
    ("engine done, engine:true",
     [{"kind": "done", "type": "done.invoke.q", "src": "q",
       "engine": True}]),
    ("done WITHOUT engine flag (user traffic)",
     [{"kind": "done", "type": "done.invoke.q", "src": "q"}]),
    ("two identical undeclared events",
     [{"kind": "event", "type": "BOGUS"}, {"kind": "event", "type": "BOGUS"}]),
]


def run_sync(name, recs):
    m = create_machine(dict(CFG))
    spy = Spy()
    it = SyncInterpreter.from_snapshot(blob(m, recs), m)
    it.use(spy)
    it.start()
    time.sleep(0.05)
    le = type(getattr(it, "last_error", None)).__name__ \
        if getattr(it, "last_error", None) else None
    print("SYNC  %-40s state=%s on_invalid_event=%s last_error=%s"
          % (name, sorted(it.current_state_ids), spy.invalid, le), flush=True)
    it.stop()


async def run_async(name, recs):
    m = create_machine(dict(CFG))
    spy = Spy()
    it = Interpreter.from_snapshot(blob(m, recs), m)
    it.use(spy)
    await it.start()
    await asyncio.sleep(0.08)
    le = type(getattr(it, "last_error", None)).__name__ \
        if getattr(it, "last_error", None) else None
    print("ASYNC %-40s state=%s on_invalid_event=%s last_error=%s"
          % (name, sorted(it.current_state_ids), spy.invalid, le), flush=True)
    await it.stop()


async def main():
    for name, recs in CASES:
        run_sync(name, recs)
    for name, recs in CASES:
        await run_async(name, recs)


if __name__ == "__main__":
    asyncio.run(main())
