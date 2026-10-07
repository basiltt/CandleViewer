"""F2b — async-def-service variant of F2 (targets #173 pool sizing was
`def`-only in the prior pass; async def services don't use the executor
pool at all, but stop()-mid-service safety must hold for them too)."""
from __future__ import annotations
import asyncio, logging, sys, time
logging.disable(logging.CRITICAL)
LIB = "<workspace>/_ref/xstate-statemachine/src"
if LIB not in sys.path:
    sys.path.insert(0, LIB)
from xstate_statemachine import Event, Interpreter, MachineLogic, create_machine  # noqa: E402

CONFIG = {
    "id": "poolone",
    "initial": "idle",
    "context": {"done": 0},
    "on": {"GO": {"target": "work", "internal": False}},
    "states": {
        "idle": {},
        "work": {
            "invoke": {"id": "svcid", "src": "svc", "onDone": {"target": "idle", "actions": ["mark"]}},
        },
    },
}


async def svc(interp, ctx, ev):
    await asyncio.sleep(0.05)
    return "ok"


def mark(interp, ctx, ev, action_def=None):
    ctx["done"] = ctx.get("done", 0) + 1


async def main():
    logic = MachineLogic(actions={"mark": mark}, services={"svc": svc})
    machine = create_machine(CONFIG, logic=logic)
    interp = Interpreter(machine, service_pool_size=1)
    await interp.start()
    for _ in range(50):
        interp.send(Event("GO"))
        await asyncio.sleep(0.001)
    print("mid_status:", interp.status, "mid_state:", interp.current_state_ids)
    await asyncio.sleep(1.0)
    print("pre_stop_status:", interp.status, "state:", interp.current_state_ids, "done:", interp.context.get("done"))
    stopped_ok = True
    try:
        await interp.stop()
    except Exception as e:
        stopped_ok = False
        print("stop_exc:", repr(e))
    print("stopped_ok:", stopped_ok)
    print("status:", interp.status)
    print("done_count:", interp.context.get("done"))
    print("last_error:", interp.last_error)


if __name__ == "__main__":
    asyncio.run(main())
