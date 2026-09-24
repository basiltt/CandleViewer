"""Sharper: does send(engine_event, wait=True) fail an onUnhandled:'error'
machine because _detach() strips provenance? Compare wait=True vs wait=False."""
import sys, asyncio
def run(wait):
    sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
    from xstate_statemachine import create_machine, MachineLogic, Interpreter
    from xstate_statemachine.events import system_event
    CFG={"id":"m","initial":"a","onUnhandled":"error","states":{"a":{"on":{"GO":"b"}},"b":{}}}
    async def main():
        i=Interpreter(create_machine(CFG, logic=MachineLogic())); await i.start()
        await i.send(system_event("xstate.error.actor.child", error="boom"), wait=wait)
        await asyncio.sleep(0.3)
        print(f"  wait={str(wait):5s} -> status={i.status:8s} error={type(i.error).__name__ if i.error else None}")
        if i.status=="running": await i.stop()
    asyncio.run(main())
print("engine-minted event sent to an onUnhandled:'error' machine:")
run(False)   # no _detach
run(True)    # _detach -> dataclasses.replace -> provenance dropped
