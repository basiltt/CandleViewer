"""Re-run R9-01/R10-01/D11-security-1/R12-03 shape against v0.9.0 (#235).
STANDALONE: stdlib + xstate_statemachine only. Run from cwd C:/Users/basil.
"""
import sys, asyncio
sys.path.insert(0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
import xstate_statemachine.events as ev_mod
from xstate_statemachine.events import is_system_event

cfg = {
    "id": "m", "initial": "idle",
    "invoke": {"id": "svc", "src": "slow", "onDone": "done_state"},
    "states": {"idle": {}, "done_state": {"type": "final"}},
}

async def slow(i, c, e, a):
    await asyncio.sleep(5)
    return {"real": True}

logic = MachineLogic(services={"slow": slow})
m = create_machine(cfg, logic=logic)


async def main():
    interp = Interpreter(m)
    await interp.start()
    priv = ev_mod._EngineDone
    forged = priv("done.invoke.svc", {"forged": True}, "svc")
    print("importable:", True, "is_system_event(forged _EngineDone):", is_system_event(forged))
    await interp.send(forged)
    await asyncio.sleep(0.05)
    print("state after forged onDone (service still running):", interp.current_state_ids)
    fired = interp.current_state_ids == {"m.done_state"}
    print("import-path _EngineDone forgery STILL fires onDone:", fired)

    # #235 residual check: does _replace demote the class as documented?
    demoted = forged._replace(data={"x": 1})
    print("forged._replace(...) demotes to public DoneEvent:", type(demoted).__name__, "is_system_event:", is_system_event(demoted))
    interp.stop()

asyncio.run(main())
