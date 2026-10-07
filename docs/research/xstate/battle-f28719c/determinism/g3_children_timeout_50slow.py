"""G3 — start(children_timeout=) with 50 slow invoked children (targets
R7-03/#181). A parallel machine with 50 regions, each invoking a child
whose entry action sleeps well past the timeout, must not hold up
start(); start() must return within ~children_timeout, the interpreter
must be running, and the slow children must register once their bring-up
completes (no crash, no duplicate registration, no hang)."""
from __future__ import annotations
import asyncio, logging, sys, time
logging.disable(logging.CRITICAL)
LIB = "<workspace>/_ref/xstate-statemachine/src"
if LIB not in sys.path:
    sys.path.insert(0, LIB)
from xstate_statemachine import Interpreter, MachineLogic, create_machine  # noqa: E402

N = 50
CHILD_CFG = {
    "id": "child",
    "initial": "s",
    "states": {"s": {"entry": ["slow_entry"]}},
}


async def slow_entry(i, c, e, a=None):
    await asyncio.sleep(0.5)  # much slower than any reasonable timeout we set


def build_parent():
    regions = {}
    for k in range(N):
        rid = f"r{k}"
        regions[rid] = {
            "initial": "up",
            "states": {
                "up": {
                    "invoke": {"id": f"kid{k}", "src": "child"},
                }
            },
        }
    cfg = {"id": "par", "type": "parallel", "states": regions}
    child_machine = create_machine(CHILD_CFG, logic=MachineLogic(actions={"slow_entry": slow_entry}))
    logic = MachineLogic(services={"child": child_machine})
    return create_machine(cfg, logic=logic)


async def main():
    machine = build_parent()
    interp = Interpreter(machine)
    t0 = time.monotonic()
    await interp.start(children_timeout=0.2)
    elapsed = time.monotonic() - t0
    print("start() elapsed:", round(elapsed, 3), "s (timeout budget 0.2s)")
    print("status right after start():", interp.status)
    print("children registered right after start():", len(getattr(interp, "_actors", {}) or getattr(interp, "actors", {})))

    await asyncio.sleep(1.0)
    n_children = len(getattr(interp, "_actors", {}) or getattr(interp, "actors", {}))
    print("children registered after 1.0s settle:", n_children)
    print("status after settle:", interp.status)
    print("last_error:", interp.last_error)
    await interp.stop()


if __name__ == "__main__":
    asyncio.run(main())
