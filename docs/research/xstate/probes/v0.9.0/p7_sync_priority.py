"""S-probe 7: #233 sync priority-lane restore ordering vs async two-lane."""
import asyncio, json
from xstate_statemachine import (create_machine, MachineLogic, Interpreter,
                                 SyncInterpreter)
CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {
    "P1": "a", "P2": "a", "I1": "a", "I2": "a"}}}}

def blob(recs):
    return json.dumps({
        "version": 3, "machine_id": "m", "machine_hash": H,
        "status": "running", "configuration": ["m", "m.a"],
        "state_ids": ["m.a"], "context": {}, "history": {}, "actors": {},
        "system": {}, "deferred": [], "scheduled_sends": [],
        "output": None, "error": None, "taken_at": 0.0,
        "value": "a", "pending_events": recs})

R = lambda t, lane: {"type": t, "kind": "event", "payload": {},
                     **({"lane": lane} if lane else {})}
# inbox, priority, inbox, priority -> priority ones must come first, FIFO
RECS = [R("I1", None), R("P1", "priority"), R("I2", None), R("P2", "priority")]

async def main():
    global H
    m = create_machine(CFG, logic=MachineLogic())
    H = Interpreter(m).get_persisted_snapshot()["machine_hash"]
    a = Interpreter.from_snapshot(blob(RECS), m)
    print("async drained:", [getattr(e, "type", e) for e in await a.drain_pending()])
    s = SyncInterpreter.from_snapshot(blob(RECS), m)
    print("sync  drained:", [getattr(e, "type", e) for e in s.drain_pending()])

asyncio.run(asyncio.wait_for(main(), 25))
