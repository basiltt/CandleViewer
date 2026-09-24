"""G-1: USER code can mint a system event via the public API and bypass
strict mode, onUnhandled and the "*" wildcard matcher."""
import asyncio
from xstate_statemachine import Event, MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter
from xstate_statemachine import events as ev

print("is_system_event(Event('X'))              =", ev.is_system_event(Event("X")))
print("is_system_event(Event('X', system=True)) =", ev.is_system_event(Event("X", system=True)))
print()

STAR = {"id": "s", "initial": "a",
        "states": {"a": {"on": {"*": {"target": "b"}}}, "b": {}}}
STRICT = {"id": "t", "initial": "a",
          "states": {"a": {"on": {"GO": {"target": "b"}}}, "b": {}}}
UNH = {"id": "u", "initial": "a", "onUnhandled": "error",
       "states": {"a": {"on": {"GO": {"target": "b"}}}, "b": {}}}

async def main():
    # --- 1. "*" wildcard ---
    it = await Interpreter(create_machine(STAR, logic=MachineLogic())).start()
    await it.send(Event("ANYTHING")); await asyncio.sleep(0.05)
    print("A) plain  Event('ANYTHING')  -> state", it.current_state_ids, "(expect s.b)")
    await it.stop()
    it = await Interpreter(create_machine(STAR, logic=MachineLogic())).start()
    await it.send(Event("ANYTHING", system=True)); await asyncio.sleep(0.05)
    print("B) forged Event(system=True) -> state", it.current_state_ids, "(bypasses '*' if s.a)")
    await it.stop()
    print()

    # --- 2. strict mode ---
    it2 = await Interpreter(create_machine(STRICT, logic=MachineLogic()), strict=True).start()
    for label, e in (("plain ", Event("NOT_DECLARED")),
                     ("forged", Event("NOT_DECLARED", system=True))):
        try:
            await it2.send(e); print(f"C) strict {label}: ACCEPTED")
        except Exception as exc:
            print(f"C) strict {label}: {type(exc).__name__}")
    await it2.stop()
    print()

    # --- 3. onUnhandled: "error" ---
    for label, e in (("plain ", Event("NOPE")), ("forged", Event("NOPE", system=True))):
        it3 = await Interpreter(create_machine(UNH, logic=MachineLogic())).start()
        try:
            await it3.send(e); await asyncio.sleep(0.05)
            print(f"D) onUnhandled=error {label}: no raise, status={it3.status}, err={it3.error!r}")
        except Exception as exc:
            print(f"D) onUnhandled=error {label}: {type(exc).__name__}")
        await it3.stop()

asyncio.run(main())
