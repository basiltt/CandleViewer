"""S-probe 8: on the ASYNC engine, restored priority-lane events are placed in
`_priority_queue`; `drain_pending()` reads only `_event_queue`, so a shutdown
path that persists "every accepted-but-unprocessed event" silently LOSES them.
`_snapshot_pending_events()` (the get_persisted_snapshot path) does include
them, so the two durability paths disagree. The sync engine drains all four."""
import asyncio, json
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {
    "P1": "a", "P2": "a", "I1": "a", "I2": "a"}}}}
R = lambda t, lane: {"type": t, "kind": "event", "payload": {},
                     **({"lane": lane} if lane else {})}
RECS = [R("I1", None), R("P1", "priority"), R("I2", None), R("P2", "priority")]

def blob(h):
    return json.dumps({"version": 3, "machine_id": "m", "machine_hash": h,
        "status": "running", "configuration": ["m", "m.a"], "state_ids": ["m.a"],
        "context": {}, "history": {}, "actors": {}, "system": {}, "deferred": [],
        "scheduled_sends": [], "output": None, "error": None, "taken_at": 0.0,
        "value": "a", "pending_events": RECS})

async def main():
    m = create_machine(CFG, logic=MachineLogic())
    h = Interpreter(m).get_persisted_snapshot()["machine_hash"]
    a = Interpreter.from_snapshot(blob(h), m)
    view = [getattr(e, "type", e) for e in a._snapshot_pending_events()]
    drained = [getattr(e, "type", e) for e in await a.drain_pending()]
    print("async snapshot view :", view)
    print("async drain_pending :", drained)
    print("LOST BY ASYNC DRAIN :", [t for t in view if t not in drained])
    s = SyncInterpreter.from_snapshot(blob(h), m)
    print("sync  drain_pending :", [getattr(e, "type", e) for e in s.drain_pending()])

asyncio.run(asyncio.wait_for(main(), 25))
