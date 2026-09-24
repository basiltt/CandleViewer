"""G-4: the library's own LoggingInspector trips ErrorEvent.data's
DeprecationWarning, from library code the user cannot change."""
import asyncio, warnings, logging
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter
from xstate_statemachine.plugins import LoggingInspector

logging.basicConfig(level=logging.INFO)

CFG = {"id": "m", "initial": "work",
       "states": {"work": {"invoke": {"src": "svc", "id": "svc",
                                      "onError": {"target": "bad"}}},
                  "bad": {"type": "final"}}}

async def boom(i, c, e): raise ValueError("boom")

async def main():
    m = create_machine(CFG, logic=MachineLogic(services={"svc": boom}))
    it = Interpreter(m)
    it.use(LoggingInspector())
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await it.start()
        await asyncio.sleep(0.2)
        dep = [x for x in w if issubclass(x.category, DeprecationWarning)]
        print("state:", it.current_state_ids)
        print("DeprecationWarnings raised:", len(dep))
        for x in dep:
            print("  ", x.filename.split("\\")[-1] + ":" + str(x.lineno), "|", x.message)
    await it.stop()

asyncio.run(main())
