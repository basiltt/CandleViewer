"""F3 - threadsafe done-callback double-fire probe (targets #172).

Attack: cancel a send_threadsafe future ourselves right after submission, on
top of the interpreter's own settle path, to see if the in-flight counter
can be decremented twice (once by our external done-callback landing before
the interpreter's, once by the interpreter's), driving it negative or
leaving a stale positive that would permanently gate the chain-budget reset.
"""
from __future__ import annotations

import asyncio
import logging
import sys

logging.disable(logging.CRITICAL)
LIB = "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from xstate_statemachine import Event, Interpreter, MachineLogic, create_machine  # noqa: E402

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"EV": {"actions": []}}}}}


async def main():
    machine = create_machine(CFG, logic=MachineLogic())
    interp = Interpreter(machine)
    await interp.start()

    futs = []
    for _ in range(100):
        fut = interp.send_threadsafe(Event("EV"), internal=True)
        futs.append(fut)
        # Attach our OWN extra done-callback that also inspects/mutates
        # nothing but races the interpreter's internal one.
        fut.add_done_callback(lambda f: None)
        if len(futs) % 3 == 0:
            fut.cancel()  # attempt to force an alternate completion path

    await asyncio.sleep(0.3)
    await interp.stop()
    await asyncio.sleep(0.1)

    print("in_flight_after_stop:", interp._threadsafe_self_sends_in_flight)
    cancelled = sum(1 for f in futs if f.cancelled())
    done = sum(1 for f in futs if f.done())
    print("cancelled:", cancelled, "done:", done, "total:", len(futs))


if __name__ == "__main__":
    asyncio.run(main())
