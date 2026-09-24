"""G-3: a restored engine event loses its provenance and becomes USER traffic.
Under 0.8.0 the name `xstate.*` exempted it; #79 removed the name rule and
the restore path does not re-flag it, so the exemption is lost across a
snapshot/restore. Demonstrated via onUnhandled:"error" and via "*"."""
import asyncio, json
from xstate_statemachine import Event, MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter

UNH = {"id": "u", "initial": "a", "onUnhandled": "error",
       "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
STAR = {"id": "s", "initial": "a",
        "states": {"a": {"on": {"*": {"target": "b"}}}, "b": {}}}

async def roundtrip(cfg, evt):
    it = Interpreter(create_machine(cfg, logic=MachineLogic()))
    await it.start()
    it._put_inbox(evt)
    snap = json.dumps(it.get_persisted_snapshot())
    await it.stop()
    it2 = Interpreter.from_snapshot(json.dumps(json.loads(snap)),
                                    create_machine(cfg, logic=MachineLogic()))
    await it2.start()
    await asyncio.sleep(0.1)
    out = (it2.status, repr(it2.error), set(it2.current_state_ids))
    await it2.stop()
    return out

async def direct(cfg, evt):
    it = Interpreter(create_machine(cfg, logic=MachineLogic()))
    await it.start()
    await it.send(evt); await asyncio.sleep(0.1)
    out = (it.status, repr(it.error), set(it.current_state_ids))
    await it.stop()
    return out

async def main():
    esc = Event(type="xstate.error.actor.kid", payload={"error": "x"}, system=True)
    print("onUnhandled=error, escalate event")
    print("  live (system=True) :", await direct(UNH, esc))
    print("  after restore      :", await roundtrip(UNH, esc))
    print("'*' matcher, escalate event")
    print("  live (system=True) :", await direct(STAR, esc))
    print("  after restore      :", await roundtrip(STAR, esc))

asyncio.run(main())
