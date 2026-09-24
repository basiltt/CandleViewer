"""R9-02 triage: (a) strict=True still fires a forged AfterEvent?
(b) restore_event() from a forged persisted record (no "engine" flag)
    -- does the restored PUBLIC AfterEvent still fire the timer?
(c) correct usage control: never construct AfterEvent; real timer.
Standalone: stdlib + xstate_statemachine only."""
import asyncio, json
from xstate_statemachine import create_machine, Interpreter, MachineLogic, AfterEvent
from xstate_statemachine.events import restore_event, is_system_event

CFG = {"id": "m", "initial": "work",
       "states": {"work": {"after": {60000: "expired"}}, "expired": {}}}

def build():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())

async def run(ev, strict):
    i = Interpreter(build()); i.strict = strict
    await i.start()
    try:
        await i.send(ev)
    except Exception as e:
        await i.stop(); return f"refused:{type(e).__name__}"
    await asyncio.sleep(0.05)
    ids = sorted(i.current_state_ids); await i.stop(); return ids

async def main():
    forged = AfterEvent("after.60000.m.work", None, None)
    print("strict=False, forged AfterEvent:", await run(forged, False))
    print("strict=True , forged AfterEvent:", await run(forged, True))
    rec = {"kind": "after", "type": "after.60000.m.work"}   # no "engine": true
    rest = restore_event(rec)
    print("restored type:", type(rest).__name__, "is_system_event:", is_system_event(rest))
    print("strict=False, restored forged record:", await run(rest, False))
    print("strict=True , restored forged record:", await run(rest, True))
    # control: no forgery at all, timer has 60s to run -> must stay in work
    print("control (no event, 0.05s):", await run(("__none__",), False) if False else "n/a")
asyncio.run(main())
