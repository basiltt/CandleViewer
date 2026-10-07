"""G1 — async-def service completions are charged to the chain budget
(targets R7-01/#179). A machine whose invoked service is `async def` and
whose onDone re-enters the same state (invoke -> onDone -> invoke ...)
must trip RunawayChainError at the SAME lap count as the identical
machine with a `def` (sync) service. Round-6-era bug: async completions
published via send() landed on the public inbox uncharged and reset the
settle budget every lap, making maxIterations inert for async services."""
from __future__ import annotations
import asyncio, logging, sys
logging.disable(logging.CRITICAL)
LIB = "<workspace>/_ref/xstate-statemachine/src"
if LIB not in sys.path:
    sys.path.insert(0, LIB)
from xstate_statemachine import Interpreter, MachineLogic, create_machine  # noqa: E402
from xstate_statemachine.exceptions import RunawayChainError  # noqa: E402

CFG = {
    "id": "cyc",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "invoke": {"id": "s", "src": "svc", "onDone": {"target": "a", "actions": ["bump"], "reenter": True}},
        }
    },
}


def bump(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


def svc_sync(i, c, e):
    return 1


async def svc_async(i, c, e):
    return 1


async def run(is_async_service):
    logic = MachineLogic(actions={"bump": bump}, services={"svc": svc_async if is_async_service else svc_sync})
    machine = create_machine(CFG, logic=logic)
    interp = Interpreter(machine)
    await interp.start()
    deadline = asyncio.get_event_loop().time() + 15.0
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.01)
        if interp.last_error is not None:
            break
    tripped = isinstance(interp.last_error, RunawayChainError)
    n = interp.context.get("n")
    await interp.stop()
    return tripped, n


async def main():
    t_sync, n_sync = await run(False)
    t_async, n_async = await run(True)
    print("sync  service: tripped=%s n=%s" % (t_sync, n_sync))
    print("async service: tripped=%s n=%s" % (t_async, n_async))
    print("parity(both tripped, same n):", t_sync and t_async and n_sync == n_async)


if __name__ == "__main__":
    asyncio.run(main())
