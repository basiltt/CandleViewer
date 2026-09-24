"""G-2/G-3: snapshot round-trip of (a) a pending engine ErrorEvent/DoneEvent
and (b) the Event.system provenance flag."""
import asyncio, json
from xstate_statemachine import Event, MachineLogic, create_machine
from xstate_statemachine.events import DoneEvent, ErrorEvent
from xstate_statemachine.interpreter import Interpreter

CFG = {"id": "m", "initial": "a", "onUnhandled": "error",
       "states": {"a": {"on": {"GO": "b"}}, "b": {}}}

async def main():
    it = Interpreter(create_machine(CFG, logic=MachineLogic()))
    await it.start()
    # Park events in the inbox WITHOUT letting the loop drain them.
    it._put_inbox(ErrorEvent(type="error.platform.svc", error=ValueError("boom"), src="svc"))
    it._put_inbox(DoneEvent(type="done.invoke.svc", data={"ok": 1}, src="svc"))
    it._put_inbox(Event(type="xstate.error.actor.child", payload={"error": "x"}, system=True))
    it._put_inbox(Event(type="USER_EVT", payload={}))
    print("pending before snapshot:", [type(e).__name__ + ":" + e.type for e in it.pending_events])
    snap = it.get_persisted_snapshot()
    print("snapshot pending_events:", json.dumps(snap["pending_events"]))
    snap_str = json.dumps(snap)
    await it.stop()

    it2 = Interpreter.from_snapshot(snap_str, create_machine(CFG, logic=MachineLogic()))
    restored = list(it2.pending_events)
    print("restored:", [(type(e).__name__, e.type, getattr(e, "system", "-")) for e in restored])
    await it2.stop()

asyncio.run(main())
