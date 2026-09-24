import asyncio, warnings
from xstate_statemachine import Interpreter, create_machine
from xstate_statemachine.events import Event, is_system_event, ErrorEvent

CFG={"id":"m","initial":"a","strict":True,"states":{"a":{"on":{"GO":"b"}},"b":{}}}
async def main():
    i=Interpreter(create_machine(CFG)); await i.start()
    for t in ["done.review","DONE.review","error.validation","after.5","xstate.foo","nope"]:
        try:
            await i.send(t); r="ACCEPTED"
        except Exception as e: r=type(e).__name__
        print(f"  strict send {t!r:22} -> {r}")
    await i.stop()
    print("is_system_event(Event('done.review')) =", is_system_event(Event("done.review")))
asyncio.run(main())
