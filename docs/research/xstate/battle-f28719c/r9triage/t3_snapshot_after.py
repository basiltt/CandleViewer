"""R9-02: forged `after` record inside a restored snapshot -- does it
bypass strict (enqueued directly, no send()-time check) and fire a 60s
timer instantly?  Standalone."""
import asyncio, json
from xstate_statemachine import create_machine, Interpreter, MachineLogic

CFG = {"id": "m", "initial": "work",
       "states": {"work": {"after": {60000: "expired"}, "on": {"GO": "other"}},
                  "expired": {}, "other": {}}}
def build():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())

async def main():
    i = Interpreter(build()); i.strict = True
    await i.start(); await asyncio.sleep(0.02)
    snap = i.get_snapshot()
    await i.stop()
    snap = json.loads(snap) if isinstance(snap, str) else snap
    for key in ("pending", "pending_events", "queue", "deferred"):
        if key in snap:
            print("slot:", key, "->", snap[key])
    snap.setdefault("pending_events", []).append(
        {"kind": "after", "type": "after.60000.m.work"})
    try:
        j2 = Interpreter.from_snapshot(json.dumps(snap), build())
    except Exception as e:
        print("restore refused:", type(e).__name__, e); return
    j2.strict = True
    await j2.start()
    await asyncio.sleep(0.1)
    print("after restore, states:", sorted(j2.current_state_ids))
    await j2.stop()
asyncio.run(main())
