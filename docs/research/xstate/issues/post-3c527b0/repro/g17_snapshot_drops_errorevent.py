"""G-17: a pending `ErrorEvent` / `DoneEvent` is SILENTLY DROPPED by
`get_persisted_snapshot()`.

`base_interpreter.py:1007-1010` filters the inbox with
`if isinstance(e, Event)`; `ErrorEvent` and `DoneEvent` are NamedTuples, not
`Event`s, so an accepted-but-unprocessed invoke failure/completion is not
persisted -- no warning, no record. `from_snapshot` (:1233-1236) likewise
re-materialises every record as a plain `Event`, so even if the shape were
persisted it would come back with the wrong class and no `error`.

#47 added `pending_events` to the snapshot precisely so "a crash between
accept and process" could not lose an event; #80 routed EVERY service and
child failure through `ErrorEvent`, so that guarantee now has a hole
exactly where it matters most.

Two demonstrations:
  A) NATURAL -- poll the real inbox of a real failing invoke and snapshot
     inside the window between enqueue and drain.
  B) DETERMINISTIC -- park one of each event kind and snapshot.
"""
import asyncio
from xstate_statemachine import Event, MachineLogic, create_machine
from xstate_statemachine.events import DoneEvent, ErrorEvent
from xstate_statemachine.interpreter import Interpreter

CFG = {"id": "m", "initial": "w", "states": {
    "w": {"invoke": {"src": "svc", "id": "svc", "onError": {"target": "bad"}}},
    "bad": {"type": "final"}}}

async def blow(i, c, e):
    await asyncio.sleep(0.02)
    raise ValueError("boom")

async def catch_window(it, out):
    """Snapshot the instant the inbox is non-empty."""
    for _ in range(200_000):
        pending = it._snapshot_pending_events()
        if pending:
            out["pend"] = [f"{type(e).__name__}:{e.type}" for e in pending]
            out["snap"] = [r["type"] for r in
                           it.get_persisted_snapshot()["pending_events"]]
            return
        await asyncio.sleep(0)

async def main():
    # --- A) natural ---
    it = Interpreter(create_machine(CFG, logic=MachineLogic(services={"svc": blow})))
    await it.start()
    out = {}
    await asyncio.wait_for(catch_window(it, out), 3)
    print("A) real inbox held      :", out.get("pend"))
    print("A) snapshot persisted   :", out.get("snap"))
    print("A) failure survived     :",
          any("error.platform" in x for x in out.get("snap", [])),
          "  <-- the failure is GONE from the snapshot")
    await it.stop()

    # --- B) deterministic ---
    it2 = Interpreter(create_machine(CFG, logic=MachineLogic(services={"svc": blow})))
    await it2.start()
    it2._put_inbox(ErrorEvent("error.platform.svc", ValueError("boom"), "svc"))
    it2._put_inbox(DoneEvent("done.invoke.svc", {"ok": 1}, "svc"))
    it2._put_inbox(Event("USER_EVT"))
    print("B) parked in inbox      :",
          [f"{type(e).__name__}:{e.type}" for e in it2.pending_events])
    print("B) snapshot persisted   :",
          [r["type"] for r in it2.get_persisted_snapshot()["pending_events"]],
          "  <-- both engine events dropped")
    await it2.stop()

asyncio.run(main())
