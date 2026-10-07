"""#75's _detach() uses dataclasses.replace(). `_provenance` is init=False, so
replace() DROPS it: an engine-minted Event re-sent with wait=True becomes USER
traffic -- the exact class of bug #85/#86 was meant to close."""
import sys, asyncio, dataclasses
sys.path.insert(0,"<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine.events import system_event, is_system_event
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.exceptions import UnhandledEventError
ev = system_event("___xstate_statemachine_init___")
print("minted system?            ", is_system_event(ev))
print("dataclasses.replace(ev)   ", is_system_event(dataclasses.replace(ev)), "<- _detach() path")
print()
CFG={"id":"m","initial":"a","onUnhandled":"error","states":{"a":{"on":{"GO":"b"}},"b":{}}}
async def main():
    i=Interpreter(create_machine(CFG, logic=MachineLogic())); await i.start()
    esc = system_event("xstate.error.actor.child", error="boom")
    r = await i.send(esc, wait=True)     # wait=True + caller's own object -> _detach
    await asyncio.sleep(0.2)
    print("send(system_event, wait=True): receipt.error =",
          type(r.error).__name__ if r.error else None, "| status:", i.status)
    print("VERDICT:", "engine event demoted to USER traffic -> onUnhandled fired"
          if r.error else "provenance preserved")
    await i.stop()
asyncio.run(main())
