"""G5 -- _chain_owed under 100 concurrent never-completing coroutine
services + stop() (targets #179's _chain_owed bookkeeping). Arms 100
invoked async services that never return (await an Event that's never
set), then calls stop(). Must not hang, and must not leak. Bounded with
a hard watchdog."""
from __future__ import annotations
import asyncio, logging, sys, time
logging.disable(logging.CRITICAL)
LIB = "<workspace>/_ref/xstate-statemachine/src"
if LIB not in sys.path:
    sys.path.insert(0, LIB)
from xstate_statemachine import Event, Interpreter, MachineLogic, create_machine  # noqa: E402

N = 100
CFG = {
    "id": "owed",
    "initial": "idle",
    "context": {},
    "on": {"GO": {"target": "work"}},
    "states": {
        "idle": {},
        "work": {"invoke": {"id": "svc", "src": "hang", "onDone": {"target": "idle"}}},
    },
}


async def hang(i, c, e):
    await asyncio.Event().wait()  # never completes


async def one_run():
    logic = MachineLogic(services={"hang": hang})
    machine = create_machine(CFG, logic=logic)
    interp = Interpreter(machine)
    await interp.start()
    await interp.send(Event("GO"))
    await asyncio.sleep(0.02)
    owed = getattr(interp, "_chain_owed", None)
    t0 = time.monotonic()
    await asyncio.wait_for(interp.stop(), timeout=5.0)
    elapsed = time.monotonic() - t0
    return owed, interp.status, elapsed


async def main():
    results = []
    for k in range(N):
        try:
            r = await asyncio.wait_for(one_run(), timeout=5.0)
            results.append(r)
        except asyncio.TimeoutError:
            results.append(("TIMEOUT", None, None))
    hangs = sum(1 for r in results if r[0] == "TIMEOUT")
    max_elapsed = max((r[2] for r in results if r[2] is not None), default=None)
    print("runs:", N, "hangs/timeouts:", hangs, "max stop() elapsed:", max_elapsed)
    print("sample chain_owed values (first 5):", [r[0] for r in results[:5]])


if __name__ == "__main__":
    asyncio.run(main())
