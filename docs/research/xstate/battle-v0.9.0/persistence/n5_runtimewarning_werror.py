"""#232 under `-W error`: the RuntimeWarning becomes an exception.  WHERE
does it land -- in the action (breaking the step), in the run loop (killing
the interpreter), or in a GC finaliser (unraisable, harmless)?"""
import asyncio, gc, json, os, sys, traceback
from xstate_statemachine import Interpreter, MachineLogic, create_machine

UNRAISABLE = []
sys.unraisablehook = lambda a: UNRAISABLE.append(
    f"{type(a.exc_value).__name__}: {a.exc_value}")

CFG = {"id": "rw", "initial": "a", "context": {"log": [], "action_exc": None},
       "states": {"a": {"entry": ["probe"],
                        "on": {"B": {"actions": ["note"]}}}}}

def build():
    def note(i, c, e, a):
        c["log"].append(e.type)

    def probe(i, c, e, a):
        try:
            i.send("B", wait=True)          # receipt dropped
        except BaseException as ex:         # noqa: BLE001
            c["action_exc"] = f"{type(ex).__name__}: {ex}"
    return create_machine(CFG, logic=MachineLogic(actions={"probe": probe,
                                                           "note": note}))

async def main():
    loop_errors = []
    asyncio.get_running_loop().set_exception_handler(
        lambda l, ctx: loop_errors.append(str(ctx.get("exception") or
                                              ctx.get("message"))))
    i = Interpreter(build())
    start_exc = None
    try:
        await i.start()
        await asyncio.sleep(0.2)
    except BaseException as ex:                # noqa: BLE001
        start_exc = f"{type(ex).__name__}: {ex}"
    log = list(i.context["log"])
    action_exc = i.context["action_exc"]
    status = i.status
    try:
        await i.stop()
    except BaseException as ex:                # noqa: BLE001
        loop_errors.append(f"stop: {type(ex).__name__}: {ex}")
    del i
    for _ in range(3):
        gc.collect()
        await asyncio.sleep(0.02)
    print(json.dumps({"W": sys.warnoptions,
                      "start_exc": start_exc,
                      "action_saw": action_exc,
                      "log": log, "status_after": status,
                      "loop_exception_handler": loop_errors,
                      "unraisable": UNRAISABLE,
                      "machine_still_worked": log == ["B"]}, indent=1))

asyncio.run(main())
